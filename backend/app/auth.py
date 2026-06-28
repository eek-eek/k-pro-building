"""Простая авторизация админ-раздела (Настройки/Промпты).

HTTP Basic с фиксированными учётными данными. Этого достаточно, чтобы скрыть
настройки от случайных пользователей; на проде поверх ещё стоит basic-auth Caddy."""
from __future__ import annotations

import base64
import secrets

from fastapi import Header, HTTPException

ADMIN_USER = "admin"
ADMIN_PASS = "admin12345"
_UNAUTH = {"WWW-Authenticate": "Basic"}


def require_admin(authorization: str = Header(default="")) -> None:
    """FastAPI-зависимость: пропускает только admin/admin12345 (Basic)."""
    if not authorization.startswith("Basic "):
        raise HTTPException(status_code=401, detail="нужна авторизация", headers=_UNAUTH)
    try:
        raw = base64.b64decode(authorization[6:]).decode("utf-8")
        user, _, pwd = raw.partition(":")
    except Exception:
        raise HTTPException(status_code=401, detail="неверный формат авторизации", headers=_UNAUTH)
    ok = secrets.compare_digest(user, ADMIN_USER) and secrets.compare_digest(pwd, ADMIN_PASS)
    if not ok:
        raise HTTPException(status_code=401, detail="неверный логин или пароль", headers=_UNAUTH)
