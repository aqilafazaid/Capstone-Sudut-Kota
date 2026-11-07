"""Audit akun Firebase Auth vs profil RTDB.

Mendeteksi dua jenis akun "nyangkut":

- **Auth yatim** — user Firebase Auth tanpa profil ``<RTDB_ROOT>/akun/<uid>``.
  Bisa login tetapi tidak punya peran (selalu ditolak halaman).
- **Profil yatim** — profil RTDB tanpa user Auth. Tidak bisa login, tetapi
  datanya bisa membingungkan (mis. NIP/email terpakai).

Bawaan hanya melaporkan (dry-run). Tambahkan ``--apply`` untuk menghapus.

    cd backend
    .venv/Scripts/python.exe scripts/audit_accounts.py
    .venv/Scripts/python.exe scripts/audit_accounts.py --apply
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import firebase_init  # noqa: E402


def _app():
    return firebase_init.init_firebase()


def _ref(*parts: str):
    from firebase_admin import db as fb_db

    root = os.environ.get("RTDB_ROOT", "cctv_data").strip("/") or "cctv_data"
    segments = [root, *[p.strip("/") for p in parts if p and p.strip("/")]]
    return fb_db.reference("/" + "/".join(segments), app=_app())


def list_auth_users() -> list[dict]:
    from firebase_admin import auth as fb_auth

    rows = []
    page = fb_auth.list_users(app=_app())
    while page:
        for user in page.users:
            rows.append(
                {
                    "uid": user.uid,
                    "email": user.email or "",
                    "nama": user.display_name or "",
                    "disabled": bool(user.disabled),
                    "last_sign_in": user.user_metadata.last_sign_in_timestamp,
                }
            )
        page = page.get_next_page()
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit akun Sudut Kota.")
    parser.add_argument("--apply", action="store_true", help="hapus yang yatim")
    args = parser.parse_args()

    missing = firebase_init.missing_keys()
    if missing:
        print("[ERROR] Kunci Admin SDK belum lengkap: " + ", ".join(missing))
        return 1

    users = list_auth_users()
    profiles = _ref("akun").get() or {}
    if not isinstance(profiles, dict):
        profiles = {}

    auth_uids = {row["uid"] for row in users}
    profile_uids = set(profiles)

    auth_orphans = [row for row in users if row["uid"] not in profile_uids]
    profile_orphans = sorted(profile_uids - auth_uids)

    print(f"Auth users      : {len(users)}")
    print(f"Profil RTDB     : {len(profiles)}")
    print(f"Auth yatim      : {len(auth_orphans)}")
    for row in auth_orphans:
        print(f"  - {row['email'] or '(tanpa email)'} | uid={row['uid']} | disabled={row['disabled']}")
    print(f"Profil yatim    : {len(profile_orphans)}")
    for uid in profile_orphans:
        data = profiles.get(uid) or {}
        print(f"  - {data.get('email', '')} | peran={data.get('peran', '')} | uid={uid}")

    if not auth_orphans and not profile_orphans:
        print("[OK] Tidak ada akun nyangkut.")
        return 0

    if not args.apply:
        print("\nDry-run: jalankan ulang dengan --apply untuk menghapus.")
        return 0

    from firebase_admin import auth as fb_auth

    for row in auth_orphans:
        try:
            fb_auth.delete_user(row["uid"], app=_app())
            print(f"[HAPUS] Auth yatim {row['email'] or row['uid']}")
        except Exception as exc:
            print(f"[GAGAL] Auth {row['uid']}: {type(exc).__name__}: {exc}")
    for uid in profile_orphans:
        try:
            _ref("akun", uid).delete()
            print(f"[HAPUS] Profil yatim {uid}")
        except Exception as exc:
            print(f"[GAGAL] Profil {uid}: {type(exc).__name__}: {exc}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
