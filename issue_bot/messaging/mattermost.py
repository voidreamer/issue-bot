"""
Mattermost message builders — previews, dialogs, help, issue lists, bot posting.
"""

import logging
import httpx

from issue_bot.core.config import resolve_project, get_project_labels, get_all_labels
from issue_bot.backends.llm import PROVIDER_DEFAULTS

log = logging.getLogger("issue-bot")


def format_labels(labels: list[str]) -> str:
    return ", ".join(f"`{l}`" for l in labels) if labels else "_none_"


def build_issue_footer(data: dict, fallback_user: str) -> str:
    project_alias = data.get("project_alias", "")
    project_tag = f" [{project_alias}]" if project_alias and project_alias != "default" else ""
    return f"\n\n---\n_Created via `/issue` by @{data.get('user', fallback_user)} | {data.get('points', 1)} pts{project_tag}_"


def build_preview_message(cfg: dict, issue_id: str, data: dict) -> dict:
    """Build an ephemeral message with a preview and action buttons."""
    title   = data["title"]
    desc    = data["description"]
    labels  = data.get("labels", [])
    points  = data.get("points", 1)
    user    = data.get("user", "unknown")
    project_alias = data.get("project_alias", "")

    preview_desc = desc if len(desc) <= 800 else desc[:800] + "\n\n_(truncated...)_"
    label_str = format_labels(labels)

    project_tag = ""
    if project_alias and project_alias != "default":
        project_name = cfg["projects"].get(project_alias, {}).get("name", project_alias)
        project_tag = f" | **Project:** {project_name}"

    bot_url = cfg["bot_url"]

    return {
        "response_type": "in_channel",
        "text": (
            f"### Issue Preview\n"
            f"**Title:** {title}\n"
            f"**Points:** {points} | **Labels:** {label_str}{project_tag}\n\n"
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
                        "url": f"{bot_url}/actions/button",
                        "context": {"action": "approve", "issue_id": issue_id}
                    }
                },
                {
                    "id": "regenerate",
                    "name": "Regenerate",
                    "type": "button",
                    "integration": {
                        "url": f"{bot_url}/actions/button",
                        "context": {"action": "regenerate", "issue_id": issue_id}
                    }
                },
                {
                    "id": "edit",
                    "name": "Edit",
                    "type": "button",
                    "integration": {
                        "url": f"{bot_url}/actions/button",
                        "context": {"action": "edit", "issue_id": issue_id}
                    }
                },
                {
                    "id": "cancel",
                    "name": "Cancel",
                    "type": "button",
                    "style": "danger",
                    "integration": {
                        "url": f"{bot_url}/actions/button",
                        "context": {"action": "cancel", "issue_id": issue_id}
                    }
                },
            ]
        }]
    }


def build_epic_preview_message(cfg: dict, issue_id: str, data: dict) -> dict:
    """Build a preview for an epic (parent + children)."""
    parent = data["parent"]
    children = data.get("children", [])
    user = data.get("user", "unknown")
    project_alias = data.get("project_alias", "")
    bot_url = cfg["bot_url"]

    project_tag = ""
    if project_alias and project_alias != "default":
        project_name = cfg["projects"].get(project_alias, {}).get("name", project_alias)
        project_tag = f" | **Project:** {project_name}"

    child_lines = []
    total_points = 0
    for i, child in enumerate(children, 1):
        pts = child.get("points", 1)
        total_points += pts
        labels_str = format_labels(child.get("labels", []))
        child_lines.append(f"{i}. **{child['title']}** ({pts} pts) — {labels_str}")

    children_text = "\n".join(child_lines)

    return {
        "response_type": "in_channel",
        "text": (
            f"### Epic Preview\n"
            f"**Parent:** {parent['title']}\n"
            f"**Labels:** {format_labels(parent.get('labels', []))}{project_tag}\n"
            f"**Total points:** {total_points}\n\n"
            f"---\n**Child Issues:**\n{children_text}\n---\n"
            f"_by @{user}_"
        ),
        "attachments": [{
            "fallback": "Epic preview actions",
            "actions": [
                {
                    "id": "approve_epic",
                    "name": "Approve All",
                    "type": "button",
                    "style": "good",
                    "integration": {
                        "url": f"{bot_url}/actions/button",
                        "context": {"action": "approve_epic", "issue_id": issue_id}
                    }
                },
                {
                    "id": "cancel",
                    "name": "Cancel",
                    "type": "button",
                    "style": "danger",
                    "integration": {
                        "url": f"{bot_url}/actions/button",
                        "context": {"action": "cancel", "issue_id": issue_id}
                    }
                },
            ]
        }]
    }


def build_plan_preview_message(cfg: dict, issue_id: str, data: dict) -> dict:
    """Build a preview for a sprint plan (batch of issues)."""
    issues = data.get("issues", [])
    user = data.get("user", "unknown")
    project_alias = data.get("project_alias", "")
    bot_url = cfg["bot_url"]

    project_tag = ""
    if project_alias and project_alias != "default":
        project_name = cfg["projects"].get(project_alias, {}).get("name", project_alias)
        project_tag = f" | **Project:** {project_name}"

    issue_lines = []
    total_points = 0
    for i, issue in enumerate(issues, 1):
        pts = issue.get("points", 1)
        total_points += pts
        labels_str = format_labels(issue.get("labels", []))
        issue_lines.append(f"{i}. **{issue['title']}** ({pts} pts) — {labels_str}")

    issues_text = "\n".join(issue_lines)

    return {
        "response_type": "in_channel",
        "text": (
            f"### Sprint Plan Preview\n"
            f"**Issues:** {len(issues)} | **Total points:** {total_points}{project_tag}\n\n"
            f"---\n{issues_text}\n---\n"
            f"_by @{user}_"
        ),
        "attachments": [{
            "fallback": "Plan preview actions",
            "actions": [
                {
                    "id": "approve_plan",
                    "name": "Approve All",
                    "type": "button",
                    "style": "good",
                    "integration": {
                        "url": f"{bot_url}/actions/button",
                        "context": {"action": "approve_plan", "issue_id": issue_id}
                    }
                },
                {
                    "id": "cancel",
                    "name": "Cancel",
                    "type": "button",
                    "style": "danger",
                    "integration": {
                        "url": f"{bot_url}/actions/button",
                        "context": {"action": "cancel", "issue_id": issue_id}
                    }
                },
            ]
        }]
    }


def build_edit_dialog(
    cfg: dict,
    issue_id: str,
    data: dict,
    iterations: list,
    milestones: list,
    members: list | None = None,
) -> dict:
    """Build a Mattermost interactive dialog for editing the issue."""
    project_alias = data.get("project_alias", "")
    _, project = resolve_project(cfg, project_alias)
    project_labels = get_project_labels(project)
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
            "help_text": f"Available: {','.join(project_labels)}",
        },
    ]

    # Project dropdown (multi-project only)
    if len(cfg["projects"]) > 1:
        project_opts = [
            {"text": p["name"], "value": alias}
            for alias, p in cfg["projects"].items()
        ]
        elements.append({
            "display_name": "Project",
            "name": "project_alias",
            "type": "select",
            "options": project_opts,
            "default": project_alias or cfg["default_project"],
            "optional": False,
        })

    # Assignee dropdown
    if members:
        member_opts = [{"text": "(unassigned)", "value": ""}]
        member_opts += [{"text": f"{m['name']} (@{m['username']})", "value": str(m["id"])} for m in members]
        elements.append({
            "display_name": "Assignee",
            "name": "assignee_id",
            "type": "select",
            "options": member_opts,
            "default": str(data.get("assignee_id", "")),
            "optional": True,
        })

    # Milestone
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

    # Iteration
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
        "url": f"{cfg['bot_url']}/actions/dialog",
        "dialog": {
            "callback_id": issue_id,
            "title": "Edit Issue Before Creating",
            "submit_label": "Approve & Create",
            "elements": elements,
        }
    }


def build_help_response(cfg: dict) -> dict:
    """Build an ephemeral help message."""
    projects = cfg["projects"]
    project_list = "\n".join(
        f"  - `{alias}` — {p['name']}"
        for alias, p in projects.items()
    )
    all_labels = get_all_labels(cfg)
    label_str = ", ".join(f"`{l}`" for l in all_labels[:20])
    if len(all_labels) > 20:
        label_str += f" ... +{len(all_labels) - 20} more"

    provider = cfg["llm_provider"]
    defaults = PROVIDER_DEFAULTS.get(provider.lower(), {})
    model = cfg["llm_model"] or defaults.get("model", "unknown")

    default_alias = cfg["default_project"]

    text = (
        "### Issue Bot — Help\n\n"
        "**Commands:**\n"
        "| Command | Description |\n"
        "|---|---|\n"
        "| `/issue <points> <prompt>` | Create an issue (default project) |\n"
        "| `/issue <project> <points> <prompt>` | Create in a specific project |\n"
        "| `/issue bug\\|feature\\|chore <points> <prompt>` | Create with a template |\n"
        "| `/issue help` | Show this help |\n"
        "| `/issue list [project]` | List recent open issues |\n"
        "| `/issue search <query>` | Search issues by text |\n"
        "| `/issue epic <points> <prompt>` | Create a parent + child issues |\n"
        "| `/issue plan <goals>` | Generate a batch of planned issues |\n\n"
        f"**LLM:** `{provider}` / `{model}`\n\n"
        f"**Projects** (default: `{default_alias}`):\n{project_list}\n\n"
        f"**Labels:** {label_str}"
    )

    return {
        "response_type": "ephemeral",
        "text": text,
    }


def build_issue_list_response(issues: list[dict], project_alias: str = "", query: str = "") -> dict:
    """Build an ephemeral message listing issues."""
    if not issues:
        msg = "No issues found."
        if query:
            msg = f"No issues found matching \"{query}\"."
        return {"response_type": "ephemeral", "text": msg}

    header = "### Recent Issues"
    if query:
        header = f"### Search Results: \"{query}\""
    if project_alias:
        header += f" ({project_alias})"

    lines = []
    for issue in issues:
        state_icon = "🟢" if issue.get("state") == "opened" else "🔴"
        iid = issue.get("iid", "?")
        title = issue.get("title", "Untitled")
        url = issue.get("web_url", "")
        labels = issue.get("labels", [])
        label_str = " ".join(f"`{l}`" for l in labels[:3]) if labels else ""
        lines.append(f"- {state_icon} **[#{iid} {title}]({url})** {label_str}")

    return {
        "response_type": "ephemeral",
        "text": header + "\n\n" + "\n".join(lines),
    }


async def post_to_mattermost_channel(
    http_client: httpx.AsyncClient,
    cfg: dict,
    channel_id: str,
    message: str,
):
    """Post a message to a Mattermost channel using the bot token."""
    bot_token = cfg.get("mm_bot_token", "")
    if not bot_token:
        log.warning("MM_BOT_TOKEN not set, cannot post to channel")
        return
    try:
        resp = await http_client.post(
            f"{cfg['mm_site_url']}/api/v4/posts",
            headers={"Authorization": f"Bearer {bot_token}"},
            json={"channel_id": channel_id, "message": message},
        )
        resp.raise_for_status()
    except Exception as e:
        log.error(f"Failed to post to Mattermost channel: {e}")
