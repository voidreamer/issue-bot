"""Tests for issue_bot.routes.slash — /slash/issue handler."""

import json
from unittest.mock import AsyncMock, MagicMock

from issue_bot import deps


def _form(text="", token="test-slash-token", user="testuser", channel="ch1"):
    return {"token": token, "text": text, "user_name": user, "channel_id": channel}


def test_invalid_token(app_client):
    resp = app_client.post("/slash/issue", data=_form(token="bad"))
    assert resp.status_code == 403


def test_empty_text_returns_help(app_client):
    resp = app_client.post("/slash/issue", data=_form(text=""))
    assert resp.status_code == 200
    body = resp.json()
    assert "Help" in body["text"]


def test_help_command(app_client):
    resp = app_client.post("/slash/issue", data=_form(text="help"))
    body = resp.json()
    assert body["response_type"] == "ephemeral"
    assert "/issue" in body["text"]


def test_list_command(app_client):
    mock_resp = MagicMock()
    mock_resp.json.return_value = [
        {"iid": 1, "title": "Test", "web_url": "http://x", "state": "opened", "labels": []}
    ]
    mock_resp.raise_for_status = MagicMock()
    deps.http_client.get = AsyncMock(return_value=mock_resp)

    resp = app_client.post("/slash/issue", data=_form(text="list"))
    body = resp.json()
    assert body["response_type"] == "ephemeral"
    assert "Test" in body["text"]


def test_search_no_query(app_client):
    resp = app_client.post("/slash/issue", data=_form(text="search"))
    body = resp.json()
    assert "Usage" in body["text"]


def test_create_no_prompt_returns_usage(app_client):
    resp = app_client.post("/slash/issue", data=_form(text="3"))
    body = resp.json()
    assert "Usage" in body["text"]


def test_create_calls_llm_and_stores(app_client):
    llm_response = {"title": "Test Issue", "description": "Desc", "labels": ["bug"]}
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": json.dumps(llm_response)}}]
    }
    mock_resp.raise_for_status = MagicMock()
    deps.http_client.post = AsyncMock(return_value=mock_resp)

    resp = app_client.post("/slash/issue", data=_form(text="3 Build login page"))
    body = resp.json()
    assert body["response_type"] == "in_channel"
    assert "Test Issue" in body["text"]


def test_create_unknown_project(app_client):
    # "nonexistent" is not a known alias, so it becomes part of the prompt
    # which triggers the LLM call — mock it to avoid errors
    llm_response = {"title": "Built It", "description": "Desc", "labels": []}
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "choices": [{"message": {"content": json.dumps(llm_response)}}]
    }
    mock_resp.raise_for_status = MagicMock()
    deps.http_client.post = AsyncMock(return_value=mock_resp)

    resp = app_client.post("/slash/issue", data=_form(text="nonexistent 3 Build it"))
    assert resp.status_code == 200
