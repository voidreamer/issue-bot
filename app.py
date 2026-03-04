"""
Mattermost -> LLM -> GitLab/GitHub Issue Creator

Routes + wiring only. Business logic lives in extracted modules:
  config.py, parser.py, store.py, llm.py, gitlab.py, github.py,
  mattermost.py, templates.py
"""

import logging, uuid, asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
import httpx

from config import load_config, resolve_project
from parser import parse_issue_command
from store import Store
from templates import get_template, get_template_names
from llm import call_llm, call_llm_epic, call_llm_plan
from gitlab import (
    create_gitlab_issue, get_gitlab_iterations, get_gitlab_milestones,
    get_gitlab_project_members, search_gitlab_issues,
)
from github import create_github_issue, search_github_issues, get_github_repo_collaborators
from mattermost import (
    build_preview_message, build_epic_preview_message, build_plan_preview_message,
    build_edit_dialog, build_help_response, build_issue_list_response,
    build_issue_footer, format_labels, post_to_mattermost_channel,
)

# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------
CFG = load_config()
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("issue-bot")

http_client: httpx.AsyncClient = None  # type: ignore
store: Store = None  # type: ignore

@asynccontextmanager
async def lifespan(app):
    global http_client, store
    http_client = httpx.AsyncClient(timeout=60.0)
    store = Store(CFG["db_path"])
    store.cleanup_expired()
    yield
    await http_client.aclose()
    store.close()

app = FastAPI(title="Issue Bot", lifespan=lifespan)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
async def _create_issue(data: dict, user: str) -> dict:
    """Create an issue on the appropriate backend (GitLab or GitHub)."""
    project_id = data.get("project_id", "")
    project_alias = data.get("project_alias", "")
    project_cfg = CFG["projects"].get(project_alias, {})
    backend = project_cfg.get("backend", "gitlab")

    description = data["description"] + build_issue_footer(data, user)
    extra = {}
    if data.get("milestone_id"):
        extra["milestone_id"] = int(data["milestone_id"])
    if data.get("iteration_id"):
        extra["iteration_id"] = int(data["iteration_id"])
    if data.get("assignee_id"):
        extra["assignee_id"] = int(data["assignee_id"])

    if backend == "github":
        return await create_github_issue(
            http_client, CFG, repo=project_id,
            title=data["title"], description=description,
            labels=data.get("labels", []), weight=data.get("points", 1), **extra,
        )
    else:
        return await create_gitlab_issue(
            http_client, CFG, project_id=project_id,
            title=data["title"], description=description,
            labels=data.get("labels", []), weight=data.get("points", 1), **extra,
        )


def _issue_created_msg(data: dict, issue: dict, user: str) -> str:
    label_str = format_labels(data.get("labels", []))
    project_alias = data.get("project_alias", "")
    project_tag = ""
    if project_alias and project_alias != "default":
        project_name = CFG["projects"].get(project_alias, {}).get("name", project_alias)
        project_tag = f" | Project: **{project_name}**"
    return (
        f"### Issue #{issue['iid']} created\n"
        f"**[{data['title']}]({issue['web_url']})**\n"
        f"Points: **{data.get('points', 1)}** | Labels: {label_str}{project_tag}\n"
        f"_by @{data.get('user', user)}_"
    )


# ---------------------------------------------------------------------------
# Slash command
# ---------------------------------------------------------------------------
@app.post("/slash/issue")
async def handle_slash_issue(request: Request):
    form = await request.form()
    token = form.get("token", "")
    text  = form.get("text", "").strip()
    user  = form.get("user_name", "unknown")
    channel_id = form.get("channel_id", "")

    if token != CFG["mm_slash_token"]:
        raise HTTPException(status_code=403, detail="Invalid token")

    cmd = parse_issue_command(
        text,
        project_aliases=set(CFG["projects"].keys()),
        template_names=get_template_names(),
    )

    # --- help ---
    if cmd.action == "help":
        return JSONResponse(build_help_response(CFG))

    # --- list ---
    if cmd.action == "list":
        try:
            alias, project = resolve_project(CFG, cmd.project)
        except KeyError as e:
            return JSONResponse({"response_type": "ephemeral", "text": str(e)})
        backend = project.get("backend", "gitlab")
        if backend == "github":
            issues = await search_github_issues(http_client, CFG, repo=project["id"])
        else:
            issues = await search_gitlab_issues(http_client, CFG, project_id=project["id"])
        return JSONResponse(build_issue_list_response(issues, project_alias=alias))

    # --- search ---
    if cmd.action == "search":
        if not cmd.search_query:
            return JSONResponse({"response_type": "ephemeral", "text": "Usage: `/issue search <query>`"})
        _, project = resolve_project(CFG, "")
        backend = project.get("backend", "gitlab")
        if backend == "github":
            issues = await search_github_issues(http_client, CFG, repo=project["id"], query=cmd.search_query)
        else:
            issues = await search_gitlab_issues(http_client, CFG, project_id=project["id"], query=cmd.search_query)
        return JSONResponse(build_issue_list_response(issues, query=cmd.search_query))

    # --- epic ---
    if cmd.action == "epic":
        if not cmd.prompt:
            return JSONResponse({"response_type": "ephemeral", "text": "Usage: `/issue epic <points> <goal>`"})
        try:
            alias, project = resolve_project(CFG, cmd.project)
        except KeyError as e:
            return JSONResponse({"response_type": "ephemeral", "text": str(e)})
        try:
            epic_data = await call_llm_epic(http_client, CFG, cmd.prompt, cmd.points, labels=project.get("labels", ""))
            epic_data["user"] = user
            epic_data["project_alias"] = alias
            epic_data["project_id"] = project["id"]
            epic_data["original_prompt"] = cmd.prompt
            epic_data["points"] = cmd.points
            epic_data["type"] = "epic"
            issue_id = uuid.uuid4().hex[:12]
            store.save_pending(issue_id, epic_data, user_id=user, channel_id=channel_id, project_alias=alias)
            return JSONResponse(build_epic_preview_message(CFG, issue_id, epic_data))
        except Exception as e:
            log.exception("Epic generation failed")
            return JSONResponse({"response_type": "ephemeral", "text": f"Epic generation failed: {e}"})

    # --- plan ---
    if cmd.action == "plan":
        if not cmd.prompt:
            return JSONResponse({"response_type": "ephemeral", "text": "Usage: `/issue plan <goals>`"})
        try:
            alias, project = resolve_project(CFG, cmd.project)
        except KeyError as e:
            return JSONResponse({"response_type": "ephemeral", "text": str(e)})
        try:
            plan_data = await call_llm_plan(http_client, CFG, cmd.prompt, labels=project.get("labels", ""))
            plan_data["user"] = user
            plan_data["project_alias"] = alias
            plan_data["project_id"] = project["id"]
            plan_data["original_prompt"] = cmd.prompt
            plan_data["type"] = "plan"
            issue_id = uuid.uuid4().hex[:12]
            store.save_pending(issue_id, plan_data, user_id=user, channel_id=channel_id, project_alias=alias)
            return JSONResponse(build_plan_preview_message(CFG, issue_id, plan_data))
        except Exception as e:
            log.exception("Plan generation failed")
            return JSONResponse({"response_type": "ephemeral", "text": f"Plan generation failed: {e}"})

    # --- create (default) ---
    if not cmd.prompt:
        return JSONResponse({
            "response_type": "ephemeral",
            "text": ("**Usage:** `/issue [project] [template] <points> <prompt>`\n"
                     "Example: `/issue 3 Build login page with OAuth`\n"
                     "Type `/issue help` for more info."),
        })

    try:
        project_alias, project = resolve_project(CFG, cmd.project)
    except KeyError as e:
        return JSONResponse({"response_type": "ephemeral", "text": str(e)})

    template = get_template(cmd.template)
    project_labels_str = project.get("labels", "")
    log.info(f"[{user}] /issue {project_alias} {cmd.points} {cmd.prompt[:80]}...")

    try:
        issue_data = await call_llm(
            http_client, CFG, cmd.prompt, cmd.points,
            labels=project_labels_str, template_extra=template["system_prompt_extra"],
        )
        # Merge template default labels
        if template["default_labels"]:
            existing = set(issue_data.get("labels", []))
            for lbl in template["default_labels"]:
                if lbl not in existing:
                    issue_data.setdefault("labels", []).append(lbl)

        issue_data["points"] = cmd.points
        issue_data["user"] = user
        issue_data["project_alias"] = project_alias
        issue_data["project_id"] = project["id"]
        issue_data["original_prompt"] = cmd.prompt
        issue_data["template"] = cmd.template
        issue_data["type"] = "single"

        issue_id = uuid.uuid4().hex[:12]
        store.save_pending(issue_id, issue_data, user_id=user, channel_id=channel_id, project_alias=project_alias)
        return JSONResponse(build_preview_message(CFG, issue_id, issue_data))

    except httpx.HTTPStatusError as e:
        log.error(f"HTTP error: {e.response.status_code} - {e.response.text}")
        return JSONResponse({
            "response_type": "ephemeral",
            "text": f"Failed: {e.response.status_code}\n```\n{e.response.text[:300]}\n```",
        })
    except Exception as e:
        log.exception("Unexpected error")
        return JSONResponse({"response_type": "ephemeral", "text": f"Something went wrong: {type(e).__name__}: {e}"})


# ---------------------------------------------------------------------------
# Button actions
# ---------------------------------------------------------------------------
@app.post("/actions/button")
async def handle_button(request: Request):
    payload = await request.json()
    context  = payload.get("context", {})
    action   = context.get("action")
    issue_id = context.get("issue_id")
    user     = payload.get("user_name", "unknown")
    trigger_id = payload.get("trigger_id", "")

    data = store.get_pending(issue_id) if issue_id else None
    if not data:
        return JSONResponse({"update": {"message": "This issue preview has expired. Run `/issue` again.", "props": {}}})

    # --- APPROVE (single issue) ---
    if action == "approve":
        try:
            issue = await _create_issue(data, user)
            store.record_created_issue(
                gitlab_iid=issue["iid"], project_alias=data.get("project_alias", ""),
                title=data["title"], created_by=data.get("user", user),
                gitlab_url=issue["web_url"], data=data,
            )
            store.delete_pending(issue_id)
            return JSONResponse({"update": {"message": _issue_created_msg(data, issue, user), "props": {}}})
        except Exception as e:
            log.exception("Failed to create issue")
            return JSONResponse({"update": {"message": f"Failed to create issue: {e}", "props": {}}})

    # --- APPROVE EPIC ---
    elif action == "approve_epic":
        try:
            project_id = data.get("project_id", "")
            project_alias = data.get("project_alias", "")
            project_cfg = CFG["projects"].get(project_alias, {})
            backend = project_cfg.get("backend", "gitlab")

            # Create parent
            parent = data["parent"]
            parent_data = {**parent, "points": data.get("points", 1), "user": data.get("user", user),
                           "project_alias": project_alias, "project_id": project_id}
            parent_issue = await _create_issue(parent_data, user)
            parent_iid = parent_issue["iid"]
            created_urls = [f"- **[{parent['title']}]({parent_issue['web_url']})** (parent)"]

            store.record_created_issue(
                gitlab_iid=parent_iid, project_alias=project_alias,
                title=parent["title"], created_by=data.get("user", user),
                gitlab_url=parent_issue["web_url"], data=parent,
            )

            # Create children sequentially
            for child in data.get("children", []):
                child_desc = child.get("description", "")
                child_desc += f"\n\nParent: #{parent_iid}"
                child_data = {
                    **child, "description": child_desc,
                    "points": child.get("points", 1), "user": data.get("user", user),
                    "project_alias": project_alias, "project_id": project_id,
                }
                child_issue = await _create_issue(child_data, user)
                created_urls.append(f"- **[{child['title']}]({child_issue['web_url']})** ({child.get('points', 1)} pts)")
                store.record_created_issue(
                    gitlab_iid=child_issue["iid"], project_alias=project_alias,
                    title=child["title"], created_by=data.get("user", user),
                    gitlab_url=child_issue["web_url"], data=child,
                )

            store.delete_pending(issue_id)
            msg = f"### Epic created ({len(data.get('children', []))+1} issues)\n\n" + "\n".join(created_urls)
            return JSONResponse({"update": {"message": msg, "props": {}}})
        except Exception as e:
            log.exception("Failed to create epic")
            return JSONResponse({"update": {"message": f"Failed to create epic: {e}", "props": {}}})

    # --- APPROVE PLAN ---
    elif action == "approve_plan":
        try:
            project_id = data.get("project_id", "")
            project_alias = data.get("project_alias", "")
            created_urls = []
            for issue_item in data.get("issues", []):
                item_data = {
                    **issue_item, "points": issue_item.get("points", 1),
                    "user": data.get("user", user),
                    "project_alias": project_alias, "project_id": project_id,
                }
                created = await _create_issue(item_data, user)
                created_urls.append(f"- **[{issue_item['title']}]({created['web_url']})** ({issue_item.get('points', 1)} pts)")
                store.record_created_issue(
                    gitlab_iid=created["iid"], project_alias=project_alias,
                    title=issue_item["title"], created_by=data.get("user", user),
                    gitlab_url=created["web_url"], data=issue_item,
                )
            store.delete_pending(issue_id)
            msg = f"### Sprint plan created ({len(created_urls)} issues)\n\n" + "\n".join(created_urls)
            return JSONResponse({"update": {"message": msg, "props": {}}})
        except Exception as e:
            log.exception("Failed to create plan")
            return JSONResponse({"update": {"message": f"Failed to create plan: {e}", "props": {}}})

    # --- REGENERATE ---
    elif action == "regenerate":
        try:
            template = get_template(data.get("template", ""))
            project = CFG["projects"].get(data.get("project_alias", ""), {})
            new_data = await call_llm(
                http_client, CFG, data["original_prompt"], data.get("points", 1),
                labels=project.get("labels", ""), template_extra=template["system_prompt_extra"],
            )
            # Preserve metadata
            for key in ("points", "user", "project_alias", "project_id", "original_prompt", "template", "type"):
                if key in data:
                    new_data[key] = data[key]
            store.update_pending(issue_id, new_data)
            return JSONResponse({"update": build_preview_message(CFG, issue_id, new_data)})
        except Exception as e:
            log.exception("Regeneration failed")
            return JSONResponse({"update": {"message": f"Regeneration failed: {e}", "props": {}}})

    # --- EDIT ---
    elif action == "edit":
        project_id = data.get("project_id", "")
        iterations, milestones, members = await asyncio.gather(
            get_gitlab_iterations(http_client, CFG, project_id),
            get_gitlab_milestones(http_client, CFG, project_id),
            get_gitlab_project_members(http_client, CFG, project_id),
        )
        dialog_req = build_edit_dialog(CFG, issue_id, data, iterations, milestones, members)
        dialog_req["trigger_id"] = trigger_id
        try:
            mm_resp = await http_client.post(
                f"{CFG['mm_site_url']}/api/v4/actions/dialogs/open", json=dialog_req)
            mm_resp.raise_for_status()
        except Exception as e:
            log.exception("Failed to open dialog")
            return JSONResponse({"update": {"message": f"Could not open edit dialog: {e}", "props": {}}})
        return JSONResponse({})

    # --- CANCEL ---
    elif action == "cancel":
        store.delete_pending(issue_id)
        return JSONResponse({"update": {"message": "Issue creation cancelled.", "props": {}}})

    return JSONResponse({"update": {"message": "Unknown action.", "props": {}}})


# ---------------------------------------------------------------------------
# Dialog submission
# ---------------------------------------------------------------------------
@app.post("/actions/dialog")
async def handle_dialog(request: Request):
    payload  = await request.json()
    issue_id = payload.get("callback_id", "")
    submission = payload.get("submission", {})
    user     = payload.get("user", {}).get("username", "unknown")

    data = store.get_pending(issue_id)
    if not data:
        return JSONResponse({"errors": {"title": "This issue preview has expired. Run /issue again."}})

    if submission.get("title"):
        data["title"] = submission["title"]
    if submission.get("description"):
        data["description"] = submission["description"]
    if submission.get("points"):
        try: data["points"] = int(submission["points"])
        except ValueError: pass
    if "labels" in submission:
        data["labels"] = [l.strip() for l in submission["labels"].split(",") if l.strip()]
    if submission.get("milestone_id"):
        data["milestone_id"] = submission["milestone_id"]
    if submission.get("iteration_id"):
        data["iteration_id"] = submission["iteration_id"]
    if submission.get("assignee_id"):
        data["assignee_id"] = submission["assignee_id"]
    if submission.get("project_alias"):
        new_alias = submission["project_alias"]
        if new_alias in CFG["projects"]:
            data["project_alias"] = new_alias
            data["project_id"] = CFG["projects"][new_alias]["id"]

    try:
        issue = await _create_issue(data, user)
        store.record_created_issue(
            gitlab_iid=issue["iid"], project_alias=data.get("project_alias", ""),
            title=data["title"], created_by=data.get("user", user),
            gitlab_url=issue["web_url"], data=data,
        )
        store.delete_pending(issue_id)
        log.info(f"Issue #{issue['iid']} created: {data['title']}")
        return JSONResponse({})
    except Exception as e:
        log.exception("Failed to create issue from dialog")
        return JSONResponse({"errors": {"title": f"GitLab error: {e}"}})


# ---------------------------------------------------------------------------
# GitLab webhook notifications
# ---------------------------------------------------------------------------
@app.post("/webhooks/gitlab")
async def handle_gitlab_webhook(request: Request):
    # Verify secret
    secret = CFG.get("webhook_secret", "")
    if secret:
        token = request.headers.get("X-Gitlab-Token", "")
        if token != secret:
            raise HTTPException(status_code=403, detail="Invalid webhook token")

    payload = await request.json()
    object_kind = payload.get("object_kind", "")

    if object_kind == "issue":
        attrs = payload.get("object_attributes", {})
        action = attrs.get("action", "")  # open, close, reopen, update
        title = attrs.get("title", "")
        url = attrs.get("url", "")
        iid = attrs.get("iid", "")
        state = attrs.get("state", "")
        user_info = payload.get("user", {})
        username = user_info.get("username", "unknown")

        channel_id = CFG.get("mm_notify_channel_id", "")
        if channel_id and action in ("open", "close", "reopen"):
            icon = {"open": "🟢", "close": "🔴", "reopen": "🔵"}.get(action, "ℹ️")
            msg = f"{icon} Issue **[#{iid} {title}]({url})** {action}ed by @{username}"
            await post_to_mattermost_channel(http_client, CFG, channel_id, msg)

    return JSONResponse({"status": "ok"})


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------
@app.get("/health")
async def health():
    return {
        "status": "ok",
        "llm_provider": CFG["llm_provider"],
        "projects": list(CFG["projects"].keys()),
    }
