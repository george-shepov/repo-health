# Repository Health

A private-admin dashboard for Giorgiy Shepov's GitHub portfolio.

This is a **public code repository**. It deliberately contains no repository snapshot, GitHub token, VPS credential, admin token, or private repository name beyond the default owner configuration.

## What it shows after secure configuration

- Owned repository count
- Open issue and pull-request counts
- Visibility, archive status, default branch, size, and update time
- Search and “open work” filtering

The API refuses to return any portfolio data without a separate administrator token. GitHub access remains server-side.

## Run locally

```bash
cp .env.example .env
# Edit .env with real values — never commit it.
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8080
```

Open http://localhost:8080 and enter the value of `ADMIN_TOKEN`.

## Required runtime secrets

- `GITHUB_TOKEN`: fine-grained GitHub token with read-only access to the repositories to show.
- `ADMIN_TOKEN`: separate long random value required by the dashboard browser before the API returns data.

## VPS deployment

The production container binds only to `127.0.0.1:8091`; it is not exposed directly on the server's public IP.

After this repository's deployment workflow is approved, configure a reverse-proxy host and GitHub environment secrets:

- `VPS_HOST`
- `VPS_USER`
- `VPS_SSH_KEY`
- `REPO_HEALTH_GITHUB_TOKEN`
- `REPO_HEALTH_ADMIN_TOKEN`

The GitHub Actions workflow builds an immutable GHCR image, then deploys it to `/opt/repo-health` using Docker Compose. No credentials are stored in the repository.
