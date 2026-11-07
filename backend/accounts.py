"""CRUD akun operator: Firebase Auth (identitas) + RTDB (profil & peran).

Klien tidak pernah menulis RTDB. Semua perubahan lewat endpoint ``/api/akun``
yang memakai Admin SDK, sehingga rules RTDB boleh menolak seluruh akses klien.

Profil disimpan di ``<RTDB_ROOT>/akun/<uid>``:

    { nama, nip, username, email, peran, created_at, updated_at }
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

import auth
import firebase_init


class AccountError(Exception):
    """Kesalahan validasi/bisnis akun dengan status HTTP yang sesuai."""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


def _app():
    return firebase_init.init_firebase()


def _ref(*parts: str):
    from firebase_admin import db as fb_db

    root = os.environ.get("RTDB_ROOT", "cctv_data").strip("/")
    segments = [p.strip("/") for p in (root, *parts) if p and p.strip("/")]
    return fb_db.reference("/" + "/".join(segments), app=_app())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _text(value: Any, field: str, required: bool = False, max_len: int = 120) -> str:
    text = "" if value is None else str(value).strip()
    if required and not text:
        raise AccountError(f"{field} wajib diisi.")
    if len(text) > max_len:
        raise AccountError(f"{field} terlalu panjang (maks {max_len} karakter).")
    return text


def _email(value: Any) -> str:
    text = _text(value, "Email", required=True, max_len=160).lower()
    if "@" not in text or text.startswith("@") or text.endswith("@"):
        raise AccountError("Format email tidak valid.")
    return text


def _password(value: Any, required: bool) -> str:
    text = "" if value is None else str(value)
    if not text:
        if required:
            raise AccountError("Kata sandi wajib diisi.")
        return ""
    if len(text) < 6:
        raise AccountError("Kata sandi minimal 6 karakter.")
    return text


def _peran(value: Any, default: str = "visitor") -> str:
    text = str(value or default).strip().lower()
    if text not in auth.VALID_ROLES:
        raise AccountError("Peran harus admin, teknisi, atau visitor.")
    return text


def _profile(uid: str, raw: dict[str, Any] | None) -> dict[str, Any]:
    data = raw or {}
    return {
        "uid": uid,
        "nama": str(data.get("nama") or ""),
        "nip": str(data.get("nip") or ""),
        "username": str(data.get("username") or ""),
        "email": str(data.get("email") or ""),
        "peran": str(data.get("peran") or "visitor"),
        "created_at": str(data.get("created_at") or ""),
        "updated_at": str(data.get("updated_at") or ""),
    }


def list_accounts() -> list[dict[str, Any]]:
    data = _ref("akun").get() or {}
    if not isinstance(data, dict):
        return []
    items = [_profile(uid, raw) for uid, raw in data.items() if isinstance(raw, dict)]
    rank = {"admin": 0, "teknisi": 1, "visitor": 2}
    items.sort(key=lambda a: (rank.get(a["peran"], 9), a["nama"].lower()))
    return items


def get_account(uid: str) -> dict[str, Any]:
    raw = _ref("akun", uid).get()
    if not isinstance(raw, dict) or not raw:
        raise AccountError("Akun tidak ditemukan.", 404)
    return _profile(uid, raw)


def _unique(accounts: list[dict[str, Any]], field: str, value: str, skip_uid: str = "") -> None:
    if not value:
        return
    lowered = value.lower()
    for account in accounts:
        if account["uid"] == skip_uid:
            continue
        if str(account.get(field, "")).lower() == lowered:
            raise AccountError(f"{field.capitalize()} sudah dipakai akun lain.", 409)


def ensure_self_profile(uid: str, email: str, payload: Any) -> dict[str, Any]:
    """Buat profil sendiri saat pendaftaran; peran selalu visitor."""
    existing = _ref("akun", uid).get()
    if isinstance(existing, dict) and existing:
        return _profile(uid, existing)

    body = payload if isinstance(payload, dict) else {}
    nama = _text(body.get("nama") or email.split("@")[0], "Nama", required=True)
    nip = _text(body.get("nip"), "NIP", max_len=30)
    username = _text(body.get("username") or email.split("@")[0], "Username", max_len=40).lower()

    _unique(list_accounts(), "username", username)

    now = _now()
    profile = {
        "nama": nama,
        "nip": nip,
        "username": username,
        "email": email.lower(),
        "peran": "visitor",
        "created_at": now,
        "updated_at": now,
    }
    _ref("akun", uid).set(profile)
    return _profile(uid, profile)


def create_account(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise AccountError("Body harus berupa objek JSON.")

    from firebase_admin import auth as fb_auth

    nama = _text(payload.get("nama"), "Nama", required=True)
    nip = _text(payload.get("nip"), "NIP", max_len=30)
    email = _email(payload.get("email"))
    username = _text(payload.get("username") or email.split("@")[0], "Username", max_len=40).lower()
    password = _password(payload.get("password"), required=True)
    peran = _peran(payload.get("peran"))

    accounts = list_accounts()
    _unique(accounts, "username", username)
    _unique(accounts, "nip", nip)
    _unique(accounts, "email", email)

    try:
        record = fb_auth.create_user(
            email=email, password=password, display_name=nama, app=_app()
        )
    except fb_auth.EmailAlreadyExistsError as exc:
        raise AccountError("Email sudah terdaftar di Firebase Auth.", 409) from exc

    now = _now()
    profile = {
        "nama": nama,
        "nip": nip,
        "username": username,
        "email": email,
        "peran": peran,
        "created_at": now,
        "updated_at": now,
    }
    _ref("akun", record.uid).set(profile)
    return _profile(record.uid, profile)


def update_account(uid: str, payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise AccountError("Body harus berupa objek JSON.")

    from firebase_admin import auth as fb_auth

    current = get_account(uid)
    accounts = list_accounts()

    nama = _text(payload.get("nama", current["nama"]), "Nama", required=True)
    nip = _text(payload.get("nip", current["nip"]), "NIP", max_len=30)
    username = _text(payload.get("username", current["username"]), "Username", max_len=40).lower()
    peran = _peran(payload.get("peran", current["peran"]))

    _unique(accounts, "username", username, skip_uid=uid)
    _unique(accounts, "nip", nip, skip_uid=uid)

    admins = [a for a in accounts if a["peran"] == "admin"]
    if current["peran"] == "admin" and peran != "admin" and len(admins) <= 1:
        raise AccountError("Minimal harus ada satu Administrator.", 409)

    profile = {
        "nama": nama,
        "nip": nip,
        "username": username,
        "email": current["email"],
        "peran": peran,
        "created_at": current["created_at"] or _now(),
        "updated_at": _now(),
    }
    _ref("akun", uid).set(profile)

    password = _password(payload.get("password"), required=False)
    if password:
        try:
            fb_auth.update_user(uid, password=password, app=_app())
        except fb_auth.UserNotFoundError as exc:
            raise AccountError("Akun ada di profil tapi tidak ada di Firebase Auth.", 409) from exc

    auth.reset_cache()
    return _profile(uid, profile)


def delete_account(uid: str, requester_uid: str) -> dict[str, Any]:
    from firebase_admin import auth as fb_auth

    current = get_account(uid)
    if uid == requester_uid:
        raise AccountError("Tidak bisa menghapus akun yang sedang dipakai.", 409)

    admins = [a for a in list_accounts() if a["peran"] == "admin"]
    if current["peran"] == "admin" and len(admins) <= 1:
        raise AccountError("Minimal harus ada satu Administrator.", 409)

    _ref("akun", uid).delete()
    try:
        fb_auth.delete_user(uid, app=_app())
    except fb_auth.UserNotFoundError:
        pass  # profil yatim: tetap dianggap terhapus
    auth.reset_cache()
    return {"ok": True, "uid": uid}


def register_error_handlers(app) -> None:
    from flask import jsonify

    @app.errorhandler(AccountError)
    def _handle_account_error(error: AccountError):
        return jsonify(error=error.message), error.status
