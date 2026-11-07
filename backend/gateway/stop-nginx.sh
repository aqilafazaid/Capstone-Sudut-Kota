#!/usr/bin/env bash
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
cd "$ROOT"
if command -v cygpath >/dev/null 2>&1; then
    ROOT_WIN="$(cygpath -w "$ROOT")"
else
    ROOT_WIN="$ROOT"
fi
backend/gateway/tools/nginx/nginx.exe -p "$ROOT_WIN" -e backend/gateway/logs/error.log -c backend/gateway/nginx.conf -s stop
echo "nginx dihentikan."
