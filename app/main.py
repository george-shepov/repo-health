from __future__ import annotations

import secrets
from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.github_health import GitHubHealthError, GitHubHealthService


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    github_token: str | None = None
    admin_token: str | None = None
    github_owner: str = "george-shepov"
    github_health_cache_seconds: int = 300


settings = Settings()
service = GitHubHealthService(
    owner=settings.github_owner,
    token=settings.github_token,
    cache_seconds=max(30, settings.github_health_cache_seconds),
)
app = FastAPI(title="Repository Health", version="1.0.0")
DASHBOARD_PATH = Path(__file__).parent / "static" / "index.html"


def require_admin(x_admin_token: str | None = Header(default=None)) -> None:
    if not settings.admin_token:
        raise HTTPException(status_code=503, detail="Dashboard admin access is not configured.")
    if not x_admin_token or not secrets.compare_digest(x_admin_token, settings.admin_token):
        raise HTTPException(status_code=401, detail="Admin authentication is required.")


@app.get("/", include_in_schema=False)
@app.get("/health", include_in_schema=False)
def dashboard() -> FileResponse:
    return FileResponse(DASHBOARD_PATH)


@app.get("/api/health")
def health() -> dict:
    return {"status": "healthy", "admin_configured": bool(settings.admin_token), "github_configured": bool(settings.github_token)}


@app.get("/api/repository-health", dependencies=[Depends(require_admin)])
async def repository_health(refresh: bool = Query(default=False)) -> dict:
    try:
        return await service.snapshot(refresh=refresh)
    except GitHubHealthError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
