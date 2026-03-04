"""Tests for issue_bot.routes.webhooks — /webhooks/gitlab handler."""

from unittest.mock import AsyncMock, MagicMock

from issue_bot import deps


def test_webhook_invalid_secret(app_client):
    deps.CFG["webhook_secret"] = "secret123"
    resp = app_client.post("/webhooks/gitlab", json={}, headers={"X-Gitlab-Token": "wrong"})
    assert resp.status_code == 403


def test_webhook_no_secret_required(app_client):
    deps.CFG["webhook_secret"] = ""
    resp = app_client.post("/webhooks/gitlab", json={"object_kind": "note"})
    assert resp.status_code == 200


def test_webhook_issue_open_posts_notification(app_client):
    deps.CFG["mm_notify_channel_id"] = "notify-ch"
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    deps.http_client.post = AsyncMock(return_value=mock_resp)

    resp = app_client.post("/webhooks/gitlab", json={
        "object_kind": "issue",
        "object_attributes": {
            "action": "open", "title": "New Bug", "url": "http://x/1", "iid": 1, "state": "opened",
        },
        "user": {"username": "dev"},
    })
    assert resp.status_code == 200
    deps.http_client.post.assert_called_once()
    call_json = deps.http_client.post.call_args[1]["json"]
    assert "New Bug" in call_json["message"]


def test_webhook_issue_non_notifiable_action(app_client):
    deps.CFG["mm_notify_channel_id"] = "notify-ch"
    resp = app_client.post("/webhooks/gitlab", json={
        "object_kind": "issue",
        "object_attributes": {"action": "update", "title": "X", "url": "u", "iid": 1, "state": "opened"},
        "user": {"username": "dev"},
    })
    assert resp.status_code == 200
    deps.http_client.post.assert_not_called()
