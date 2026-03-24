set shell := ["bash", "-lc"]

default:
  @just --list

backend-sync:
  cd backend && uv sync --extra dev

frontend-sync:
  cd frontend && pnpm install

sync: backend-sync frontend-sync

migrate:
  cd backend && uv run alembic upgrade head

dev-backend:
  @just dev-backend-cpu

dev-backend-cpu:
  cd backend && uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

dev-backend-gpu:
  cd backend && DEPLOYMENT_PROFILE=gpu uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000 --timeout-graceful-shutdown 3

backend-cpu:
  cd backend && DEPLOYMENT_PROFILE=cpu uv run uvicorn app.main:app --host 0.0.0.0 --port 8000

backend-gpu:
  cd backend && DEPLOYMENT_PROFILE=gpu uv run uvicorn app.main:app --host 0.0.0.0 --port 8000

dev-frontend:
  cd frontend && pnpm dev

lint-backend:
  cd backend && uv run --with ruff==0.15.2 ruff check .

typecheck-backend:
  cd backend && uv run --with basedpyright==1.38.2 basedpyright --project pyrightconfig.json

lint-frontend:
  cd frontend && pnpm lint

lint: lint-backend lint-frontend

test-backend:
  cd backend && uv run --with pytest pytest

test: test-backend

build-frontend:
  cd frontend && pnpm build

playwright-install:
  cd frontend && pnpm exec playwright install chromium

test-e2e:
  cd frontend && pnpm test:e2e

check: lint test build-frontend

docker-cpu:
  docker compose --profile cpu up -d --build

docker-gpu:
  docker compose --profile gpu up -d --build

docker-dev-cpu:
  docker compose -f docker-compose.yml -f docker-compose.dev.yml --profile cpu up --build

docker-dev-gpu:
  docker compose -f docker-compose.yml -f docker-compose.dev.yml --profile gpu up --build
