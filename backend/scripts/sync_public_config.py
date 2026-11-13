"""Hasilkan konfigurasi publik frontend dari backend/.env.

Tiga berkas keluaran, semuanya berisi nilai PUBLIK (boleh di-commit):

    frontend/js/firebase-config.js  Firebase Web SDK + FIREBASE_READY
    frontend/js/public-config.js    alamat backend + status proxy Vercel
    vercel.json                     rewrite /api dan /hls ke Funnel

    python backend/scripts/sync_public_config.py

Halaman Vercel memanggil /api dan /hls pada origin-nya sendiri; Vercel
mem-proxy kedua path itu ke Tailscale Funnel. Peramban tidak pernah membuka
koneksi lintas-origin ke *.ts.net — nama itu di mesin operator diresolve ke IP
tailnet (100.x) sehingga Chrome memblokirnya lewat Private Network Access.

Kunci Admin SDK / service account tidak pernah ditulis ke berkas mana pun.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
ROOT_DIR = BASE_DIR.parent
ENV_FILE = BASE_DIR / ".env"
FIREBASE_OUT = ROOT_DIR / "frontend" / "js" / "firebase-config.js"
PUBLIC_OUT = ROOT_DIR / "frontend" / "js" / "public-config.js"
VERCEL_FILE = ROOT_DIR / "vercel.json"

# Path yang diproxy Vercel ke backend publik.
PROXY_PATHS = ("api", "hls")

FIELDS = (
    ("apiKey", "FIREBASE_API_KEY"),
    ("authDomain", "FIREBASE_AUTH_DOMAIN"),
    ("databaseURL", "FIREBASE_DATABASE_URL"),
    ("projectId", "FIREBASE_PROJECT_ID"),
    ("storageBucket", "FIREBASE_STORAGE_BUCKET"),
    ("messagingSenderId", "FIREBASE_MESSAGING_SENDER_ID"),
    ("appId", "FIREBASE_APP_ID"),
    ("measurementId", "FIREBASE_MEASUREMENT_ID"),
)

FIREBASE_TEMPLATE = """/**\n * Dihasilkan oleh backend/scripts/sync_public_config.py.\n * Jangan edit manual: ubah backend/.env lalu jalankan ulang skrip itu.\n *\n * Hanya berisi kunci PUBLIK Firebase Web SDK. Kunci Admin SDK / service\n * account tidak pernah masuk ke file ini.\n */\nwindow.FIREBASE_CONFIG = {{\n{body}\n}};\n\nwindow.FIREBASE_READY = (function (cfg) {{\n  var required = ['apiKey', 'authDomain', 'databaseURL', 'projectId', 'appId'];\n  return required.every(function (key) {{\n    return String(cfg[key] || '').trim() !== '';\n  }});\n}})(window.FIREBASE_CONFIG);\n"""

PUBLIC_TEMPLATE = """/* Dihasilkan backend/scripts/sync_public_config.py. Jangan edit manual.
 * Isinya publik: alamat backend dan status proxy Vercel (Tailscale Funnel). */
window.SK_PUBLIC = {{
    backendBase: {backend},
    funnelBase: {funnel},
    proxy: {proxy}
}};
"""


def update_vercel(backend: str) -> bool:
    """Tulis rewrite /api dan /hls di vercel.json supaya same-origin.

    Kunci lain di vercel.json tidak disentuh. Tanpa backend, rewrite dikosongkan
    agar halaman Vercel tidak mem-proxy ke alamat yang tidak ada.
    """
    if not VERCEL_FILE.exists():
        return False
    try:
        data = json.loads(VERCEL_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        print(f"[WARN] {VERCEL_FILE.name} bukan JSON valid; rewrite dilewati.")
        return False

    if backend:
        rewrites = [
            {"source": f"/{path}/:path*", "destination": f"{backend}/{path}/:path*"}
            for path in PROXY_PATHS
        ]
    else:
        rewrites = []

    if data.get("rewrites") == rewrites:
        return False
    data["rewrites"] = rewrites
    VERCEL_FILE.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return True


def main() -> int:
    if not ENV_FILE.exists():
        print(f"[ERROR] {ENV_FILE} tidak ditemukan. Salin dari .env.example.")
        return 1

    # override=True: .env adalah sumber kebenaran, bukan variabel shell yang kebetulan ada.
    load_dotenv(ENV_FILE, override=True)

    values = {key: os.environ.get(env_key, "").strip() for key, env_key in FIELDS}
    body = ",\n".join(f"  {key}: {json.dumps(value)}" for key, value in values.items())
    FIREBASE_OUT.write_text(FIREBASE_TEMPLATE.format(body=body), encoding="utf-8")

    backend = os.environ.get("PUBLIC_BACKEND_URL", "").strip().rstrip("/")
    # backendBase kosong: halaman Vercel memakai origin sendiri, lalu Vercel
    # mem-proxy /api + /hls ke Funnel (lihat update_vercel).
    PUBLIC_OUT.write_text(
        PUBLIC_TEMPLATE.format(
            backend=json.dumps(""),
            funnel=json.dumps(backend),
            proxy=json.dumps(bool(backend)).lower(),
        ),
        encoding="utf-8",
    )

    print(f"[OK] {FIREBASE_OUT.relative_to(ROOT_DIR)} ditulis.")
    print(f"[OK] {PUBLIC_OUT.relative_to(ROOT_DIR)} ditulis.")
    if update_vercel(backend):
        print(f"[OK] {VERCEL_FILE.relative_to(ROOT_DIR)}: rewrite /api dan /hls -> {backend}")
    else:
        print(f"[OK] {VERCEL_FILE.relative_to(ROOT_DIR)}: rewrite sudah sesuai.")

    empty = [key for key, value in values.items() if not value]
    if empty:
        print("[INFO] Firebase masih kosong: " + ", ".join(empty) + ".")
        print("[INFO] Frontend tetap berjalan pada mode publik (tanpa login).")
    if not backend:
        print("[INFO] PUBLIC_BACKEND_URL kosong: halaman Vercel tidak punya backend.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
