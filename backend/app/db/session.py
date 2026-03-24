import os
from collections.abc import AsyncGenerator
from functools import lru_cache
from pathlib import Path
from typing import Any

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import event
from sqlalchemy import text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.config import settings
from app.services.settings_store import (
    LEGACY_REMOVED_SETTING_KEYS,
    PERSISTABLE_SETTING_KEYS,
    SettingsStoreService,
)

ENV_PRIORITY_SETTING_KEYS = {
    "deployment_profile",
    "wan2gp_path",
    "local_model_python_path",
    "xhs_downloader_path",
    "tiktok_downloader_path",
    "ks_downloader_path",
}

BACKEND_DIR = Path(__file__).resolve().parents[2]
ALEMBIC_INI_PATH = BACKEND_DIR / "alembic.ini"

connect_args = {}
if settings.database_url.startswith("sqlite"):
    # Increase sqlite lock wait time to reduce "database is locked" during concurrent read/write.
    connect_args["timeout"] = 30

engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    pool_pre_ping=True,
    connect_args=connect_args,
)

if settings.database_url.startswith("sqlite"):

    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragma(dbapi_connection: Any, connection_record: Any) -> None:
        del connection_record
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.close()


AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


@lru_cache(maxsize=1)
def _get_alembic_head_revision() -> str:
    config = Config(str(ALEMBIC_INI_PATH))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    head = ScriptDirectory.from_config(config).get_current_head()
    if not head:
        raise RuntimeError("Alembic head revision is not defined")
    return head


async def _get_current_db_revision(session: AsyncSession) -> str | None:
    try:
        result = await session.execute(sql_text("SELECT version_num FROM alembic_version"))
    except Exception:
        return None

    revisions = [str(item).strip() for item in result.scalars().all() if str(item).strip()]
    if len(revisions) != 1:
        return None
    return revisions[0]


async def init_db():
    async with AsyncSessionLocal() as session:
        head_revision = _get_alembic_head_revision()
        current_revision = await _get_current_db_revision(session)
        if current_revision != head_revision:
            current_label = current_revision or "<none>"
            raise RuntimeError(
                "数据库 schema 未迁移到最新版本。"
                f"当前 revision={current_label}，目标 revision={head_revision}。"
                "请先运行 `uv run alembic upgrade head`。"
            )

        store = SettingsStoreService(session)
        persisted = await store.get_many(PERSISTABLE_SETTING_KEYS)
        for key, value in persisted.items():
            if key in ENV_PRIORITY_SETTING_KEYS:
                current_value = getattr(settings, key, None)
                if current_value not in (None, ""):
                    continue
            if hasattr(settings, key):
                setattr(settings, key, value)
        await store.delete_many(LEGACY_REMOVED_SETTING_KEYS)

        credentials_path = str(settings.google_credentials_path or "").strip()
        if credentials_path:
            os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = credentials_path
