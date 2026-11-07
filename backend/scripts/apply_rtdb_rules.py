"""Terapkan Realtime Database rules dari scripts/rtdb-rules.json.

Semua akses data lewat backend (Admin SDK), jadi aturan paling aman adalah
menolak seluruh akses klien. Jalankan dari folder backend:

    python scripts/apply_rtdb_rules.py            # terapkan
    python scripts/apply_rtdb_rules.py --show     # baca aturan yang aktif

Skrip ini mengubah konfigurasi keamanan project Firebase. Pastikan itu memang
yang diinginkan sebelum menjalankannya.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from urllib.request import Request, urlopen

import google.auth.transport.requests

import firebase_init

RULES_FILE = Path(__file__).resolve().parent / "rtdb-rules.json"
SCOPES = [
    "https://www.googleapis.com/auth/firebase.database",
    "https://www.googleapis.com/auth/cloud-platform",
]


def _access_token() -> str:
    app = firebase_init.init_firebase()
    cred = app.credential.get_credential()
    cred = cred.with_scopes(SCOPES)
    cred.refresh(google.auth.transport.requests.Request())
    return cred.token


def _url(secret: bool = False) -> str:
    base = os.environ["FIREBASE_DATABASE_URL"].rstrip("/")
    return f"{base}/.settings/rules.json"


def main() -> int:
    missing = firebase_init.missing_keys()
    if missing:
        print("[ERROR] Kunci Admin SDK belum lengkap: " + ", ".join(missing))
        return 1

    token = _access_token()
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    if "--show" in sys.argv:
        with urlopen(Request(_url(), headers=headers), timeout=15) as response:
            print(json.dumps(json.loads(response.read().decode("utf-8")), indent=2))
        return 0

    rules = json.loads(RULES_FILE.read_text(encoding="utf-8"))
    body = json.dumps(rules).encode("utf-8")
    with urlopen(Request(_url(), data=body, headers=headers, method="PUT"), timeout=15) as response:
        print(f"[OK] rules diterapkan (HTTP {response.status}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
