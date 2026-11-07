"""Inisialisasi Firebase Admin SDK dari variabel di backend/.env.

Dipakai bersama oleh app.py dan ai_engine/main_ai.py supaya kredensial tidak
diduplikasi dan file JSON service account tidak perlu ada di repo.
"""

from __future__ import annotations

import os
from pathlib import Path

import firebase_admin
from dotenv import load_dotenv
from firebase_admin import credentials

load_dotenv(Path(__file__).resolve().parent / ".env")

# Semua kunci yang dibutuhkan credentials.Certificate()
CRED_KEYS = [
    "FIREBASE_TYPE",
    "FIREBASE_PROJECT_ID",
    "FIREBASE_PRIVATE_KEY_ID",
    "FIREBASE_PRIVATE_KEY",
    "FIREBASE_CLIENT_EMAIL",
    "FIREBASE_CLIENT_ID",
    "FIREBASE_AUTH_URI",
    "FIREBASE_TOKEN_URI",
    "FIREBASE_AUTH_PROVIDER_X509_CERT_URL",
    "FIREBASE_CLIENT_X509_CERT_URL",
]


def missing_keys() -> list[str]:
    """Daftar variabel .env yang belum diisi (kosong bila lengkap)."""
    return [key for key in CRED_KEYS + ["FIREBASE_DATABASE_URL"] if not os.environ.get(key)]


def init_firebase():
    """Inisialisasi Admin SDK sekali saja; kredensial dibaca dari .env."""
    if firebase_admin._apps:
        return firebase_admin.get_app()

    missing = missing_keys()
    if missing:
        raise RuntimeError(
            "Konfigurasi Firebase belum lengkap di backend/.env: " + ", ".join(missing)
        )

    cred_dict = {
        "type": os.environ["FIREBASE_TYPE"],
        "project_id": os.environ["FIREBASE_PROJECT_ID"],
        "private_key_id": os.environ["FIREBASE_PRIVATE_KEY_ID"],
        # .env menyimpan newline sebagai teks "\n"; kembalikan jadi newline asli.
        "private_key": os.environ["FIREBASE_PRIVATE_KEY"].replace("\\n", "\n"),
        "client_email": os.environ["FIREBASE_CLIENT_EMAIL"],
        "client_id": os.environ["FIREBASE_CLIENT_ID"],
        "auth_uri": os.environ["FIREBASE_AUTH_URI"],
        "token_uri": os.environ["FIREBASE_TOKEN_URI"],
        "auth_provider_x509_cert_url": os.environ["FIREBASE_AUTH_PROVIDER_X509_CERT_URL"],
        "client_x509_cert_url": os.environ["FIREBASE_CLIENT_X509_CERT_URL"],
        "universe_domain": os.environ.get("FIREBASE_UNIVERSE_DOMAIN", "googleapis.com"),
    }

    return firebase_admin.initialize_app(
        credentials.Certificate(cred_dict),
        {"databaseURL": os.environ["FIREBASE_DATABASE_URL"]},
    )
