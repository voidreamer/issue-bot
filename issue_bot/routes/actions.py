"""Button action + dialog submission handlers."""

import logging
import asyncio

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from fastapi import Request

from issue_bot import deps
from issue_bot.core.config import resolve_project
from issue_bot.core.templates import get_template
from issue_bot.backends.gitlab import (
    create_gitlab_issue, get_gitlab_iterations, get_gitlab_milestones,
    get_gitlab_project_members, fetch_project_context,
)
from issue_bot.backends.github import create_github_issue
from issue_bot.backends.llm import call_llm
from issue_bot.messaging.mattermost import (
    build_preview_message, build_edit_dialog, build_issue_footer, format_labels,
)

log = logging.getLogger("issue-bot")

router = APIRouter()


async def _create_issue(data: dict, user: str) -> dict:
    """Create an issue on the appropriate backend (GitLab or GitHub)."""
    project_id = data.get("project_id", "")
    project_alias = data.get("project_alias", "")
    project_cfg = deps.CFG["projects"].get(project_alias, {})
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
            deps.http_client, deps.CFG, repo=project_id,
            title=data["title"], description=description,
            labels=data.get("labels", []), weight=data.get("points", 1), **extra,
        )
    else:
        return await create_gitlab_issue(
            deps.http_client, deps.CFG, project_id=project_id,
            title=data["title"], description=description,
            labels=data.get("labels", []), weight=data.get("points", 1), **extra,
        )


def _issue_created_msg(data: dict, issue: dict, user: str) -> str:
    label_str = format_labels(data.get("labels", []))
    project_alias = data.get("project_alias", "")
    project_tag = ""
    if project_alias and project_alias != "default":
        project_name = deps.CFG["projects"].get(project_alias, {}).get("name", project_alias)
        project_tag = f" | Project: **{project_name}**"
    return (
        f"### Issue #{issue['iid']} created\n"
        f"**[{data['title']}]({issue['web_url']})**\n"
        f"Points: **{data.get('points', 1)}** | Labels: {label_str}{project_tag}\n"
        f"_by @{data.get('user', user)}_"
    )


@router.post("/actions/button")
async def handle_button(request: Request):
    payload = await request.json()
    context  = payload.get("context", {})
    action   = context.get("action")
    issue_id = context.get("issue_id")
    user     = payload.get("user_name", "unknown")
    trigger_id = payload.get("trigger_id", "")

    data = deps.store.get_pending(issue_id) if issue_id else None
    if not data:
        return JSONResponse({"update": {"message": "This issue preview has expired. Run `/issue` again.", "props": {}}})

    # --- APPROVE (single issue) ---
    if action == "approve":
        try:
            issue = await _create_issue(data, user)
            deps.store.record_created_issue(
                gitlab_iid=issue["iid"], project_alias=data.get("project_alias", ""),
                title=data["title"], created_by=data.get("user", user),
                gitlab_url=issue["web_url"], data=data,
            )
            deps.store.delete_pending(issue_id)
            return JSONResponse({"update": {"message": _issue_created_msg(data, issue, user), "props": {}}})
        except Exception as e:
            log.exception("Failed to create issue")
            return JSONResponse({"update": {"message": f"Failed to create issue: {e}", "props": {}}})

    # --- APPROVE EPIC ---
    elif action == "approve_epic":
        try:
            project_id = data.get("project_id", "")
            project_alias = data.get("project_alias", "")

            # Create parent
            parent = data["parent"]
            parent_data = {**parent, "points": data.get("points", 1), "user": data.get("user", user),
                           "project_alias": project_alias, "project_id": project_id}
            if data.get("assignee_id"):
                parent_data["assignee_id"] = data["assignee_id"]
            parent_issue = await _create_issue(parent_data, user)
            parent_iid = parent_issue["iid"]
            created_urls = [f"- **[{parent['title']}]({parent_issue['web_url']})** (parent)"]

            deps.store.record_created_issue(
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
                if data.get("assignee_id"):
                    child_data["assignee_id"] = data["assignee_id"]
                child_issue = await _create_issue(child_data, user)
                created_urls.append(f"- **[{child['title']}]({child_issue['web_url']})** ({child.get('points', 1)} pts)")
                deps.store.record_created_issue(
                    gitlab_iid=child_issue["iid"], project_alias=project_alias,
                    title=child["title"], created_by=data.get("user", user),
                    gitlab_url=child_issue["web_url"], data=child,
                )

            deps.store.delete_pending(issue_id)
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
                if data.get("assignee_id"):
                    item_data["assignee_id"] = data["assignee_id"]
                created = await _create_issue(item_data, user)
                created_urls.append(f"- **[{issue_item['title']}]({created['web_url']})** ({issue_item.get('points', 1)} pts)")
                deps.store.record_created_issue(
                    gitlab_iid=created["iid"], project_alias=project_alias,
                    title=issue_item["title"], created_by=data.get("user", user),
                    gitlab_url=created["web_url"], data=issue_item,
                )
            deps.store.delete_pending(issue_id)
            msg = f"### Sprint plan created ({len(created_urls)} issues)\n\n" + "\n".join(created_urls)
            return JSONResponse({"update": {"message": msg, "props": {}}})
        except Exception as e:
            log.exception("Failed to create plan")
            return JSONResponse({"update": {"message": f"Failed to create plan: {e}", "props": {}}})

    # --- REGENERATE ---
    elif action == "regenerate":
        try:
            template = get_template(data.get("template", ""))
            project = deps.CFG["projects"].get(data.get("project_alias", ""), {})
            project_id = data.get("project_id", "")
            project_context = ""
            if deps.CFG.get("inject_project_context", True) and project_id:
                project_context = await fetch_project_context(deps.http_client, deps.CFG, project_id)
            new_data = await call_llm(
                deps.http_client, deps.CFG, data["original_prompt"], data.get("points", 1),
                labels=project.get("labels", ""), template_extra=template["system_prompt_extra"],
                context=project_context,
            )
            # Preserve metadata
            for key in ("points", "user", "project_alias", "project_id", "original_prompt",
                        "template", "type", "assignee_id", "assignee_username", "assignee_warning"):
                if key in data:
                    new_data[key] = data[key]
            deps.store.update_pending(issue_id, new_data)
            return JSONResponse({"update": build_preview_message(deps.CFG, issue_id, new_data)})
        except Exception as e:
            log.exception("Regeneration failed")
            return JSONResponse({"update": {"message": f"Regeneration failed: {e}", "props": {}}})

    # --- EDIT ---
    elif action == "edit":
        project_id = data.get("project_id", "")
        iterations, milestones, members = await asyncio.gather(
            get_gitlab_iterations(deps.http_client, deps.CFG, project_id),
            get_gitlab_milestones(deps.http_client, deps.CFG, project_id),
            get_gitlab_project_members(deps.http_client, deps.CFG, project_id),
        )
        dialog_req = build_edit_dialog(deps.CFG, issue_id, data, iterations, milestones, members)
        dialog_req["trigger_id"] = trigger_id
        try:
            mm_resp = await deps.http_client.post(
                f"{deps.CFG['mm_site_url']}/api/v4/actions/dialogs/open", json=dialog_req)
            mm_resp.raise_for_status()
        except Exception as e:
            log.exception("Failed to open dialog")
            return JSONResponse({"update": {"message": f"Could not open edit dialog: {e}", "props": {}}})
        return JSONResponse({})

    # --- CANCEL ---
    elif action == "cancel":
        deps.store.delete_pending(issue_id)
        return JSONResponse({"update": {"message": "Issue creation cancelled.", "props": {}}})

    return JSONResponse({"update": {"message": "Unknown action.", "props": {}}})


@router.post("/actions/dialog")
async def handle_dialog(request: Request):
    payload  = await request.json()
    issue_id = payload.get("callback_id", "")
    submission = payload.get("submission", {})
    user     = payload.get("user", {}).get("username", "unknown")

    data = deps.store.get_pending(issue_id)
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
        if new_alias in deps.CFG["projects"]:
            data["project_alias"] = new_alias
            data["project_id"] = deps.CFG["projects"][new_alias]["id"]

    try:
        issue = await _create_issue(data, user)
        deps.store.record_created_issue(
            gitlab_iid=issue["iid"], project_alias=data.get("project_alias", ""),
            title=data["title"], created_by=data.get("user", user),
            gitlab_url=issue["web_url"], data=data,
        )
        deps.store.delete_pending(issue_id)
        log.info(f"Issue #{issue['iid']} created: {data['title']}")
        return JSONResponse({})
    except Exception as e:
        log.exception("Failed to create issue from dialog")
        return JSONResponse({"errors": {"title": f"GitLab error: {e}"}})
