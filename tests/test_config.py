"""Tests for issue_bot.core.config."""

import pytest

from issue_bot.core.config import load_config, resolve_project, get_project_labels, get_all_labels


REQUIRED_ENV = {
    "GITLAB_TOKEN": "tok",
    "MM_SLASH_TOKEN": "slash-tok",
    "GITLAB_PROJECT_ID": "99",
}


def test_load_config_legacy_mode(monkeypatch):
    for k, v in REQUIRED_ENV.items():
        monkeypatch.setenv(k, v)
    cfg = load_config()
    assert "default" in cfg["projects"]
    assert cfg["projects"]["default"]["id"] == "99"
    assert cfg["default_project"] == "default"


def test_load_config_multi_mode(monkeypatch):
    import json
    monkeypatch.setenv("GITLAB_TOKEN", "tok")
    monkeypatch.setenv("MM_SLASH_TOKEN", "slash-tok")
    projects = {"web": {"id": "1", "name": "Web"}, "api": {"id": "2", "name": "API"}}
    monkeypatch.setenv("GITLAB_PROJECTS", json.dumps(projects))
    monkeypatch.setenv("GITLAB_DEFAULT_PROJECT", "api")
    cfg = load_config()
    assert "web" in cfg["projects"]
    assert "api" in cfg["projects"]
    assert cfg["default_project"] == "api"


def test_load_config_missing_project_id(monkeypatch):
    monkeypatch.setenv("GITLAB_TOKEN", "tok")
    monkeypatch.setenv("MM_SLASH_TOKEN", "slash-tok")
    monkeypatch.delenv("GITLAB_PROJECT_ID", raising=False)
    monkeypatch.delenv("GITLAB_PROJECTS", raising=False)
    with pytest.raises(ValueError, match="Set either"):
        load_config()


def test_load_config_invalid_projects_json(monkeypatch):
    monkeypatch.setenv("GITLAB_TOKEN", "tok")
    monkeypatch.setenv("MM_SLASH_TOKEN", "slash-tok")
    monkeypatch.setenv("GITLAB_PROJECTS", "not-json")
    with pytest.raises(ValueError, match="not valid JSON"):
        load_config()


def test_resolve_project_default():
    cfg = {
        "default_project": "main",
        "projects": {"main": {"id": "1", "name": "Main"}},
    }
    alias, proj = resolve_project(cfg, "")
    assert alias == "main"
    assert proj["id"] == "1"


def test_resolve_project_explicit():
    cfg = {
        "default_project": "main",
        "projects": {"main": {"id": "1"}, "other": {"id": "2"}},
    }
    alias, proj = resolve_project(cfg, "other")
    assert alias == "other"
    assert proj["id"] == "2"


def test_resolve_project_unknown():
    cfg = {"default_project": "main", "projects": {"main": {"id": "1"}}}
    with pytest.raises(KeyError, match="Unknown project"):
        resolve_project(cfg, "nope")


def test_get_project_labels():
    assert get_project_labels({"labels": "a, b, c"}) == ["a", "b", "c"]
    assert get_project_labels({"labels": ""}) == []
    assert get_project_labels({}) == []


def test_get_all_labels_deduplicates():
    cfg = {
        "projects": {
            "a": {"labels": "bug,enhancement"},
            "b": {"labels": "enhancement,infra"},
        }
    }
    labels = get_all_labels(cfg)
    assert labels == ["bug", "enhancement", "infra"]
