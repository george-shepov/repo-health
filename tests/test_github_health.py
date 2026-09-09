import pytest

from app.github_health import GitHubHealthService


@pytest.mark.asyncio
async def test_snapshot_aggregates_owned_repositories_and_open_work(monkeypatch):
    service = GitHubHealthService("george-shepov", "not-a-real-token")

    async def fake_get(client, path, params):
        if path == "/user/repos":
            return [
                {
                    "name": "FieldKit",
                    "full_name": "george-shepov/FieldKit",
                    "html_url": "https://github.com/george-shepov/FieldKit",
                    "visibility": "public",
                    "archived": False,
                    "default_branch": "main",
                    "size": 1800,
                    "updated_at": "2026-07-13T00:00:00Z",
                    "owner": {"login": "george-shepov"},
                },
                {"owner": {"login": "other-user"}},
            ]
        if "is:issue" in params.get("q", ""):
            return {"items": [{"repository_url": "https://api.github.com/repos/george-shepov/FieldKit"}]}
        if "q" in params:
            return {"items": [{"repository_url": "https://api.github.com/repos/george-shepov/FieldKit"}]}
        if path.endswith("/commits"):
            return [{"commit": {"committer": {"date": "2026-07-13T00:00:00Z"}}}]
        if path.endswith("/contributors"):
            return [{"login": "george-shepov"}]
        if path.endswith("/releases") or path.endswith("/tags") or path.endswith("/deployments"):
            return []
        if path.endswith("/actions/workflows"):
            return {"workflows": []}
        if path.endswith("/actions/runs"):
            return {"workflow_runs": []}
        return {}

    monkeypatch.setattr(service, "_get", fake_get)
    result = await service.snapshot(refresh=True)

    assert result["totals"]["repositories"] == 1
    assert result["totals"]["open_issues"] == 1
    assert result["totals"]["open_pull_requests"] == 1
    assert result["repositories"][0]["recent_commit_activity"]["commits_sampled"] == 1
    assert result["repositories"][0]["ci"]["healthy"] is False
    assert result["repositories"][0]["deployment_activity"]["count"] == 0
