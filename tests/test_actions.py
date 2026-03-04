"""Tests for issue_bot.routes.actions — button + dialog handlers."""

import json
from unittest.mock import AsyncMock, MagicMock

from issue_bot import deps
from tests.conftest import make_test_config


def _save_issue(store, issue_id="test123", **overrides):
    data = {"title": "Test Issue", "description": "Desc", "labels": ["bug"],
            "points": 3, "user": "alice", "project_alias": "default",
            "project_id": "42", "original_prompt": "Build something", "template": "", "type": "single"}
    data.update(overrides)
    store.save_pending(issue_id, data, user_id="alice", channel_id="ch1")
    return data


def test_button_expired_issue(app_client):
    resp = app_client.post("/actions/button", json={
        "context": {"action": "approve", "issue_id": "nonexistent"},
        "user_name": "alice",
    })
    body = resp.json()
    assert "expired" in body["update"]["message"]


def test_button_cancel(app_client):
    _save_issue(deps.store)
    resp = app_client.post("/actions/button", json={
        "context": {"action": "cancel", "issue_id": "test123"},
        "user_name": "alice",
    })
    body = resp.json()
    assert "cancelled" in body["update"]["message"]
    assert deps.store.get_pending("test123") is None


def test_button_approve_creates_issue(app_client):
    _save_issue(deps.store)
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"iid": 99, "web_url": "http://example.com/99", "title": "Test"}
    mock_resp.raise_for_status = MagicMock()
    deps.http_client.post = AsyncMock(return_value=mock_resp)

    resp = app_client.post("/actions/button", json={
        "context": {"action": "approve", "issue_id": "test123"},
        "user_name": "alice",
    })
    body = resp.json()
    assert "#99" in body["update"]["message"]
    assert deps.store.get_pending("test123") is None


def test_button_approve_epic(app_client):
    deps.store.save_pending("epic1", {
        "parent": {"title": "Epic Parent", "description": "Parent desc", "labels": ["infra"]},
        "children": [{"title": "Child 1", "description": "Desc", "labels": ["bug"], "points": 2}],
        "points": 5, "user": "alice", "project_alias": "default", "project_id": "42", "type": "epic",
    }, user_id="alice", channel_id="ch1")

    issue_counter = {"n": 100}
    def mock_post(*args, **kwargs):
        resp = MagicMock()
        issue_counter["n"] += 1
        resp.json.return_value = {"iid": issue_counter["n"], "web_url": f"http://x/{issue_counter['n']}"}
        resp.raise_for_status = MagicMock()
        return resp
    deps.http_client.post = AsyncMock(side_effect=mock_post)

    resp = app_client.post("/actions/button", json={
        "context": {"action": "approve_epic", "issue_id": "epic1"},
        "user_name": "alice",
    })
    body = resp.json()
    assert "Epic created" in body["update"]["message"]


def test_button_approve_plan(app_client):
    deps.store.save_pending("plan1", {
        "issues": [
            {"title": "Issue 1", "description": "D1", "labels": ["bug"], "points": 2},
            {"title": "Issue 2", "description": "D2", "labels": [], "points": 3},
        ],
        "user": "alice", "project_alias": "default", "project_id": "42", "type": "plan",
    }, user_id="alice", channel_id="ch1")

    issue_counter = {"n": 200}
    def mock_post(*args, **kwargs):
        resp = MagicMock()
        issue_counter["n"] += 1
        resp.json.return_value = {"iid": issue_counter["n"], "web_url": f"http://x/{issue_counter['n']}"}
        resp.raise_for_status = MagicMock()
        return resp
    deps.http_client.post = AsyncMock(side_effect=mock_post)

    resp = app_client.post("/actions/button", json={
        "context": {"action": "approve_plan", "issue_id": "plan1"},
        "user_name": "alice",
    })
    body = resp.json()
    assert "Sprint plan created" in body["update"]["message"]


def test_button_regenerate(app_client):
    _save_issue(deps.store)
    llm_response = {"title": "Regenerated", "description": "New desc", "labels": ["enhancement"]}
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"choices": [{"message": {"content": json.dumps(llm_response)}}]}
    mock_resp.raise_for_status = MagicMock()
    deps.http_client.post = AsyncMock(return_value=mock_resp)

    resp = app_client.post("/actions/button", json={
        "context": {"action": "regenerate", "issue_id": "test123"},
        "user_name": "alice",
    })
    body = resp.json()
    assert "Regenerated" in body["update"]["text"]


def test_button_unknown_action(app_client):
    _save_issue(deps.store)
    resp = app_client.post("/actions/button", json={
        "context": {"action": "unknown", "issue_id": "test123"},
        "user_name": "alice",
    })
    body = resp.json()
    assert "Unknown action" in body["update"]["message"]


def test_dialog_expired(app_client):
    resp = app_client.post("/actions/dialog", json={
        "callback_id": "gone", "submission": {}, "user": {"username": "alice"},
    })
    body = resp.json()
    assert "expired" in body["errors"]["title"]


def test_dialog_creates_issue(app_client):
    _save_issue(deps.store)
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"iid": 50, "web_url": "http://x/50", "title": "Test"}
    mock_resp.raise_for_status = MagicMock()
    deps.http_client.post = AsyncMock(return_value=mock_resp)

    resp = app_client.post("/actions/dialog", json={
        "callback_id": "test123",
        "submission": {"title": "Edited Title", "points": "5", "labels": "bug,enhancement"},
        "user": {"username": "alice"},
    })
    assert resp.status_code == 200
    assert deps.store.get_pending("test123") is None
