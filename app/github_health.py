from __future__ import annotations

import time
from collections import Counter
from typing import Any

import httpx


class GitHubHealthError(RuntimeError):
    pass


class GitHubHealthService:
    def __init__(self, owner: str, token: str | None, cache_seconds: int = 300) -> None:
        self.owner = owner
        self.token = token
        self.cache_seconds = cache_seconds
        self._snapshot: dict[str, Any] | None = None
        self._cached_at = 0.0

    async def snapshot(self, refresh: bool = False) -> dict[str, Any]:
        if not self.token:
            raise GitHubHealthError("GitHub integration is not configured on this server.")
        if not refresh and self._snapshot and time.monotonic() - self._cached_at < self.cache_seconds:
            return self._snapshot

        async with httpx.AsyncClient(
            base_url="https://api.github.com",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {self.token}",
                "X-GitHub-Api-Version": "2022-11-28",
                "User-Agent": "repo-health-dashboard",
            },
            timeout=20,
        ) as client:
            repositories = await self._get(client, "/user/repos", {"affiliation": "owner", "per_page": 100, "sort": "updated"})
            repositories = [repo for repo in repositories if repo.get("owner", {}).get("login") == self.owner]
            issue_counts = await self._search_counts(client, "issue")
            pr_counts = await self._search_counts(client, "pr")

        rows = [
            {
                "name": repo["name"],
                "full_name": repo["full_name"],
                "url": repo["html_url"],
                "visibility": repo.get("visibility", "private" if repo.get("private") else "public"),
                "archived": repo.get("archived", False),
                "default_branch": repo.get("default_branch"),
                "size_kb": repo.get("size", 0),
                "open_issues": issue_counts[repo["full_name"]],
                "open_pull_requests": pr_counts[repo["full_name"]],
                "updated_at": repo.get("updated_at"),
            }
            for repo in repositories
        ]
        rows.sort(key=lambda row: (row["archived"], -(row["open_issues"] + row["open_pull_requests"]), row["name"].lower()))
        self._snapshot = {
            "owner": self.owner,
            "generated_at": int(time.time()),
            "repositories": rows,
            "totals": {
                "repositories": len(rows),
                "open_issues": sum(row["open_issues"] for row in rows),
                "open_pull_requests": sum(row["open_pull_requests"] for row in rows),
                "private": sum(row["visibility"] == "private" for row in rows),
                "archived": sum(row["archived"] for row in rows),
            },
        }
        self._cached_at = time.monotonic()
        return self._snapshot

    async def _search_counts(self, client: httpx.AsyncClient, item_type: str) -> Counter[str]:
        payload = await self._get(client, "/search/issues", {"q": f"user:{self.owner} is:{item_type} is:open", "per_page": 100})
        counts: Counter[str] = Counter()
        for item in payload.get("items", []):
            full_name = item.get("repository_url", "").removeprefix("https://api.github.com/repos/")
            if full_name:
                counts[full_name] += 1
        return counts

    @staticmethod
    async def _get(client: httpx.AsyncClient, path: str, params: dict[str, Any]) -> Any:
        response = await client.get(path, params=params)
        if response.status_code == 401:
            raise GitHubHealthError("GitHub token is invalid or does not have repository access.")
        if response.status_code == 403:
            raise GitHubHealthError("GitHub denied the request or rate limiting is active.")
        if response.is_error:
            raise GitHubHealthError(f"GitHub returned {response.status_code}.")
        return response.json()
