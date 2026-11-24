#!/usr/bin/env bash
# Быстрый запуск J.A.R.V.I.S.
cd "$(dirname "$0")" || exit 1
PY="$(command -v python3 || command -v python)"
echo "  Запуск J.A.R.V.I.S.  →  http://localhost:8080"
exec "$PY" jarvis.py "$@"
