"""
GitHub API helpers — issues, members, search.

Provides a parallel interface to gitlab.py for GitHub-backed projects.
"""

import logging
import httpx

log = logging.getLogger("issue-bot")


async def create_github_issue(
    http_client: httpx.AsyncClient,
    cfg: dict,
    repo: str,
    title: str,
    description: str,
    labels: list[str],
    weight: int = 0,
    **extra,
) -> dict:
    """Create a GitHub issue. `repo` should be 'owner/repo' format.

    Returns dict with keys normalized to match GitLab output:
      iid -> number, web_url -> html_url
    """
    github_url = cfg.get("github_url", "https://api.github.com")
    token = cfg.get("github_token", "")

    # Add points label if weight > 0 (GitHub has no native weight)
    issue_labels = list(labels)
    if weight:
        issue_labels.append(f"points:{weight}")

    body = {"title": title, "body": description, "labels": issue_labels}
    if extra.get("assignee_id"):
        # GitHub uses usernames, not IDs for assignees
        # The caller should pass assignees as a list of usernames
        pass
    if extra.get("assignees"):
        body["assignees"] = extra["assignees"]
    if extra.get("milestone_id"):
        body["milestone"] = int(extra["milestone_id"])

    resp = await http_client.post(
        f"{github_url}/repos/{repo}/issues",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
        },
        json=body,
    )
    resp.raise_for_status()
    gh_issue = resp.json()

    # Normalize to match GitLab shape
    return {
        "iid": gh_issue["number"],
        "web_url": gh_issue["html_url"],
        "title": gh_issue["title"],
        "state": gh_issue["state"],
        "labels": [l["name"] if isinstance(l, dict) else l for l in gh_issue.get("labels", [])],
    }


async def search_github_issues(
    http_client: httpx.AsyncClient,
    cfg: dict,
    repo: str,
    query: str = "",
    state: str = "open",
    per_page: int = 10,
) -> list[dict]:
    """Search issues in a GitHub repo."""
    try:
        github_url = cfg.get("github_url", "https://api.github.com")
        token = cfg.get("github_token", "")

        params = {"state": state, "per_page": per_page, "sort": "updated", "direction": "desc"}
        url = f"{github_url}/repos/{repo}/issues"

        if query:
            # Use GitHub search API for text search
            search_url = f"{github_url}/search/issues"
            q = f"{query} repo:{repo} is:issue state:{state}"
            resp = await http_client.get(
                search_url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                },
                params={"q": q, "per_page": per_page},
            )
            resp.raise_for_status()
            items = resp.json().get("items", [])
        else:
            resp = await http_client.get(
                url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                },
                params=params,
            )
            resp.raise_for_status()
            # Filter out pull requests (GitHub returns PRs in issues endpoint)
            items = [i for i in resp.json() if "pull_request" not in i]

        # Normalize to match GitLab shape
        return [
            {
                "iid": i["number"],
                "title": i["title"],
                "web_url": i["html_url"],
                "state": "opened" if i["state"] == "open" else "closed",
                "labels": [l["name"] if isinstance(l, dict) else l for l in i.get("labels", [])],
            }
            for i in items
        ]
    except Exception as e:
        log.error(f"GitHub search failed: {e}")
        return []


async def get_github_repo_collaborators(
    http_client: httpx.AsyncClient,
    cfg: dict,
    repo: str,
) -> list[dict]:
    """Fetch repo collaborators."""
    try:
        github_url = cfg.get("github_url", "https://api.github.com")
        token = cfg.get("github_token", "")

        resp = await http_client.get(
            f"{github_url}/repos/{repo}/collaborators",
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
            },
            params={"per_page": 100},
        )
        resp.raise_for_status()
        return [{"id": m["id"], "name": m["login"], "username": m["login"]} for m in resp.json()]
    except Exception as e:
        log.error(f"GitHub collaborators fetch failed: {e}")
        return []
