#!/usr/bin/env bash
# Запуск AI Smeta KZ (бэкенд + статический фронтенд на одном порту).
set -euo pipefail

cd "$(dirname "$0")/backend"

if [ ! -d ".venv" ]; then
  echo "→ Создаю виртуальное окружение…"
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

pip install -q -r requirements.txt

if [ ! -f ".env" ] && [ -f "../.env.example" ]; then
  echo "→ .env не найден, копирую из .env.example (заполните ключи LLM)."
  cp ../.env.example .env
fi

echo "→ Запуск на http://127.0.0.1:8000"
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
