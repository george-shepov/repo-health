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
        if "is:issue" in params["q"]:
            return {"items": [{"repository_url": "https://api.github.com/repos/george-shepov/FieldKit"}]}
        return {"items": [{"repository_url": "https://api.github.com/repos/george-shepov/FieldKit"}]}

    monkeypatch.setattr(service, "_get", fake_get)
    result = await service.snapshot(refresh=True)

    assert result["totals"]["repositories"] == 1
    assert result["totals"]["open_issues"] == 1
    assert result["totals"]["open_pull_requests"] == 1
