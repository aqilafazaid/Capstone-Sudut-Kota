"""Buat akun operator pertama lewat Admin SDK.

Dipakai sekali saat bootstrap, atau saat menambah akun tanpa membuka dashboard:

    cd backend
    python scripts/seed_accounts.py --email admin@sudutkota.go.id --nama "Admin Dishub" --peran admin

Kata sandi ditanyakan lewat prompt (tidak pernah masuk riwayat shell).
Akun hanya dibuat bila email belum terdaftar.
"""

from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import accounts  # noqa: E402
import auth  # noqa: E402
import firebase_init  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Buat akun operator Sudut Kota.")
    parser.add_argument("--email", required=True)
    parser.add_argument("--nama", required=True)
    parser.add_argument("--peran", default="admin", choices=list(auth.VALID_ROLES))
    args = parser.parse_args()

    missing = firebase_init.missing_keys()
    if missing:
        print("[ERROR] Kunci Admin SDK belum lengkap: " + ", ".join(missing))
        return 1

    password = getpass.getpass("Kata sandi baru: ")
    if getpass.getpass("Ulangi kata sandi: ") != password:
        print("[ERROR] Kata sandi tidak sama.")
        return 1

    try:
        profile = accounts.create_account(
            {
                "nama": args.nama,
                "email": args.email,
                "peran": args.peran,
                "password": password,
            }
        )
    except accounts.AccountError as exc:
        print(f"[ERROR] {exc.message}")
        return 1

    print(f"[OK] Akun dibuat: {profile['email']} | peran={profile['peran']} | uid={profile['uid']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
