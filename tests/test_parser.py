"""Tests for issue_bot.core.parser."""

from issue_bot.core.parser import parse_issue_command, ParsedCommand


ALIASES = {"webapp", "backend", "infra"}
TEMPLATES = {"bug", "feature", "chore"}


def test_empty_input_returns_help():
    cmd = parse_issue_command("")
    assert cmd.action == "help"


def test_help_command():
    cmd = parse_issue_command("help")
    assert cmd.action == "help"


def test_list_command_no_project():
    cmd = parse_issue_command("list", project_aliases=ALIASES)
    assert cmd.action == "list"
    assert cmd.project == ""


def test_list_command_with_project():
    cmd = parse_issue_command("list webapp", project_aliases=ALIASES)
    assert cmd.action == "list"
    assert cmd.project == "webapp"


def test_search_command():
    cmd = parse_issue_command("search login bug", project_aliases=ALIASES)
    assert cmd.action == "search"
    assert cmd.search_query == "login bug"


def test_epic_command_with_points_and_prompt():
    cmd = parse_issue_command("epic 5 Build auth system", project_aliases=ALIASES)
    assert cmd.action == "epic"
    assert cmd.points == 5
    assert cmd.prompt == "Build auth system"


def test_plan_command():
    cmd = parse_issue_command("plan Add login and signup", project_aliases=ALIASES)
    assert cmd.action == "plan"
    assert cmd.prompt == "Add login and signup"


def test_create_with_points_and_prompt():
    cmd = parse_issue_command("3 Build login page with OAuth")
    assert cmd.action == "create"
    assert cmd.points == 3
    assert cmd.prompt == "Build login page with OAuth"


def test_create_with_project_and_points():
    cmd = parse_issue_command("webapp 5 Build login page", project_aliases=ALIASES)
    assert cmd.action == "create"
    assert cmd.project == "webapp"
    assert cmd.points == 5
    assert cmd.prompt == "Build login page"


def test_create_with_template():
    cmd = parse_issue_command("bug 3 Fix the crash", template_names=TEMPLATES)
    assert cmd.action == "create"
    assert cmd.template == "bug"
    assert cmd.points == 3
    assert cmd.prompt == "Fix the crash"


def test_create_with_project_template_and_points():
    cmd = parse_issue_command("webapp bug 3 Fix the crash", project_aliases=ALIASES, template_names=TEMPLATES)
    assert cmd.action == "create"
    assert cmd.project == "webapp"
    assert cmd.template == "bug"
    assert cmd.points == 3
    assert cmd.prompt == "Fix the crash"


def test_create_prompt_only():
    cmd = parse_issue_command("Build login page")
    assert cmd.action == "create"
    assert cmd.points == 1
    assert cmd.prompt == "Build login page"


def test_case_insensitive_alias():
    cmd = parse_issue_command("WebApp 3 Something", project_aliases=ALIASES)
    assert cmd.project == "webapp"


def test_case_insensitive_template():
    cmd = parse_issue_command("BUG 3 Fix it", template_names=TEMPLATES)
    assert cmd.template == "bug"


def test_raw_text_preserved():
    cmd = parse_issue_command("  webapp 3 Build login  ")
    assert cmd.raw_text == "webapp 3 Build login"
