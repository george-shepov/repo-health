from __future__ import annotations

import asyncio
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
            repositories: list[dict[str, Any]] = []
            page = 1
            while True:
                batch = await self._get(client, "/user/repos", {"affiliation": "owner", "per_page": 100, "page": page, "sort": "updated"})
                repositories.extend(repo for repo in batch if repo.get("owner", {}).get("login", "").lower() == self.owner.lower())
                if len(batch) < 100:
                    break
                page += 1
            issue_counts = await self._search_counts(client, "issue")
            pr_counts = await self._search_counts(client, "pr")
            details = await asyncio.gather(*(self._measure_repo(client, repo) for repo in repositories))

        rows = [
            {
                "name": repo["name"],
                "full_name": repo["full_name"],
                "url": repo["html_url"],
                "visibility": repo.get("visibility", "private" if repo.get("private") else "public"),
                "archived": repo.get("archived", False),
                "default_branch": repo.get("default_branch"),
                "size_kb": repo.get("size", 0),
                "stars": repo.get("stargazers_count", 0),
                "forks": repo.get("forks_count", 0),
                "watchers": repo.get("subscribers_count", repo.get("watchers_count", 0)),
                "language": repo.get("language"),
                "description": repo.get("description"),
                "topics": repo.get("topics", []),
                "open_issues": issue_counts[repo["full_name"]],
                "open_pull_requests": pr_counts[repo["full_name"]],
                "updated_at": repo.get("updated_at"),
                "pushed_at": repo.get("pushed_at"),
                **details[index],
            }
            for index, repo in enumerate(repositories)
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
                "stars": sum(row["stars"] for row in rows),
                "forks": sum(row["forks"] for row in rows),
            },
        }
        self._cached_at = time.monotonic()
        return self._snapshot

    async def _measure_repo(self, client: httpx.AsyncClient, repo: dict[str, Any]) -> dict[str, Any]:
        full_name = repo["full_name"]
        branch = repo.get("default_branch") or "main"
        commits, contributors, releases, tags, workflows, runs, deployments, pages, traffic = await asyncio.gather(
            self._optional(client, f"/repos/{full_name}/commits", {"per_page": 30}),
            self._optional(client, f"/repos/{full_name}/contributors", {"per_page": 100}),
            self._optional(client, f"/repos/{full_name}/releases", {"per_page": 10}),
            self._optional(client, f"/repos/{full_name}/tags", {"per_page": 10}),
            self._optional(client, f"/repos/{full_name}/actions/workflows", {"per_page": 100}),
            self._optional(client, f"/repos/{full_name}/actions/runs", {"per_page": 20, "branch": branch}),
            self._optional(client, f"/repos/{full_name}/deployments", {"per_page": 20}),
            self._optional(client, f"/repos/{full_name}/pages", {}),
            self._optional(client, f"/repos/{full_name}/traffic/clones", {"per": "week"}),
        )
        commit_rows = commits if isinstance(commits, list) else []
        workflow_rows = workflows.get("workflows", []) if isinstance(workflows, dict) else []
        run_rows = runs.get("workflow_runs", []) if isinstance(runs, dict) else []
        return {
            "recent_commit_activity": {"commits_sampled": len(commit_rows), "last_commit_at": (commit_rows[0].get("commit", {}).get("committer", {}).get("date") if commit_rows else None)},
            "contributors": len(contributors) if isinstance(contributors, list) else None,
            "releases": len(releases) if isinstance(releases, list) else 0,
            "tags": len(tags) if isinstance(tags, list) else 0,
            "ci": {"workflow_count": len(workflow_rows), "recent_run_count": len(run_rows), "conclusions": Counter(str(run.get("conclusion") or run.get("status") or "unknown") for run in run_rows), "healthy": bool(run_rows) and not any(run.get("conclusion") in {"failure", "timed_out"} for run in run_rows)},
            "deployment_activity": {"available": isinstance(deployments, list), "count": len(deployments) if isinstance(deployments, list) else 0},
            "pages": {"available": not isinstance(pages, dict) or "_unavailable" not in pages, "configured": bool(pages) and not (isinstance(pages, dict) and pages.get("_unavailable"))},
            "traffic": {"clones": traffic if isinstance(traffic, dict) and "_unavailable" not in traffic else {"available": False}},
        }

    async def _optional(self, client: httpx.AsyncClient, path: str, params: dict[str, Any]) -> Any:
        try:
            return await self._get(client, path, params)
        except GitHubHealthError:
            return {"_unavailable": True}

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
