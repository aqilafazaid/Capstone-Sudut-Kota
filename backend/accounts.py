"""CRUD akun operator: Firebase Auth (identitas) + RTDB (profil & peran).

Klien tidak pernah menulis RTDB. Semua perubahan lewat endpoint ``/api/akun``
yang memakai Admin SDK, sehingga rules RTDB boleh menolak seluruh akses klien.

Profil disimpan di ``<RTDB_ROOT>/akun/<uid>``:

    { nama, nip, username, email, peran, created_at, updated_at }

NIP tidak pernah diisi pengguna: selalu dibuat server saat akun dibuat
(``ADM-001``, ``TKS-001``, ``VST-001``) dan dibuat ulang setiap peran berubah.
Nilai ``nip`` di body permintaan diabaikan.
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from typing import Any

import auth
import firebase_init

NIP_PREFIX = {"admin": "ADM-", "teknisi": "TKS-", "visitor": "VST-"}
_NIP_AUTO_RE = re.compile(r"^(ADM|TKS|VST)-(\d{1,6})$", re.IGNORECASE)

# --- Akses fitur -----------------------------------------------------------
# Peran hanya menentukan nilai BAWAAN. Administrator bisa mengubah keempat
# sakelar untuk akun mana pun, termasuk memberi fitur yang tidak lazim untuk
# perannya (mis. Visitor dengan Command Center). Konsekuensinya `akses` adalah
# sumber kebenaran otorisasi fitur; peran tidak lagi memotong nilainya.
FEATURES = ("cctv", "statistik", "dashboard", "ai", "akun")
ROLE_FEATURES = {
    "admin": frozenset(FEATURES),
    "teknisi": frozenset(("cctv", "statistik", "dashboard", "ai")),
    "visitor": frozenset(("cctv", "statistik")),
}


def default_akses(peran: str) -> dict[str, bool]:
    """Nilai bawaan sakelar untuk sebuah peran."""
    allowed = ROLE_FEATURES.get(peran, ROLE_FEATURES["visitor"])
    return {feature: feature in allowed for feature in FEATURES}


def effective_akses(peran: str, raw: Any = None) -> dict[str, bool]:
    """Akses efektif sebuah akun: bawaan peran, lalu ditimpa `raw`.

    Kunci yang tidak ada memakai bawaan peran, sehingga akun lama tanpa field
    ``akses`` berperilaku seperti sebelumnya. Hanya boolean yang dianggap
    keputusan eksplisit; nilai lain (``null``, string) diabaikan agar kiriman
    setengah jadi tidak diam-diam mengubah akses.
    """
    result = default_akses(peran)
    data = raw if isinstance(raw, dict) else {}
    for feature in FEATURES:
        value = data.get(feature)
        if isinstance(value, bool):
            result[feature] = value
    return result


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


def _nip_prefix(peran: str) -> str:
    return NIP_PREFIX.get(peran, NIP_PREFIX["visitor"])


def _auto_nip(peran: str, accounts: list[dict[str, Any]]) -> str:
    """NIP berikutnya untuk peran: nomor urut terpisah per awalan."""
    prefix = _nip_prefix(peran)
    highest = 0
    for account in accounts:
        match = _NIP_AUTO_RE.match(str(account.get("nip") or "").strip())
        if match and match.group(1).upper() == prefix.rstrip("-"):
            highest = max(highest, int(match.group(2)))
    return f"{prefix}{highest + 1:03d}"


def _profile(uid: str, raw: dict[str, Any] | None) -> dict[str, Any]:
    data = raw or {}
    peran = str(data.get("peran") or "visitor")
    return {
        "uid": uid,
        "nama": str(data.get("nama") or ""),
        "nip": str(data.get("nip") or ""),
        "username": str(data.get("username") or ""),
        "email": str(data.get("email") or ""),
        "peran": peran,
        "akses": effective_akses(peran, data.get("akses")),
        "created_at": str(data.get("created_at") or ""),
        "updated_at": str(data.get("updated_at") or ""),
        "deleted_at": str(data.get("deleted_at") or ""),
        "dihapus": bool(data.get("deleted_at")),
    }


def list_accounts(include_deleted: bool = False, only_deleted: bool = False) -> list[dict[str, Any]]:
    data = _ref("akun").get() or {}
    if not isinstance(data, dict):
        return []
    items = [_profile(uid, raw) for uid, raw in data.items() if isinstance(raw, dict)]
    if only_deleted:
        items = [item for item in items if item["dihapus"]]
    elif not include_deleted:
        items = [item for item in items if not item["dihapus"]]
    rank = {"admin": 0, "teknisi": 1, "visitor": 2}
    items.sort(key=lambda a: (rank.get(a["peran"], 9), a["nama"].lower()))
    return items


def get_account(uid: str, include_deleted: bool = True) -> dict[str, Any]:
    raw = _ref("akun", uid).get()
    if not isinstance(raw, dict) or not raw:
        raise AccountError("Akun tidak ditemukan.", 404)
    profile = _profile(uid, raw)
    if profile["dihapus"] and not include_deleted:
        raise AccountError("Akun berada di tempat sampah.", 404)
    return profile


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
    """Buat profil sendiri saat pendaftaran; peran selalu visitor.

    ``peran`` dan ``nip`` dari body diabaikan: pendaftaran mandiri tidak boleh
    menaikkan hak akses maupun memilih NIP. Hanya Administrator yang bisa
    membuat akun ``admin``/``teknisi`` (lewat ``POST /api/akun``).
    """
    existing = _ref("akun", uid).get()
    if isinstance(existing, dict) and existing:
        profile = _profile(uid, existing)
        if profile["dihapus"]:
            raise AccountError("Akun ini dinonaktifkan Administrator.", 403)
        return profile

    body = payload if isinstance(payload, dict) else {}
    nama = _text(body.get("nama") or email.split("@")[0], "Nama", required=True)
    username = _text(body.get("username") or email.split("@")[0], "Username", max_len=40).lower()

    accounts = list_accounts(include_deleted=True)
    _unique(accounts, "username", username)

    now = _now()
    profile = {
        "nama": nama,
        "nip": _auto_nip("visitor", accounts),
        "username": username,
        "email": email.lower(),
        "peran": "visitor",
        "akses": effective_akses("visitor"),
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
    email = _email(payload.get("email"))
    username = _text(payload.get("username") or email.split("@")[0], "Username", max_len=40).lower()
    password = _password(payload.get("password"), required=True)
    peran = _peran(payload.get("peran"))

    accounts = list_accounts(include_deleted=True)
    _unique(accounts, "username", username)
    _unique(accounts, "email", email)
    nip = _auto_nip(peran, accounts)
    _unique(accounts, "nip", nip)

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
        "akses": effective_akses(peran, payload.get("akses")),
        "created_at": now,
        "updated_at": now,
    }
    try:
        _ref("akun", record.uid).set(profile)
    except Exception as exc:
        # Jangan tinggalkan user Auth tanpa profil: akun seperti itu tidak bisa
        # dipakai tetapi tetap bisa login dan memicu 404 berulang.
        try:
            fb_auth.delete_user(record.uid, app=_app())
        except Exception:
            pass
        raise AccountError(
            "Gagal menyimpan profil akun; pembuatan akun dibatalkan.", 500
        ) from exc
    return _profile(record.uid, profile)


def update_account(uid: str, payload: Any, requester_uid: str = "") -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise AccountError("Body harus berupa objek JSON.")

    from firebase_admin import auth as fb_auth

    current = get_account(uid)
    if current["dihapus"]:
        raise AccountError("Akun ada di tempat sampah. Pulihkan dulu sebelum diubah.", 409)
    accounts = list_accounts(include_deleted=True)

    nama = _text(payload.get("nama", current["nama"]), "Nama", required=True)
    username = _text(payload.get("username", current["username"]), "Username", max_len=40).lower()
    peran = _peran(payload.get("peran", current["peran"]))

    # NIP selalu turunan peran: dibuat ulang saat peran berubah (atau belum punya).
    nip = current["nip"]
    if peran != current["peran"] or not nip:
        nip = _auto_nip(peran, accounts)

    _unique(accounts, "username", username, skip_uid=uid)
    _unique(accounts, "nip", nip, skip_uid=uid)

    admins = [a for a in list_accounts() if a["peran"] == "admin"]
    if current["peran"] == "admin" and peran != "admin" and len(admins) <= 1:
        raise AccountError("Minimal harus ada satu Administrator.", 409)

    # `akses` yang tidak dikirim mempertahankan nilai sekarang; kiriman parsial
    # digabung supaya satu sakelar tidak menghapus sakelar lain. Peran yang
    # berubah tanpa `akses` eksplisit kembali ke bawaan peran baru — sama
    # dengan perilaku modal (mengubah peran mereset sakelar).
    incoming = payload.get("akses")
    if isinstance(incoming, dict):
        merged = dict(current.get("akses") or {})
        merged.update({k: v for k, v in incoming.items() if k in FEATURES})
    elif peran != current["peran"]:
        merged = {}
    else:
        merged = dict(current.get("akses") or {})
    akses = effective_akses(peran, merged)

    # Administrator yang mencabut akses Kelola Akun miliknya sendiri akan
    # terkunci: halaman satu-satunya untuk memperbaikinya ikut hilang.
    if uid == requester_uid and not akses["akun"]:
        raise AccountError(
            "Akses Kelola Akun tidak bisa dicabut dari akun yang sedang dipakai.", 409
        )

    profile = {
        "nama": nama,
        "nip": nip,
        "username": username,
        "email": current["email"],
        "peran": peran,
        "akses": akses,
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


def _guard_delete(uid: str, requester_uid: str) -> dict[str, Any]:
    """Aturan bersama hapus akun (soft & permanen)."""
    current = get_account(uid)
    if uid == requester_uid:
        raise AccountError("Tidak bisa menghapus akun yang sedang dipakai.", 409)

    admins = [a for a in list_accounts() if a["peran"] == "admin"]
    if current["peran"] == "admin" and len(admins) <= 1:
        raise AccountError("Minimal harus ada satu Administrator.", 409)
    return current


def soft_delete_account(uid: str, requester_uid: str) -> dict[str, Any]:
    """Pindahkan akun ke tempat sampah: profil tetap, login dinonaktifkan.

    Identitas Firebase tidak dihapus, hanya ``disabled=True``, sehingga
    restore tidak perlu membuat ulang akun (dan NIP/riwayatnya tetap).
    """
    from firebase_admin import auth as fb_auth

    current = _guard_delete(uid, requester_uid)
    if current["dihapus"]:
        return current

    try:
        fb_auth.update_user(uid, disabled=True, app=_app())
    except fb_auth.UserNotFoundError:
        pass  # profil yatim tanpa identitas: tetap ditandai
    except Exception as exc:
        raise AccountError(
            "Gagal menonaktifkan identitas Firebase; akun tidak diubah.", 502
        ) from exc

    now = _now()
    _ref("akun", uid).update({"deleted_at": now, "updated_at": now})
    auth.reset_cache()
    return get_account(uid)


def restore_account(uid: str) -> dict[str, Any]:
    """Aktifkan kembali akun dari tempat sampah."""
    from firebase_admin import auth as fb_auth

    current = get_account(uid)
    if not current["dihapus"]:
        return current

    try:
        fb_auth.update_user(uid, disabled=False, app=_app())
    except fb_auth.UserNotFoundError as exc:
        raise AccountError(
            "Identitas Firebase akun ini sudah tidak ada; pakai hapus permanen.", 409
        ) from exc
    except Exception as exc:
        raise AccountError("Gagal mengaktifkan kembali identitas Firebase.", 502) from exc

    _ref("akun", uid).update({"deleted_at": None, "updated_at": _now()})
    auth.reset_cache()
    return get_account(uid)


def delete_account(uid: str, requester_uid: str) -> dict[str, Any]:
    """Hapus permanen: hanya untuk akun yang sudah di tempat sampah."""
    from firebase_admin import auth as fb_auth

    current = _guard_delete(uid, requester_uid)
    if not current["dihapus"]:
        raise AccountError(
            "Akun belum di tempat sampah. Hapus dulu (soft delete), baru hapus permanen.", 409
        )

    # Identitas dihapus lebih dulu. Bila penghapusan profil gagal setelahnya,
    # yang tersisa hanyalah profil tanpa akses login — bukan akun Auth yatim
    # yang masih bisa dipakai.
    try:
        fb_auth.delete_user(uid, app=_app())
    except fb_auth.UserNotFoundError:
        pass  # profil yatim: lanjut hapus profilnya
    except Exception as exc:
        raise AccountError(
            "Gagal menghapus identitas Firebase; profil dipertahankan.", 502
        ) from exc

    _ref("akun", uid).delete()
    auth.reset_cache()
    return {"ok": True, "uid": uid, "permanent": True}


def register_error_handlers(app) -> None:
    from flask import jsonify

    @app.errorhandler(AccountError)
    def _handle_account_error(error: AccountError):
        return jsonify(error=error.message), error.status
