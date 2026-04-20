#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  python3 -m venv .venv
  ./.venv/bin/pip install -q -r requirements.txt
fi
exec ./.venv/bin/uvicorn backend.main:app --reload --host 127.0.0.1 --port 8765
