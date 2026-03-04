"""
Mattermost -> LLM -> GitLab Issue Creator (with interactive preview)

Flow:
  1. /issue <points> <prompt>  →  LLM generates issue
  2. Bot posts a preview with [Approve] [Edit] [Cancel] buttons
  3. User clicks Edit  →  Mattermost dialog with editable fields
  4. User clicks Approve  →  creates issue in GitLab
"""

import os, json, re, logging, uuid, time, asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
import httpx

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
GITLAB_TOKEN      = os.environ["GITLAB_TOKEN"]
GITLAB_PROJECT_ID = os.environ["GITLAB_PROJECT_ID"]
GITLAB_URL        = os.environ.get("GITLAB_URL", "https://gitlab.com")
MM_SLASH_TOKEN    = os.environ["MM_SLASH_TOKEN"]
MM_SITE_URL       = os.environ.get("MM_SITE_URL", "http://localhost:8065")

LLM_PROVIDER = os.environ.get("LLM_PROVIDER", "openai")
LLM_API_KEY  = os.environ.get("LLM_API_KEY", "")
LLM_MODEL    = os.environ.get("LLM_MODEL", "")
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "")

PROJECT_LABELS = os.environ.get("PROJECT_LABELS",
    "ai,bug,documentation,enhancement,infrastructure,prototype,research,voice,"
    "priorityhigh,prioritymedium,prioritylow,good first issue,help wanted")
PROJECT_LABELS_LIST = [l.strip() for l in PROJECT_LABELS.split(",")]

BOT_URL = os.environ.get("BOT_URL", "http://localhost:8321")

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("issue-bot")

# ---------------------------------------------------------------------------
# In-memory store for pending issues (keyed by random ID)
# In production you'd use Redis or similar, but for a small team this is fine.
# Entries auto-expire after 30 minutes.
# ---------------------------------------------------------------------------
pending_issues: dict[str, dict] = {}

def cleanup_pending():
    """Remove entries older than 30 min."""
    cutoff = time.time() - 1800
    expired = [k for k, v in pending_issues.items() if v.get("ts", 0) < cutoff]
    for k in expired:
        del pending_issues[k]

# ---------------------------------------------------------------------------
# HTTP client
# ---------------------------------------------------------------------------
http_client: httpx.AsyncClient = None  # type: ignore

@asynccontextmanager
async def lifespan(app):
    global http_client
    http_client = httpx.AsyncClient(timeout=60.0)
    yield
    await http_client.aclose()

app = FastAPI(title="Issue Bot", lifespan=lifespan)

# ---------------------------------------------------------------------------
# LLM abstraction
# ---------------------------------------------------------------------------
PROVIDER_DEFAULTS = {
    "openai":    {"model": "gpt-4o",                      "url": "https://api.openai.com/v1/chat/completions"},
    "anthropic": {"model": "claude-sonnet-4-5-20250514",   "url": "https://api.anthropic.com/v1/messages"},
    "ollama":    {"model": "llama3",                       "url": "http://localhost:11434/v1/chat/completions"},
    "gemini":    {"model": "gemini-2.0-flash",             "url": "https://generativelanguage.googleapis.com/v1beta/chat/completions"},
}

SYSTEM_PROMPT = """You are an expert project manager for a software team. When given a short description \
and story-point weight, you produce a well-structured GitLab issue in Markdown.

RULES:
1. Generate a concise title using a short prefix (e.g. "MVP-XX:" or "INFRA-XX:" or "FIX-XX:") followed by a clear title.
2. The body MUST contain these sections:
   ## Summary
   (1-3 sentences)

   ## Context & Motivation
   (why this matters)

   ## Acceptance Criteria
   - [ ] criterion 1
   - [ ] criterion 2

   ## Technical Notes
   (optional implementation hints)

3. Suggest 1-4 labels from this list: {labels}
   Pick only labels that genuinely fit.
4. Respond ONLY with valid JSON, no markdown fences, no extra text:
   {{"title": "...", "description": "...", "labels": ["label1","label2"]}}"""

FORMATTED_SYSTEM_PROMPT = SYSTEM_PROMPT.format(labels=PROJECT_LABELS)


def format_labels(labels: list[str]) -> str:
    return ", ".join(f"`{l}`" for l in labels) if labels else "_none_"


def build_issue_footer(data: dict, fallback_user: str) -> str:
    return f"\n\n---\n_Created via `/issue` by @{data.get('user', fallback_user)} | {data.get('points', 1)} pts_"


async def call_llm(prompt: str, points: int) -> dict:
    provider = LLM_PROVIDER.lower()
    defaults = PROVIDER_DEFAULTS.get(provider, PROVIDER_DEFAULTS["openai"])
    model    = LLM_MODEL or defaults["model"]
    base_url = LLM_BASE_URL or defaults["url"]
    system   = FORMATTED_SYSTEM_PROMPT
    user_msg = f"Story points: {points}\nDescription: {prompt}"

    if provider == "anthropic":
        resp = await http_client.post(base_url, headers={
            "x-api-key": LLM_API_KEY, "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }, json={"model": model, "max_tokens": 2048, "system": system,
                 "messages": [{"role": "user", "content": user_msg}]})
    else:
        headers = {"content-type": "application/json"}
        if LLM_API_KEY:
            headers["Authorization"] = f"Bearer {LLM_API_KEY}"
        resp = await http_client.post(base_url, headers=headers, json={
            "model": model, "temperature": 0.4,
            "messages": [{"role": "system", "content": system},
                         {"role": "user",   "content": user_msg}]})

    resp.raise_for_status()
    body = resp.json()
    text = (body["content"][0]["text"] if provider == "anthropic"
            else body["choices"][0]["message"]["content"])
    text = re.sub(r"^```(?:json)?\s*", "", text.strip())
    text = re.sub(r"\s*```$", "", text.strip())
    return json.loads(text)


# ---------------------------------------------------------------------------
# GitLab helpers
# ---------------------------------------------------------------------------
async def create_gitlab_issue(title, description, labels, weight, **extra):
    url = f"{GITLAB_URL}/api/v4/projects/{GITLAB_PROJECT_ID}/issues"
    params = {"title": title, "description": description,
              "labels": ",".join(labels), "weight": weight}
    params.update(extra)
    resp = await http_client.post(url,
        headers={"PRIVATE-TOKEN": GITLAB_TOKEN}, json=params)
    resp.raise_for_status()
    return resp.json()


async def get_gitlab_iterations():
    """Fetch active iterations for the project's group."""
    try:
        url = f"{GITLAB_URL}/api/v4/projects/{GITLAB_PROJECT_ID}/iterations?state=opened"
        resp = await http_client.get(url, headers={"PRIVATE-TOKEN": GITLAB_TOKEN})
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return []


async def get_gitlab_milestones():
    """Fetch active milestones."""
    try:
        url = f"{GITLAB_URL}/api/v4/projects/{GITLAB_PROJECT_ID}/milestones?state=active"
        resp = await http_client.get(url, headers={"PRIVATE-TOKEN": GITLAB_TOKEN})
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return []


# ---------------------------------------------------------------------------
# Build Mattermost interactive preview
# ---------------------------------------------------------------------------
def build_preview_message(issue_id: str, data: dict) -> dict:
    """Build an ephemeral message with a preview and action buttons."""
    title   = data["title"]
    desc    = data["description"]
    labels  = data.get("labels", [])
    points  = data.get("points", 1)
    user    = data.get("user", "unknown")

    # Truncate description for preview (show first 800 chars)
    preview_desc = desc if len(desc) <= 800 else desc[:800] + "\n\n_(truncated...)_"
    label_str = format_labels(labels)

    return {
        "response_type": "in_channel",
        "text": (
            f"### Issue Preview\n"
            f"**Title:** {title}\n"
            f"**Points:** {points} | **Labels:** {label_str}\n\n"
            f"---\n{preview_desc}\n---\n"
            f"_by @{user}_"
        ),
        "attachments": [{
            "fallback": "Issue preview actions",
            "actions": [
                {
                    "id": "approve",
                    "name": "Approve & Create",
                    "type": "button",
                    "style": "good",
                    "integration": {
                        "url": f"{BOT_URL}/actions/button",
                        "context": {"action": "approve", "issue_id": issue_id}
                    }
                },
                {
                    "id": "edit",
                    "name": "Edit",
                    "type": "button",
                    "integration": {
                        "url": f"{BOT_URL}/actions/button",
                        "context": {"action": "edit", "issue_id": issue_id}
                    }
                },
                {
                    "id": "cancel",
                    "name": "Cancel",
                    "type": "button",
                    "style": "danger",
                    "integration": {
                        "url": f"{BOT_URL}/actions/button",
                        "context": {"action": "cancel", "issue_id": issue_id}
                    }
                },
            ]
        }]
    }


def build_edit_dialog(issue_id: str, data: dict, iterations: list, milestones: list) -> dict:
    """Build a Mattermost interactive dialog for editing the issue."""
    all_labels = PROJECT_LABELS_LIST
    current_labels = ",".join(data.get("labels", []))

    elements = [
        {
            "display_name": "Title",
            "name": "title",
            "type": "text",
            "default": data.get("title", ""),
            "placeholder": "Issue title",
        },
        {
            "display_name": "Description",
            "name": "description",
            "type": "textarea",
            "default": data.get("description", ""),
            "placeholder": "Full issue description (Markdown)",
            "max_length": 10000,
        },
        {
            "display_name": "Points",
            "name": "points",
            "type": "text",
            "subtype": "number",
            "default": str(data.get("points", 1)),
        },
        {
            "display_name": "Labels (comma-separated)",
            "name": "labels",
            "type": "text",
            "default": current_labels,
            "placeholder": "e.g. ai,infrastructure,priorityhigh",
            "help_text": f"Available: {PROJECT_LABELS}",
        },
    ]

    # Add milestone select if any exist
    if milestones:
        milestone_opts = [{"text": "(none)", "value": ""}]
        milestone_opts += [{"text": m["title"], "value": str(m["id"])} for m in milestones]
        elements.append({
            "display_name": "Milestone",
            "name": "milestone_id",
            "type": "select",
            "options": milestone_opts,
            "default": "",
            "optional": True,
        })

    # Add iteration select if any exist
    if iterations:
        iter_opts = [{"text": "(none)", "value": ""}]
        iter_opts += [{"text": it.get("title", f"Iteration {it['id']}"), "value": str(it["id"])} for it in iterations]
        elements.append({
            "display_name": "Iteration",
            "name": "iteration_id",
            "type": "select",
            "options": iter_opts,
            "default": "",
            "optional": True,
        })

    return {
        "trigger_id": "",  # filled in by caller
        "url": f"{BOT_URL}/actions/dialog",
        "dialog": {
            "callback_id": issue_id,
            "title": "Edit Issue Before Creating",
            "submit_label": "Approve & Create",
            "elements": elements,
        }
    }


# ---------------------------------------------------------------------------
# Slash command endpoint
# ---------------------------------------------------------------------------
@app.post("/slash/issue")
async def handle_slash_issue(request: Request):
    form = await request.form()
    token = form.get("token", "")
    text  = form.get("text", "").strip()
    user  = form.get("user_name", "unknown")

    if token != MM_SLASH_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid token")

    if not text:
        return JSONResponse({
            "response_type": "ephemeral",
            "text": ("**Usage:** `/issue <points> <prompt>`\n"
                     "Example: `/issue 3 Build login page with OAuth`"),
        })

    # Parse points + prompt
    parts = text.split(None, 1)
    try:
        points = int(parts[0])
        prompt = parts[1] if len(parts) > 1 else ""
    except (ValueError, IndexError):
        points = 1
        prompt = text

    if not prompt:
        return JSONResponse({
            "response_type": "ephemeral",
            "text": "Please provide a description after the points.",
        })

    log.info(f"[{user}] /issue {points} {prompt[:80]}...")

    try:
        # 1. Call LLM to generate the issue
        issue_data = await call_llm(prompt, points)
        issue_data["points"] = points
        issue_data["user"] = user

        # 2. Store in pending
        cleanup_pending()
        issue_id = uuid.uuid4().hex[:12]
        pending_issues[issue_id] = {**issue_data, "ts": time.time()}

        # 3. Return interactive preview
        return JSONResponse(build_preview_message(issue_id, issue_data))

    except httpx.HTTPStatusError as e:
        log.error(f"HTTP error: {e.response.status_code} - {e.response.text}")
        return JSONResponse({
            "response_type": "ephemeral",
            "text": f"Failed: {e.response.status_code}\n```\n{e.response.text[:300]}\n```",
        })
    except Exception as e:
        log.exception("Unexpected error")
        return JSONResponse({
            "response_type": "ephemeral",
            "text": f"Something went wrong: {type(e).__name__}: {e}",
        })


# ---------------------------------------------------------------------------
# Button action handler
# ---------------------------------------------------------------------------
@app.post("/actions/button")
async def handle_button(request: Request):
    payload = await request.json()
    context  = payload.get("context", {})
    action   = context.get("action")
    issue_id = context.get("issue_id")
    user     = payload.get("user_name", "unknown")
    trigger_id = payload.get("trigger_id", "")

    if issue_id not in pending_issues:
        return JSONResponse({
            "update": {"message": "This issue preview has expired. Run `/issue` again.", "props": {}}
        })

    data = pending_issues[issue_id]

    # --- APPROVE ---
    if action == "approve":
        try:
            description = data["description"] + build_issue_footer(data, user)

            gl_issue = await create_gitlab_issue(
                title=data["title"],
                description=description,
                labels=data.get("labels", []),
                weight=data.get("points", 1),
            )
            del pending_issues[issue_id]

            issue_url = gl_issue["web_url"]
            iid = gl_issue["iid"]
            label_str = format_labels(data.get("labels", []))

            msg = (
                f"### Issue #{iid} created\n"
                f"**[{data['title']}]({issue_url})**\n"
                f"Points: **{data.get('points', 1)}** | Labels: {label_str}\n"
                f"_by @{data.get('user', user)}_"
            )
            return JSONResponse({
                "update": {"message": msg, "props": {}},
            })
        except Exception as e:
            log.exception("Failed to create issue")
            return JSONResponse({
                "update": {"message": f"Failed to create issue: {e}", "props": {}},
            })

    # --- EDIT ---
    elif action == "edit":
        iterations, milestones = await asyncio.gather(
            get_gitlab_iterations(), get_gitlab_milestones()
        )
        dialog_req = build_edit_dialog(issue_id, data, iterations, milestones)
        dialog_req["trigger_id"] = trigger_id

        # Open dialog via Mattermost API
        try:
            mm_resp = await http_client.post(
                f"{MM_SITE_URL}/api/v4/actions/dialogs/open",
                json=dialog_req,
            )
            mm_resp.raise_for_status()
        except Exception as e:
            log.exception("Failed to open dialog")
            return JSONResponse({
                "update": {"message": f"Could not open edit dialog: {e}", "props": {}},
            })

        # Return empty update — the dialog handles the rest
        return JSONResponse({})

    # --- CANCEL ---
    elif action == "cancel":
        del pending_issues[issue_id]
        return JSONResponse({
            "update": {"message": "Issue creation cancelled.", "props": {}},
        })

    return JSONResponse({
        "update": {"message": "Unknown action.", "props": {}},
    })


# ---------------------------------------------------------------------------
# Dialog submission handler
# ---------------------------------------------------------------------------
@app.post("/actions/dialog")
async def handle_dialog(request: Request):
    payload  = await request.json()
    issue_id = payload.get("callback_id", "")
    submission = payload.get("submission", {})
    user     = payload.get("user", {}).get("username", "unknown")

    if issue_id not in pending_issues:
        return JSONResponse({"errors": {"title": "This issue preview has expired. Run /issue again."}})

    # Update stored data with edited values
    data = pending_issues[issue_id]
    if submission.get("title"):
        data["title"] = submission["title"]
    if submission.get("description"):
        data["description"] = submission["description"]
    if submission.get("points"):
        try:
            data["points"] = int(submission["points"])
        except ValueError:
            pass
    if "labels" in submission:
        data["labels"] = [l.strip() for l in submission["labels"].split(",") if l.strip()]
    if submission.get("milestone_id"):
        data["milestone_id"] = submission["milestone_id"]
    if submission.get("iteration_id"):
        data["iteration_id"] = submission["iteration_id"]

    # Now create the issue
    try:
        description = data["description"] + build_issue_footer(data, user)

        extra = {}
        if data.get("milestone_id"):
            extra["milestone_id"] = int(data["milestone_id"])
        if data.get("iteration_id"):
            extra["iteration_id"] = int(data["iteration_id"])

        gl_issue = await create_gitlab_issue(
            title=data["title"],
            description=description,
            labels=data.get("labels", []),
            weight=data.get("points", 1),
            **extra,
        )
        del pending_issues[issue_id]

        log.info(f"Issue #{gl_issue['iid']} created: {data['title']}")
        return JSONResponse({})

    except Exception as e:
        log.exception("Failed to create issue from dialog")
        return JSONResponse({
            "errors": {"title": f"GitLab error: {e}"}
        })


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------
@app.get("/health")
async def health():
    return {"status": "ok", "llm_provider": LLM_PROVIDER,
            "pending_issues": len(pending_issues)}
