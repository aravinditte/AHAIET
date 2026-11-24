from __future__ import annotations
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from app.api.routes import router
from app.core.config import Settings, settings as env_settings
from app.core.errors import AppError, error_body
from app.core.security import (BodySizeLimitMiddleware, RateLimitMiddleware,
                               SecurityHeadersMiddleware)
from app.storage.db import migrate

def create_app(settings: Settings | None = None) -> FastAPI:
    s = settings or env_settings
    migrate(s.db_path)
    s.storage_dir.mkdir(parents=True, exist_ok=True)
    retention_degraded = False
    if s.retention_sweep_on_startup:
        # Optional retention sweep at startup (off by default; the
        # maintenance CLI is the primary route, and the documented
        # scheduled route is scripts/install-retention-task.ps1).
        # AHAIET-017: a failed sweep is NEVER silently swallowed — it
        # is logged structurally and surfaced as a degraded retention
        # flag on the app state and /api/capabilities.
        try:
            from app.maintenance import run_retention
            run_retention(s)
        except Exception as e:
            retention_degraded = True
            import logging
            logging.getLogger("ahaiet.retention").error(
                "retention sweep failed at startup: %s: %s",
                type(e).__name__, e)
    app = FastAPI(title="AHAIET Backend", version="0.1.0")
    app.state.settings = s
    app.state.retention_degraded = retention_degraded
    # Background job lifecycle (AHAIET-009): bounded executor +
    # startup recovery of orphaned jobs (marked failed,
    # worker_restarted) before the first request is served.
    from app.services import job_runner
    app.state.job_manager = job_runner.JobManager(s)
    try:
        job_runner.recover_orphaned_jobs(s)
    except Exception:
        pass
    # CORS: only the configured local origins, never a wildcard by
    # default (AHAIET_CORS_ORIGINS overrides). The frontend is a local
    # app talking to a local backend; nothing else needs access.
    app.add_middleware(CORSMiddleware, allow_origins=list(s.cors_origins), allow_methods=["*"], allow_headers=["*"])
    # Per-client budgets for the expensive/write endpoints (429 with the
    # standard error envelope when exceeded). See docs/SECURITY.md.
    app.add_middleware(RateLimitMiddleware, limits={
        "/api/uploads": s.rate_limit_uploads_per_min,
        "/api/ocr": s.rate_limit_ocr_per_min,
        "/api/translate": s.rate_limit_translate_per_min,
        "/api/process": s.rate_limit_process_per_min,
    }, max_clients=s.rate_limit_max_clients,
        trust_forwarded_for=s.trust_forwarded_for)
    # App-level body ceiling, on top of the per-upload limits enforced
    # by the upload validation itself.
    app.add_middleware(BodySizeLimitMiddleware, max_bytes=s.effective_request_max_bytes)
    # Security response headers on every response, errors included.
    app.add_middleware(SecurityHeadersMiddleware)
    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError):
        return JSONResponse(status_code=exc.status_code, content=error_body(exc))
    app.include_router(router)
    return app

app = create_app()
