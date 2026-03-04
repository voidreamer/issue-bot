"""Tests for issue_bot.core.templates."""

from issue_bot.core.templates import get_template, get_template_names


def test_get_default_template():
    t = get_template("")
    assert t["system_prompt_extra"] == ""
    assert t["default_labels"] == []


def test_get_bug_template():
    t = get_template("bug")
    assert "Bug Report" in t["system_prompt_extra"]
    assert "bug" in t["default_labels"]


def test_get_feature_template():
    t = get_template("feature")
    assert "Feature Request" in t["system_prompt_extra"]
    assert "enhancement" in t["default_labels"]


def test_get_unknown_falls_back_to_default():
    t = get_template("nonexistent")
    assert t == get_template("")


def test_get_template_names():
    names = get_template_names()
    assert "bug" in names
    assert "feature" in names
    assert "chore" in names
    assert "default" not in names
