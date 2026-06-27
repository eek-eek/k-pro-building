#!/usr/bin/env bash
# Первичная установка Yale Building Calculator на Ubuntu 22/24 (EC2).
# Запускать из корня репозитория на сервере:  bash deploy/setup.sh
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
RUN_USER="$(whoami)"
RUN_GROUP="$(id -gn)"
cd "$REPO_DIR"

echo "→ [1/5] Python 3.11 + venv"
sudo apt-get update -qq
sudo apt-get install -y -qq python3.11 python3.11-venv python3.11-dev

echo "→ [2/5] Виртуальное окружение и зависимости"
if [ ! -d backend/.venv ]; then
	python3.11 -m venv backend/.venv
fi
backend/.venv/bin/pip install --upgrade pip -q
backend/.venv/bin/pip install -r backend/requirements.txt -q

echo "→ [3/5] .env"
if [ ! -f backend/.env ]; then
	cp .env.example backend/.env
	echo "  ⚠ Заполните ключ ИИ в backend/.env (LLM_PROVIDER + соответствующий *_API_KEY),"
	echo "    либо оставьте LLM_PROVIDER=demo для расчёта по дефолтным нормам без ИИ."
fi

echo "→ [4/5] Прогон тестов (smoke)"
( cd backend && .venv/bin/python -m pytest -q ) || {
	echo "  ✗ Тесты не прошли — остановитесь и проверьте вывод выше."; exit 1; }

echo "→ [5/5] systemd-сервис yale-bc"
TMP_UNIT="$(mktemp)"
sed -e "s#/home/ubuntu/k-pro-building#${REPO_DIR}#g" \
    -e "s#^User=ubuntu#User=${RUN_USER}#" \
    -e "s#^Group=ubuntu#Group=${RUN_GROUP}#" \
    deploy/yale-bc.service > "$TMP_UNIT"
sudo cp "$TMP_UNIT" /etc/systemd/system/yale-bc.service
rm -f "$TMP_UNIT"
sudo systemctl daemon-reload
sudo systemctl enable --now yale-bc
sleep 2
sudo systemctl --no-pager --lines=0 status yale-bc | head -4
curl -fsS -o /dev/null -w "  health: HTTP %{http_code}\n" http://127.0.0.1:8000/api/health || \
	echo "  ✗ Приложение не ответило на 127.0.0.1:8000 — см.  journalctl -u yale-bc -n 50"

cat <<EOF

✓ Бэкенд поднят на 127.0.0.1:8000 (systemd: yale-bc).
  Дальше — Caddy для доступа снаружи с логином/паролем:
    см. deploy/DEPLOY.md, раздел «Caddy».
EOF
