#!/usr/bin/env bash
set -euo pipefail

backend_dev_mode="${BACKEND_DEV_MODE:-false}"
storage_root="${STORAGE_PATH:-/data/storage}"
builtin_voice_src="/opt/localvideo/builtin-storage/voice-library/builtin"
builtin_voice_dst="${storage_root}/voice-library/builtin"
builtin_reference_src="/opt/localvideo/builtin-storage/reference-library/builtin"
builtin_reference_dst="${storage_root}/reference-library/builtin"

mkdir -p \
  /data \
  "${storage_root}" \
  /data/cache/huggingface \
  /data/cache/torch

if [ -d "${builtin_voice_src}" ]; then
  mkdir -p "${builtin_voice_dst}"
  cp -an "${builtin_voice_src}/." "${builtin_voice_dst}/"
fi

if [ -d "${builtin_reference_src}" ]; then
  mkdir -p "${builtin_reference_dst}"
  cp -an "${builtin_reference_src}/." "${builtin_reference_dst}/"
fi

if [ "$#" -gt 0 ]; then
  exec "$@"
fi

cd /app/backend
if [ "${backend_dev_mode}" = "true" ]; then
  # Keep the mounted workspace environment aligned with the lockfile.
  uv sync --frozen --no-dev --python 3.11
fi

uv run alembic upgrade head

if [ "${backend_dev_mode}" = "true" ]; then
  exec uv run uvicorn app.main:app \
    --host 0.0.0.0 \
    --port "${PORT:-8000}" \
    --reload \
    --reload-dir /app/backend/app \
    --reload-dir /app/backend/scripts
fi

exec uv run uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
