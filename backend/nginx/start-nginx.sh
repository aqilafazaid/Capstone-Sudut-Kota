#!/usr/bin/env bash
# Jalankan dari root repo atau dari folder ini: bash backend/nginx/start-nginx.sh
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
mkdir -p logs
if command -v cygpath >/dev/null 2>&1; then
    ROOT_WIN="$(cygpath -w "$ROOT")"
else
    ROOT_WIN="$ROOT"
fi
./tools/nginx/nginx.exe -p "$ROOT_WIN" -c backend/nginx/nginx.conf >/dev/null 2>&1 &
sleep 1
echo "nginx start diminta (pid file: logs/nginx.pid)."
