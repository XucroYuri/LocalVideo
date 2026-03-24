# LocalVideo Backend

FastAPI backend for LocalVideo. It manages projects, staged generation workflows, provider settings, reusable asset libraries, and composition-related APIs.

## Stack

- Python 3.11+
- FastAPI
- SQLAlchemy 2.0 async ORM
- Alembic
- SQLite by default
- SSE streaming endpoints for long-running stage workflows
- Crawl4AI, faster-whisper, edge-tts, and provider integrations

## Local Setup

```bash
cd backend

# Install runtime + dev dependencies
uv sync --extra dev

# Prepare Crawl4AI browser resources once on a fresh machine
uv run crawl4ai-setup

# Apply the current database schema
uv run alembic upgrade head

# Start the development server
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

To run with the GPU deployment profile locally:

```bash
cd backend
DEPLOYMENT_PROFILE=gpu uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## Common Commands

```bash
cd backend

# Sync dependencies
uv sync --extra dev

# Apply migrations
uv run alembic upgrade head

# Create a new migration
uv run alembic revision --autogenerate -m "describe change"

# Lint
uv run --with ruff==0.15.2 ruff check .

# Typecheck
uv run --with basedpyright==1.38.2 basedpyright --project pyrightconfig.json

# Run tests
uv run --with pytest pytest
```

If you use `just`, the root workspace also exposes:

```bash
just backend-sync
just migrate
just dev-backend-cpu
just dev-backend-gpu
just lint-backend
just typecheck-backend
just test-backend
```

## API Surface

The backend serves versioned APIs under `/api/v1`.

Main route groups:

- `/api/v1/projects`: project CRUD and cover regeneration
- `/api/v1/projects/{project_id}/stages`: stage execution, stage streaming, shot editing, and pipeline runs
- `/api/v1/projects/{project_id}/sources`: source material management
- `/api/v1/references`: reusable reference library items and import jobs
- `/api/v1/voice-library`: reusable voice library items and import jobs
- `/api/v1/text-library`: reusable text library items and import jobs
- `/api/v1/settings`: provider settings, validation, and credentials-related endpoints
- `/api/v1/capabilities`: capability and model metadata for the frontend

Useful endpoints during development:

- `GET /health`
- `GET /api/v1/status`
- `GET /api/v1/stages/manifest`
- `GET /api/v1/projects/{project_id}/stages/{stage_type}/stream`

## Notes

- Alembic migrations are the source of truth for schema changes. If you change models in a way that affects persistence, add a migration in the same PR.
- Docker images already run `uv run alembic upgrade head` on startup. Local development does not, so you need to run migrations yourself after pulling schema changes.
- The default local database is `backend/app.db` unless `DATABASE_URL` is overridden.
