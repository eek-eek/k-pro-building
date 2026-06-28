"""Простая авторизация админ-раздела (Настройки/Промпты).

HTTP Basic; логин/пароль берутся из окружения (ADMIN_USER/ADMIN_PASSWORD).
Дефолт — только для локальной разработки; на проде задайте ADMIN_PASSWORD в .env.
Поверх на проде стоит ещё basic-auth Caddy."""
from __future__ import annotations

import base64
import logging
import secrets

from fastapi import Header, HTTPException

from .config import get_settings

_UNAUTH = {"WWW-Authenticate": "Basic"}
_DEFAULT_PASS = "admin12345"  # дефолт из config — для предупреждения

if get_settings().admin_password == _DEFAULT_PASS:
    logging.getLogger("uvicorn.error").warning(
        "ADMIN_PASSWORD не задан — используется небезопасный дефолт. "
        "Задайте ADMIN_PASSWORD в backend/.env перед публикацией в прод."
    )


def require_admin(authorization: str = Header(default="")) -> None:
    """FastAPI-зависимость: пропускает только заданные ADMIN_USER/ADMIN_PASSWORD (Basic)."""
    if not authorization.startswith("Basic "):
        raise HTTPException(status_code=401, detail="нужна авторизация", headers=_UNAUTH)
    try:
        raw = base64.b64decode(authorization[6:]).decode("utf-8")
        user, _, pwd = raw.partition(":")
    except Exception:
        raise HTTPException(status_code=401, detail="неверный формат авторизации", headers=_UNAUTH)
    cfg = get_settings()
    ok = (secrets.compare_digest(user, cfg.admin_user)
          and secrets.compare_digest(pwd, cfg.admin_password))
    if not ok:
        raise HTTPException(status_code=401, detail="неверный логин или пароль", headers=_UNAUTH)
