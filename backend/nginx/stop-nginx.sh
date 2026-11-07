#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
if command -v cygpath >/dev/null 2>&1; then
    ROOT_WIN="$(cygpath -w "$ROOT")"
else
    ROOT_WIN="$ROOT"
fi
./tools/nginx/nginx.exe -p "$ROOT_WIN" -c backend/nginx/nginx.conf -s stop
