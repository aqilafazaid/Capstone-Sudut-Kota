"""Sinkronkan Firebase Web SDK config dari backend/.env ke frontend/js/firebase-config.js.

Nilai Firebase Web SDK bersifat publik (bukan rahasia). `.env` dipakai sebagai
sumber tunggal supaya nilai yang sama tidak perlu diketik dua kali:

    python backend/scripts/sync_firebase_config.py

Kunci Admin SDK / service account tidak pernah ditulis ke file ini.
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
OUT_FILE = ROOT_DIR / "frontend" / "js" / "firebase-config.js"

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

TEMPLATE = """/**
 * Dihasilkan oleh backend/scripts/sync_firebase_config.py.
 * Jangan edit manual: ubah backend/.env lalu jalankan ulang skrip itu.
 *
 * Hanya berisi kunci PUBLIK Firebase Web SDK. Kunci Admin SDK / service
 * account tidak pernah masuk ke file ini.
 */
window.FIREBASE_CONFIG = {{
{body}
}};

window.FIREBASE_READY = (function (cfg) {{
  var required = ['apiKey', 'authDomain', 'databaseURL', 'projectId', 'appId'];
  return required.every(function (key) {{
    return String(cfg[key] || '').trim() !== '';
  }});
}})(window.FIREBASE_CONFIG);
"""


def main() -> int:
    if not ENV_FILE.exists():
        print(f"[ERROR] {ENV_FILE} tidak ditemukan. Salin dari .env.example.")
        return 1

    # override=True: .env adalah sumber kebenaran, bukan variabel shell yang kebetulan ada.
    load_dotenv(ENV_FILE, override=True)
    values = {key: os.environ.get(env_key, "").strip() for key, env_key in FIELDS}

    body = ",\n".join(f"  {key}: {json.dumps(value)}" for key, value in values.items())
    OUT_FILE.write_text(TEMPLATE.format(body=body), encoding="utf-8")

    empty = [key for key, value in values.items() if not value]
    print(f"[OK] {OUT_FILE} ditulis.")
    if empty:
        print("[INFO] Masih kosong: " + ", ".join(empty) + ".")
        print("[INFO] Frontend tetap memakai lapisan demo sampai apiKey diisi.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
