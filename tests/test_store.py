"""Tests for issue_bot.core.store."""

import time

from issue_bot.core.store import Store


def test_save_and_get_pending(store):
    store.save_pending("abc", {"title": "Test"}, user_id="alice", channel_id="ch1")
    data = store.get_pending("abc")
    assert data["title"] == "Test"


def test_get_pending_missing(store):
    assert store.get_pending("nonexistent") is None


def test_update_pending(store):
    store.save_pending("abc", {"title": "Old"})
    store.update_pending("abc", {"title": "New"})
    assert store.get_pending("abc")["title"] == "New"


def test_delete_pending(store):
    store.save_pending("abc", {"title": "Test"})
    store.delete_pending("abc")
    assert store.get_pending("abc") is None


def test_expired_pending_not_returned(store):
    store.save_pending("abc", {"title": "Test"}, expiry_seconds=-1)
    assert store.get_pending("abc") is None


def test_cleanup_expired(store):
    store.save_pending("old", {"title": "Old"}, expiry_seconds=-1)
    store.save_pending("new", {"title": "New"}, expiry_seconds=3600)
    removed = store.cleanup_expired()
    assert removed == 1
    assert store.get_pending("old") is None
    assert store.get_pending("new") is not None


def test_record_and_get_recent_issues(store):
    store.record_created_issue(gitlab_iid=1, project_alias="p", title="Issue 1",
                               created_by="alice", gitlab_url="http://example.com/1")
    store.record_created_issue(gitlab_iid=2, project_alias="p", title="Issue 2",
                               created_by="bob", gitlab_url="http://example.com/2")
    issues = store.get_recent_issues()
    assert len(issues) == 2
    assert issues[0]["title"] == "Issue 2"  # most recent first


def test_get_recent_issues_by_project(store):
    store.record_created_issue(gitlab_iid=1, project_alias="a", title="A",
                               created_by="x", gitlab_url="u")
    store.record_created_issue(gitlab_iid=2, project_alias="b", title="B",
                               created_by="x", gitlab_url="u")
    issues = store.get_recent_issues(project_alias="a")
    assert len(issues) == 1
    assert issues[0]["project_alias"] == "a"


def test_save_pending_with_metadata(store):
    store.save_pending("abc", {"title": "Test"}, user_id="alice",
                       channel_id="ch1", project_alias="proj")
    data = store.get_pending("abc")
    assert data is not None
