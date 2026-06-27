"""Точка входа FastAPI: API + отдача статического фронтенда."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .api import router
from .config import FRONTEND_DIR, get_settings
from .seed import run_seed

settings = get_settings()

app = FastAPI(title="AI Smeta KZ", version="0.1.0")

_cors_origins = settings.cors_origin_list
# Нельзя сочетать wildcard-origin с allow_credentials (спецификация Fetch и
# защита от кражи кук): разрешаем учётные данные только при явном allowlist.
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=_cors_origins != ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.on_event("startup")
def _startup() -> None:
    run_seed()


# ── статический фронтенд ──
if FRONTEND_DIR.exists():
    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(str(FRONTEND_DIR / "index.html"))

    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="static")
