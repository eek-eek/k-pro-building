#!/usr/bin/env bash
# Обновление до свежего master и перезапуск.  bash deploy/update.sh
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_DIR"

echo "→ git pull"
git pull --ff-only

echo "→ зависимости"
backend/.venv/bin/pip install -r backend/requirements.txt -q

echo "→ рестарт"
sudo systemctl restart yale-bc
sleep 2
curl -fsS -o /dev/null -w "  health: HTTP %{http_code}\n" http://127.0.0.1:8000/api/health || \
	echo "  ✗ не ответило — journalctl -u yale-bc -n 50"
echo "✓ Обновлено."
