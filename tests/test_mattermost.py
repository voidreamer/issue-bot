"""Tests for issue_bot.messaging.mattermost."""

from issue_bot.messaging.mattermost import (
    format_labels, build_issue_footer, build_preview_message,
    build_epic_preview_message, build_plan_preview_message,
    build_help_response, build_issue_list_response, build_edit_dialog,
)

from tests.conftest import make_test_config


def test_format_labels_with_items():
    assert format_labels(["bug", "enhancement"]) == "`bug`, `enhancement`"


def test_format_labels_empty():
    assert format_labels([]) == "_none_"


def test_build_issue_footer():
    data = {"user": "alice", "points": 3, "project_alias": "webapp"}
    footer = build_issue_footer(data, "fallback")
    assert "@alice" in footer
    assert "3 pts" in footer
    assert "[webapp]" in footer


def test_build_issue_footer_default_project():
    data = {"user": "alice", "points": 1, "project_alias": "default"}
    footer = build_issue_footer(data, "fallback")
    assert "[default]" not in footer


def test_build_preview_message_structure():
    cfg = make_test_config()
    data = {"title": "Test Issue", "description": "A description", "labels": ["bug"],
            "points": 3, "user": "alice", "project_alias": "default"}
    msg = build_preview_message(cfg, "id123", data)
    assert msg["response_type"] == "in_channel"
    assert "Test Issue" in msg["text"]
    assert len(msg["attachments"][0]["actions"]) == 4


def test_build_preview_message_truncates_long_description():
    cfg = make_test_config()
    data = {"title": "T", "description": "x" * 1000, "labels": [], "points": 1,
            "user": "u", "project_alias": ""}
    msg = build_preview_message(cfg, "id", data)
    assert "truncated" in msg["text"]


def test_build_epic_preview_message():
    cfg = make_test_config()
    data = {"parent": {"title": "Epic", "labels": ["infra"]},
            "children": [{"title": "Child 1", "points": 2, "labels": ["bug"]}],
            "user": "bob", "project_alias": "default"}
    msg = build_epic_preview_message(cfg, "id", data)
    assert "Epic Preview" in msg["text"]
    assert "Child 1" in msg["text"]


def test_build_plan_preview_message():
    cfg = make_test_config()
    data = {"issues": [{"title": "Issue 1", "points": 3, "labels": ["bug"]}],
            "user": "carol", "project_alias": "default"}
    msg = build_plan_preview_message(cfg, "id", data)
    assert "Sprint Plan Preview" in msg["text"]


def test_build_help_response():
    cfg = make_test_config()
    resp = build_help_response(cfg)
    assert resp["response_type"] == "ephemeral"
    assert "/issue" in resp["text"]


def test_build_issue_list_response_with_issues():
    issues = [{"iid": 1, "title": "Test", "web_url": "http://x", "state": "opened", "labels": ["bug"]}]
    resp = build_issue_list_response(issues, project_alias="proj")
    assert "Test" in resp["text"]
    assert "proj" in resp["text"]


def test_build_issue_list_response_empty():
    resp = build_issue_list_response([], query="login")
    assert "No issues found" in resp["text"]
    assert "login" in resp["text"]


def test_build_edit_dialog_basic():
    cfg = make_test_config()
    data = {"title": "T", "description": "D", "points": 2, "labels": ["bug"],
            "project_alias": "default"}
    dialog = build_edit_dialog(cfg, "id123", data, iterations=[], milestones=[], members=None)
    assert dialog["dialog"]["callback_id"] == "id123"
    elements = dialog["dialog"]["elements"]
    names = [e["name"] for e in elements]
    assert "title" in names
    assert "description" in names
