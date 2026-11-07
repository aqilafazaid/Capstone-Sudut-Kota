"""Hasilkan konfigurasi publik frontend dari backend/.env.

Dua berkas keluaran, keduanya berisi nilai PUBLIK (boleh di-commit):

    frontend/js/firebase-config.js  Firebase Web SDK + FIREBASE_READY
    frontend/js/public-config.js    alamat backend untuk halaman Vercel

    python backend/scripts/sync_public_config.py

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

PUBLIC_TEMPLATE = """/* Dihasilkan backend/scripts/sync_public_config.py. Jangan edit manual.\n * Isinya publik: alamat backend yang dipanggil halaman Vercel (Tailscale Funnel). */\nwindow.SK_PUBLIC = {{\n    backendBase: {backend}\n}};\n"""


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
    PUBLIC_OUT.write_text(
        PUBLIC_TEMPLATE.format(backend=json.dumps(backend)), encoding="utf-8"
    )

    print(f"[OK] {FIREBASE_OUT.relative_to(ROOT_DIR)} ditulis.")
    print(f"[OK] {PUBLIC_OUT.relative_to(ROOT_DIR)} ditulis.")

    empty = [key for key, value in values.items() if not value]
    if empty:
        print("[INFO] Firebase masih kosong: " + ", ".join(empty) + ".")
        print("[INFO] Frontend tetap berjalan pada mode publik (tanpa login).")
    if not backend:
        print("[INFO] PUBLIC_BACKEND_URL kosong: halaman Vercel tidak tahu alamat backend.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
