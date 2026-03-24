import asyncio
import logging
import re
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import OperationalError

from app.api.health import router as health_router
from app.api.v1.router import router as v1_router
from app.config import settings
from app.core.errors import ServiceError
from app.db.session import AsyncSessionLocal, init_db
from app.providers.wan2gp import cleanup_wan2gp_runtime_processes
from app.services.reference_library_service import ReferenceLibraryService
from app.services.stage_orchestration_mixin import StageOrchestrationMixin
from app.services.text_library_service import TextLibraryService
from app.services.voice_library_service import VoiceLibraryService

# Configure logging
log_level = logging.DEBUG if settings.debug else logging.INFO
logging.basicConfig(
    level=log_level,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
# Set specific loggers to debug for LLM prompts
logging.getLogger("app.providers.llm").setLevel(logging.DEBUG)

logger = logging.getLogger(__name__)
_library_import_schema_warned = False


class _StagePollAccessLogFilter(logging.Filter):
    """Reduce uvicorn access-log noise from frontend stage polling."""

    _poll_path_pattern = re.compile(r"^/api/v1/projects/\d+/stages(?:/[^/?]+)?/?$")

    def filter(self, record: logging.LogRecord) -> bool:
        args = getattr(record, "args", ())
        if not isinstance(args, tuple) or len(args) < 5:
            return True

        method = str(args[1]) if len(args) > 1 else ""
        raw_path = str(args[2]) if len(args) > 2 else ""
        status_code = str(args[4]) if len(args) > 4 else ""
        path = raw_path.split("?", maxsplit=1)[0]

        if (
            method in {"GET", "OPTIONS"}
            and status_code == "200"
            and self._poll_path_pattern.match(path)
        ):
            return False
        return True


_uvicorn_access_logger = logging.getLogger("uvicorn.access")
if not any(
    isinstance(one_filter, _StagePollAccessLogFilter)
    for one_filter in _uvicorn_access_logger.filters
):
    _uvicorn_access_logger.addFilter(_StagePollAccessLogFilter())


async def _recover_stale_running_state_on_startup() -> None:
    """After process restart, in-memory workers are gone, so persisted RUNNING rows are stale."""
    async with AsyncSessionLocal() as session:
        projects, stages = await StageOrchestrationMixin.recover_stale_state_on_startup(session)
        if stages or projects:
            logger.warning(
                "[Startup] Recovered stale running state: projects=%d stages=%d",
                projects,
                stages,
            )


async def _reconcile_stale_library_import_jobs_once() -> tuple[int, int]:
    global _library_import_schema_warned
    try:
        ref = await ReferenceLibraryService.reconcile_stale_import_jobs()
        voice = await VoiceLibraryService.reconcile_stale_import_jobs()
        text = await TextLibraryService.reconcile_stale_import_jobs()
    except OperationalError as exc:
        message = str(exc).lower()
        missing_column = "no such column" in message or "undefined column" in message
        if missing_column:
            if not _library_import_schema_warned:
                logger.warning(
                    "[ImportReconciler] Skip stale-import reconciliation because DB schema is outdated. "
                    "Please run migration: `uv run alembic upgrade head`. detail=%s",
                    exc,
                )
                _library_import_schema_warned = True
            return 0, 0
        raise
    reconciled_jobs = (
        int(ref.get("reconciled_jobs", 0))
        + int(voice.get("reconciled_jobs", 0))
        + int(text.get("reconciled_jobs", 0))
    )
    reconciled_tasks = (
        int(ref.get("reconciled_tasks", 0))
        + int(voice.get("reconciled_tasks", 0))
        + int(text.get("reconciled_tasks", 0))
    )
    return reconciled_jobs, reconciled_tasks


async def _recover_stale_library_import_jobs_on_startup() -> None:
    reconciled_jobs, reconciled_tasks = await _reconcile_stale_library_import_jobs_once()
    if reconciled_jobs or reconciled_tasks:
        logger.warning(
            "[Startup] Reconciled stale library imports: jobs=%d tasks=%d",
            reconciled_jobs,
            reconciled_tasks,
        )


async def _run_library_import_reconciler(stop_event: asyncio.Event) -> None:
    interval_seconds = max(
        5, int(getattr(settings, "library_import_reconcile_interval_seconds", 30) or 30)
    )
    while not stop_event.is_set():
        try:
            await _reconcile_stale_library_import_jobs_once()
        except Exception:
            logger.exception("[ImportReconciler] failed while reconciling stale library imports")

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
        except TimeoutError:
            continue


@asynccontextmanager
async def lifespan(app: FastAPI):
    reconciler_stop = asyncio.Event()
    reconciler_task: asyncio.Task[None] | None = None
    released_at_start = cleanup_wan2gp_runtime_processes()
    if released_at_start:
        logger.info("[Startup] Released %d stale Wan2GP subprocess(es)", released_at_start)
    await init_db()
    await _recover_stale_running_state_on_startup()
    await _recover_stale_library_import_jobs_on_startup()
    storage_path = Path(settings.storage_path)
    storage_path.mkdir(parents=True, exist_ok=True)
    ReferenceLibraryService.bootstrap_builtin_assets()
    reconciler_task = asyncio.create_task(_run_library_import_reconciler(reconciler_stop))
    try:
        yield
    finally:
        reconciler_stop.set()
        if reconciler_task:
            reconciler_task.cancel()
            try:
                await reconciler_task
            except asyncio.CancelledError:
                pass
        released_at_shutdown = cleanup_wan2gp_runtime_processes()
        if released_at_shutdown:
            logger.info("[Shutdown] Released %d Wan2GP subprocess(es)", released_at_shutdown)


app = FastAPI(
    title=settings.project_name,
    version=settings.project_version,
    debug=settings.debug,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_origin_regex=settings.cors_origin_regex,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router, tags=["health"])
app.include_router(v1_router, prefix=settings.api_prefix)

storage_path = Path(settings.storage_path)
storage_path.mkdir(parents=True, exist_ok=True)
app.mount("/storage", StaticFiles(directory=str(storage_path)), name="storage")


@app.exception_handler(ServiceError)
async def _service_error_handler(request, exc: ServiceError):  # noqa: ARG001
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.get("/")
async def root():
    return {
        "message": "LocalVideo Backend API",
        "version": settings.project_version,
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
