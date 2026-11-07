#!/usr/bin/env bash
# Jalankan dari mana saja: bash backend/gateway/start-nginx.sh
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
cd "$ROOT"
mkdir -p backend/gateway/logs backend/gateway/temp
if command -v cygpath >/dev/null 2>&1; then
    ROOT_WIN="$(cygpath -w "$ROOT")"
else
    ROOT_WIN="$ROOT"
fi
if tasklist 2>/dev/null | grep -qi 'nginx.exe'; then
    echo "nginx sudah berjalan (http://127.0.0.1:8080)."
    exit 0
fi
backend/gateway/tools/nginx/nginx.exe -p "$ROOT_WIN" -e backend/gateway/logs/error.log -c backend/gateway/nginx.conf >/dev/null 2>&1 &
sleep 1
if tasklist 2>/dev/null | grep -qi 'nginx.exe'; then
    echo "nginx jalan di http://127.0.0.1:8080 (log: backend/gateway/logs/)."
else
    echo "nginx gagal start. Cek backend/gateway/logs/error.log" >&2
    exit 1
fi
