from __future__ import annotations
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from app.api.routes import router
from app.core.config import Settings, settings as env_settings
from app.core.errors import AppError, error_body
from app.storage.db import migrate

def create_app(settings: Settings | None = None) -> FastAPI:
    s = settings or env_settings
    migrate(s.db_path)
    s.storage_dir.mkdir(parents=True, exist_ok=True)
    app = FastAPI(title="AHAIET Backend", version="0.1.0")
    app.state.settings = s
    app.add_middleware(CORSMiddleware, allow_origins=list(s.cors_origins), allow_methods=["*"], allow_headers=["*"])
    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError):
        return JSONResponse(status_code=exc.status_code, content=error_body(exc))
    app.include_router(router)
    return app

app = create_app()
