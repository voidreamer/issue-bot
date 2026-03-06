"""
GitLab API helpers — issues, members, milestones, iterations, search, context.
"""

import logging
import httpx

log = logging.getLogger("issue-bot")


async def create_gitlab_issue(
    http_client: httpx.AsyncClient,
    cfg: dict,
    project_id: str,
    title: str,
    description: str,
    labels: list[str],
    weight: int,
    **extra,
) -> dict:
    url = f"{cfg['gitlab_url']}/api/v4/projects/{project_id}/issues"
    params = {"title": title, "description": description,
              "labels": ",".join(labels), "weight": weight}
    params.update(extra)
    resp = await http_client.post(url,
        headers={"PRIVATE-TOKEN": cfg["gitlab_token"]}, json=params)
    resp.raise_for_status()
    return resp.json()


async def get_gitlab_iterations(
    http_client: httpx.AsyncClient,
    cfg: dict,
    project_id: str,
) -> list[dict]:
    """Fetch active iterations for the project's group."""
    try:
        url = f"{cfg['gitlab_url']}/api/v4/projects/{project_id}/iterations?state=opened"
        resp = await http_client.get(url, headers={"PRIVATE-TOKEN": cfg["gitlab_token"]})
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return []


async def get_gitlab_milestones(
    http_client: httpx.AsyncClient,
    cfg: dict,
    project_id: str,
) -> list[dict]:
    """Fetch active milestones."""
    try:
        url = f"{cfg['gitlab_url']}/api/v4/projects/{project_id}/milestones?state=active"
        resp = await http_client.get(url, headers={"PRIVATE-TOKEN": cfg["gitlab_token"]})
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return []


async def get_gitlab_project_members(
    http_client: httpx.AsyncClient,
    cfg: dict,
    project_id: str,
) -> list[dict]:
    """Fetch project members (including inherited)."""
    try:
        url = f"{cfg['gitlab_url']}/api/v4/projects/{project_id}/members/all?per_page=100"
        resp = await http_client.get(url, headers={"PRIVATE-TOKEN": cfg["gitlab_token"]})
        resp.raise_for_status()
        return [{"id": m["id"], "name": m["name"], "username": m["username"]} for m in resp.json()]
    except Exception:
        return []


async def search_gitlab_issues(
    http_client: httpx.AsyncClient,
    cfg: dict,
    project_id: str,
    query: str = "",
    state: str = "opened",
    per_page: int = 10,
) -> list[dict]:
    """Search issues in a GitLab project."""
    try:
        url = f"{cfg['gitlab_url']}/api/v4/projects/{project_id}/issues"
        params = {"state": state, "per_page": per_page, "order_by": "updated_at", "sort": "desc"}
        if query:
            params["search"] = query
        resp = await http_client.get(url,
            headers={"PRIVATE-TOKEN": cfg["gitlab_token"]}, params=params)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        log.error(f"GitLab search failed: {e}")
        return []


async def fetch_project_context(
    http_client: httpx.AsyncClient,
    cfg: dict,
    project_id: str,
) -> str:
    """Fetch lightweight project context for LLM injection.

    Returns a formatted string with recent open issues and active milestones,
    or empty string if fetching fails.
    """
    issues = await search_gitlab_issues(http_client, cfg, project_id=project_id, per_page=15)
    milestones = await get_gitlab_milestones(http_client, cfg, project_id=project_id)

    parts = []

    if issues:
        issue_lines = []
        for iss in issues:
            labels = ", ".join(iss.get("labels", []))
            label_part = f" [{labels}]" if labels else ""
            issue_lines.append(f"  - #{iss.get('iid', '?')}: {iss.get('title', 'Untitled')}{label_part}")
        parts.append("Recent open issues:\n" + "\n".join(issue_lines))

    if milestones:
        ms_lines = [f"  - {m.get('title', 'Untitled')}" for m in milestones]
        parts.append("Active milestones:\n" + "\n".join(ms_lines))

    return "\n\n".join(parts)
