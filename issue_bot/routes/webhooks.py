"""GitLab webhook notifications."""

import logging

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse

from issue_bot import deps
from issue_bot.messaging.mattermost import post_to_mattermost_channel

log = logging.getLogger("issue-bot")

router = APIRouter()


@router.post("/webhooks/gitlab")
async def handle_gitlab_webhook(request: Request):
    secret = deps.CFG.get("webhook_secret", "")
    if secret:
        token = request.headers.get("X-Gitlab-Token", "")
        if token != secret:
            raise HTTPException(status_code=403, detail="Invalid webhook token")

    payload = await request.json()
    object_kind = payload.get("object_kind", "")

    if object_kind == "issue":
        attrs = payload.get("object_attributes", {})
        action = attrs.get("action", "")
        title = attrs.get("title", "")
        url = attrs.get("url", "")
        iid = attrs.get("iid", "")
        user_info = payload.get("user", {})
        username = user_info.get("username", "unknown")

        channel_id = deps.CFG.get("mm_notify_channel_id", "")
        if channel_id and action in ("open", "close", "reopen"):
            icon = {"open": "\U0001f7e2", "close": "\U0001f534", "reopen": "\U0001f535"}.get(action, "\u2139\ufe0f")
            msg = f"{icon} Issue **[#{iid} {title}]({url})** {action}ed by @{username}"
            await post_to_mattermost_channel(deps.http_client, deps.CFG, channel_id, msg)

    return JSONResponse({"status": "ok"})
