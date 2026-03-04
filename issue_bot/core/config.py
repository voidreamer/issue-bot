"""
Configuration loading with backward-compatible multi-project support.

Two modes:
  - Legacy: GITLAB_PROJECT_ID + PROJECT_LABELS (single project)
  - Multi:  GITLAB_PROJECTS JSON + GITLAB_DEFAULT_PROJECT
"""

import os
import json
import logging

log = logging.getLogger("issue-bot")


def load_config() -> dict:
    """Load and validate all configuration from environment variables.

    Returns a dict with keys:
        gitlab_url, gitlab_token, mm_slash_token, mm_site_url, bot_url,
        llm_provider, llm_api_key, llm_model, llm_base_url,
        projects (dict of alias -> ProjectConfig dicts),
        default_project (alias str),
        db_path, webhook_secret, mm_bot_token, mm_notify_channel_id
    """
    cfg = {
        "gitlab_token": os.environ["GITLAB_TOKEN"],
        "gitlab_url": os.environ.get("GITLAB_URL", "https://gitlab.com"),
        "mm_slash_token": os.environ["MM_SLASH_TOKEN"],
        "mm_site_url": os.environ.get("MM_SITE_URL", "http://localhost:8065"),
        "bot_url": os.environ.get("BOT_URL", "http://localhost:8321"),

        # LLM
        "llm_provider": os.environ.get("LLM_PROVIDER", "openai"),
        "llm_api_key": os.environ.get("LLM_API_KEY", ""),
        "llm_model": os.environ.get("LLM_MODEL", ""),
        "llm_base_url": os.environ.get("LLM_BASE_URL", ""),

        # Phase 2
        "db_path": os.environ.get("BOT_DB_PATH", "data/issuebot.db"),
        "webhook_secret": os.environ.get("GITLAB_WEBHOOK_SECRET", ""),
        "mm_bot_token": os.environ.get("MM_BOT_TOKEN", ""),
        "mm_notify_channel_id": os.environ.get("MM_NOTIFY_CHANNEL_ID", ""),

        # Phase 3
        "github_token": os.environ.get("GITHUB_TOKEN", ""),
        "github_url": os.environ.get("GITHUB_URL", "https://api.github.com"),
    }

    # --- Project resolution: legacy vs multi ---
    projects_json = os.environ.get("GITLAB_PROJECTS", "")
    if projects_json:
        # Multi-project mode
        try:
            raw = json.loads(projects_json)
        except json.JSONDecodeError as e:
            raise ValueError(f"GITLAB_PROJECTS is not valid JSON: {e}")

        projects = {}
        for alias, pconf in raw.items():
            projects[alias] = {
                "id": str(pconf["id"]),
                "name": pconf.get("name", alias),
                "labels": pconf.get("labels", ""),
                "backend": pconf.get("backend", "gitlab"),
            }
        cfg["projects"] = projects
        cfg["default_project"] = os.environ.get(
            "GITLAB_DEFAULT_PROJECT",
            next(iter(projects))  # first key
        )
        log.info(f"Multi-project mode: {list(projects.keys())}, default={cfg['default_project']}")
    else:
        # Legacy single-project mode
        project_id = os.environ.get("GITLAB_PROJECT_ID", "")
        if not project_id:
            raise ValueError("Set either GITLAB_PROJECTS (multi) or GITLAB_PROJECT_ID (legacy)")
        labels = os.environ.get("PROJECT_LABELS",
            "ai,bug,documentation,enhancement,infrastructure,prototype,research,voice,"
            "priorityhigh,prioritymedium,prioritylow,good first issue,help wanted")
        cfg["projects"] = {
            "default": {
                "id": project_id,
                "name": "Default",
                "labels": labels,
                "backend": "gitlab",
            }
        }
        cfg["default_project"] = "default"
        log.info("Legacy single-project mode")

    return cfg


def resolve_project(cfg: dict, alias: str) -> tuple[str, dict]:
    """Resolve a project alias to (alias, project_config).

    If alias is empty, returns the default project.
    Raises KeyError if alias is not found.
    """
    projects = cfg["projects"]
    if not alias:
        alias = cfg["default_project"]
    if alias not in projects:
        raise KeyError(f"Unknown project '{alias}'. Available: {', '.join(projects.keys())}")
    return alias, projects[alias]


def get_project_labels(project: dict) -> list[str]:
    """Get label list from a project config."""
    labels_str = project.get("labels", "")
    if not labels_str:
        return []
    return [l.strip() for l in labels_str.split(",") if l.strip()]


def get_all_labels(cfg: dict) -> list[str]:
    """Get a deduplicated list of all labels across all projects."""
    seen = set()
    result = []
    for proj in cfg["projects"].values():
        for label in get_project_labels(proj):
            if label not in seen:
                seen.add(label)
                result.append(label)
    return result
