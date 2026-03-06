"""Slash command handler — /slash/issue."""

import logging
import uuid

import httpx
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse

from issue_bot import deps
from issue_bot.core.config import resolve_project
from issue_bot.core.parser import parse_issue_command
from issue_bot.core.templates import get_template, get_template_names
from issue_bot.backends.llm import call_llm, call_llm_epic, call_llm_plan
from issue_bot.backends.gitlab import (
    search_gitlab_issues, fetch_project_context, get_gitlab_project_members,
)
from issue_bot.backends.github import search_github_issues
from issue_bot.messaging.mattermost import (
    build_preview_message, build_epic_preview_message, build_plan_preview_message,
    build_help_response, build_issue_list_response,
)

log = logging.getLogger("issue-bot")

router = APIRouter()


async def _resolve_assignee(project_id: str, usernames: list[str]) -> tuple[int | None, str | None]:
    """Resolve the first @username to a GitLab user ID. Returns (id, username) or (None, None)."""
    if not usernames:
        return None, None
    members = await get_gitlab_project_members(deps.http_client, deps.CFG, project_id)
    target = usernames[0].lower()
    for m in members:
        if m["username"].lower() == target:
            return m["id"], m["username"]
    return None, None


async def _get_project_context(project_id: str) -> str:
    """Fetch project context if enabled in config."""
    if not deps.CFG.get("inject_project_context", True):
        return ""
    return await fetch_project_context(deps.http_client, deps.CFG, project_id)


@router.post("/slash/issue")
async def handle_slash_issue(request: Request):
    form = await request.form()
    token = form.get("token", "")
    text  = form.get("text", "").strip()
    user  = form.get("user_name", "unknown")
    channel_id = form.get("channel_id", "")

    if token != deps.CFG["mm_slash_token"]:
        raise HTTPException(status_code=403, detail="Invalid token")

    cmd = parse_issue_command(
        text,
        project_aliases=set(deps.CFG["projects"].keys()),
        template_names=get_template_names(),
    )

    # --- help ---
    if cmd.action == "help":
        return JSONResponse(build_help_response(deps.CFG))

    # --- list ---
    if cmd.action == "list":
        try:
            alias, project = resolve_project(deps.CFG, cmd.project)
        except KeyError as e:
            return JSONResponse({"response_type": "ephemeral", "text": str(e)})
        backend = project.get("backend", "gitlab")
        if backend == "github":
            issues = await search_github_issues(deps.http_client, deps.CFG, repo=project["id"])
        else:
            issues = await search_gitlab_issues(deps.http_client, deps.CFG, project_id=project["id"])
        return JSONResponse(build_issue_list_response(issues, project_alias=alias))

    # --- search ---
    if cmd.action == "search":
        if not cmd.search_query:
            return JSONResponse({"response_type": "ephemeral", "text": "Usage: `/issue search <query>`"})
        _, project = resolve_project(deps.CFG, "")
        backend = project.get("backend", "gitlab")
        if backend == "github":
            issues = await search_github_issues(deps.http_client, deps.CFG, repo=project["id"], query=cmd.search_query)
        else:
            issues = await search_gitlab_issues(deps.http_client, deps.CFG, project_id=project["id"], query=cmd.search_query)
        return JSONResponse(build_issue_list_response(issues, query=cmd.search_query))

    # --- epic ---
    if cmd.action == "epic":
        if not cmd.prompt:
            return JSONResponse({"response_type": "ephemeral", "text": "Usage: `/issue epic <points> <goal>`"})
        try:
            alias, project = resolve_project(deps.CFG, cmd.project)
        except KeyError as e:
            return JSONResponse({"response_type": "ephemeral", "text": str(e)})
        try:
            project_context = await _get_project_context(project["id"])
            epic_data = await call_llm_epic(
                deps.http_client, deps.CFG, cmd.prompt, cmd.points,
                labels=project.get("labels", ""), context=project_context,
            )
            epic_data["user"] = user
            epic_data["project_alias"] = alias
            epic_data["project_id"] = project["id"]
            epic_data["original_prompt"] = cmd.prompt
            epic_data["points"] = cmd.points
            epic_data["type"] = "epic"
            assignee_id, assignee_username = await _resolve_assignee(project["id"], cmd.assignees)
            if assignee_id:
                epic_data["assignee_id"] = assignee_id
                epic_data["assignee_username"] = assignee_username
            elif cmd.assignees:
                epic_data["assignee_warning"] = f"Could not find @{cmd.assignees[0]} in project members"
            issue_id = uuid.uuid4().hex[:12]
            deps.store.save_pending(issue_id, epic_data, user_id=user, channel_id=channel_id, project_alias=alias)
            return JSONResponse(build_epic_preview_message(deps.CFG, issue_id, epic_data))
        except Exception as e:
            log.exception("Epic generation failed")
            return JSONResponse({"response_type": "ephemeral", "text": f"Epic generation failed: {e}"})

    # --- plan ---
    if cmd.action == "plan":
        if not cmd.prompt:
            return JSONResponse({"response_type": "ephemeral", "text": "Usage: `/issue plan <goals>`"})
        try:
            alias, project = resolve_project(deps.CFG, cmd.project)
        except KeyError as e:
            return JSONResponse({"response_type": "ephemeral", "text": str(e)})
        try:
            project_context = await _get_project_context(project["id"])
            plan_data = await call_llm_plan(
                deps.http_client, deps.CFG, cmd.prompt,
                labels=project.get("labels", ""), context=project_context,
            )
            plan_data["user"] = user
            plan_data["project_alias"] = alias
            plan_data["project_id"] = project["id"]
            plan_data["original_prompt"] = cmd.prompt
            plan_data["type"] = "plan"
            assignee_id, assignee_username = await _resolve_assignee(project["id"], cmd.assignees)
            if assignee_id:
                plan_data["assignee_id"] = assignee_id
                plan_data["assignee_username"] = assignee_username
            elif cmd.assignees:
                plan_data["assignee_warning"] = f"Could not find @{cmd.assignees[0]} in project members"
            issue_id = uuid.uuid4().hex[:12]
            deps.store.save_pending(issue_id, plan_data, user_id=user, channel_id=channel_id, project_alias=alias)
            return JSONResponse(build_plan_preview_message(deps.CFG, issue_id, plan_data))
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
        project_alias, project = resolve_project(deps.CFG, cmd.project)
    except KeyError as e:
        return JSONResponse({"response_type": "ephemeral", "text": str(e)})

    template = get_template(cmd.template)
    project_labels_str = project.get("labels", "")
    log.info(f"[{user}] /issue {project_alias} {cmd.points} {cmd.prompt[:80]}...")

    try:
        project_context = await _get_project_context(project["id"])
        issue_data = await call_llm(
            deps.http_client, deps.CFG, cmd.prompt, cmd.points,
            labels=project_labels_str, template_extra=template["system_prompt_extra"],
            context=project_context,
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
        assignee_id, assignee_username = await _resolve_assignee(project["id"], cmd.assignees)
        if assignee_id:
            issue_data["assignee_id"] = assignee_id
            issue_data["assignee_username"] = assignee_username
        elif cmd.assignees:
            issue_data["assignee_warning"] = f"Could not find @{cmd.assignees[0]} in project members"

        issue_id = uuid.uuid4().hex[:12]
        deps.store.save_pending(issue_id, issue_data, user_id=user, channel_id=channel_id, project_alias=project_alias)
        return JSONResponse(build_preview_message(deps.CFG, issue_id, issue_data))

    except httpx.HTTPStatusError as e:
        log.error(f"HTTP error: {e.response.status_code} - {e.response.text}")
        return JSONResponse({
            "response_type": "ephemeral",
            "text": f"Failed: {e.response.status_code}\n```\n{e.response.text[:300]}\n```",
        })
    except Exception as e:
        log.exception("Unexpected error")
        return JSONResponse({"response_type": "ephemeral", "text": f"Something went wrong: {type(e).__name__}: {e}"})
