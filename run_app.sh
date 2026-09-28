#!/usr/bin/env bash
# TRANS ERP - start the application on Linux / macOS (same steps as run_app.bat).
#   ./run_app.sh [port]
set -euo pipefail
cd "$(dirname "$0")"
PORT="${1:-8000}"
[ -x .venv/bin/python ] || python3 -m venv .venv
PY=.venv/bin/python
if ! cmp -s requirements.txt .venv/requirements.installed; then
  "$PY" -m pip install -r requirements.txt && cp requirements.txt .venv/requirements.installed
fi
[ -f .env ] || "$PY" scripts/make_env.py
mkdir -p storage logs
"$PY" scripts/make_env.py --check-db
"$PY" -m alembic upgrade head
if [ ! -f storage/.seeded ]; then
  read -r -p "Also load DEMO data (sample vehicles, drivers, tyres)? [y/N] " a
  if [[ "$a" =~ ^[Yy] ]]; then "$PY" -m app.seed --demo; else "$PY" -m app.seed; fi
  echo seeded > storage/.seeded
fi
echo "App: http://localhost:$PORT   (admin / Admin@12345)   Ctrl+C to stop"
exec "$PY" -m uvicorn app.main:app --host 0.0.0.0 --port "$PORT"
