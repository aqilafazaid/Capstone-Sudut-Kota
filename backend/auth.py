"""Verifikasi Firebase ID token dan peran operator.

Kontrak:

- Peramban mengirim ``Authorization: Bearer <idToken>`` pada request tulis.
- Token diverifikasi Admin SDK; UID dipakai untuk membaca peran di
  ``<RTDB_ROOT>/akun/<uid>/peran`` (cache 60 detik).
- Peran yang dikenal hanya ``admin``, ``teknisi``, ``visitor``; nilai lain
  diperlakukan ``visitor``.

Bila kredensial Admin SDK belum lengkap, modul ini **tidak** menggagalkan
import: endpoint baca tetap jalan, endpoint yang butuh auth membalas 503
supaya tidak terbaca sebagai "token salah".
"""

from __future__ import annotations

import os
import threading
import time
from functools import wraps
from typing import Any, Callable

from flask import g, jsonify, request

import firebase_init

ROLE_CACHE_TTL = 60
VALID_ROLES = ("admin", "teknisi", "visitor")
WRITE_ROLES = ("admin", "teknisi")

_lock = threading.Lock()
_role_cache: dict[str, tuple[str, float]] = {}

# Titik suntik untuk tes: tidak ada token Firebase sungguhan saat unit test.
_verifier: Callable[[str], dict[str, Any]] | None = None
_role_resolver: Callable[[str], str] | None = None


class AuthError(Exception):
    """Kegagalan autentikasi/otorisasi dengan status HTTP yang sesuai."""

    def __init__(self, message: str, status: int = 401) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


def set_verifier(verifier: Callable[[str], dict[str, Any]] | None) -> None:
    """Ganti verifikasi token (dipakai tes). ``None`` mengembalikan perilaku asli."""
    global _verifier
    _verifier = verifier


def set_role_resolver(resolver: Callable[[str], str] | None) -> None:
    """Ganti pembacaan peran (dipakai tes)."""
    global _role_resolver
    _role_resolver = resolver


def reset_cache() -> None:
    with _lock:
        _role_cache.clear()


def configured() -> bool:
    """True bila seluruh kunci Admin SDK sudah terisi."""
    return not firebase_init.missing_keys()


def _rtdb_path(*parts: str) -> str:
    root = os.environ.get("RTDB_ROOT", "cctv_data").strip("/")
    segments = [p.strip("/") for p in (root, *parts) if p and p.strip("/")]
    return "/" + "/".join(segments)


def _app():
    return firebase_init.init_firebase()


def _decode(token: str) -> dict[str, Any]:
    if _verifier is not None:
        return _verifier(token)
    from firebase_admin import auth as fb_auth

    return fb_auth.verify_id_token(token, app=_app(), check_revoked=False)


def role_of(uid: str) -> str:
    """Peran operator dari RTDB, dengan cache singkat."""
    if _role_resolver is not None:
        return _role_resolver(uid)

    now = time.time()
    with _lock:
        cached = _role_cache.get(uid)
    if cached and now - cached[1] < ROLE_CACHE_TTL:
        return cached[0]

    peran = "visitor"
    try:
        from firebase_admin import db as fb_db

        data = fb_db.reference(_rtdb_path("akun", uid), app=_app()).get() or {}
        candidate = str(data.get("peran") or "").strip().lower()
        if candidate in VALID_ROLES:
            peran = candidate
    except Exception:
        # RTDB tidak terjangkau: jangan pernah menaikkan hak akses.
        peran = "visitor"

    with _lock:
        _role_cache[uid] = (peran, now)
    return peran


def profile_of(uid: str) -> dict[str, Any] | None:
    """Profil publik ``/akun/<uid>`` atau ``None`` bila belum ada."""
    try:
        from firebase_admin import db as fb_db

        data = fb_db.reference(_rtdb_path("akun", uid), app=_app()).get()
    except Exception:
        return None
    if not isinstance(data, dict) or not data:
        return None
    return {
        "uid": uid,
        "nama": str(data.get("nama") or ""),
        "nip": str(data.get("nip") or ""),
        "username": str(data.get("username") or ""),
        "peran": role_of(uid),
    }


def authenticate(required: bool = True) -> dict[str, Any] | None:
    """Baca dan verifikasi header Authorization."""
    header = request.headers.get("Authorization", "").strip()
    if not header.lower().startswith("bearer "):
        if not required:
            return None
        raise AuthError("Header Authorization: Bearer <idToken> wajib diisi.", 401)

    token = header[7:].strip()
    if not token:
        raise AuthError("Token kosong.", 401)

    if _verifier is None and not configured():
        missing = ", ".join(firebase_init.missing_keys())
        raise AuthError(
            f"Backend belum dikonfigurasi untuk Firebase Auth. Variabel kurang: {missing}.",
            503,
        )

    try:
        claims = _decode(token)
    except AuthError:
        raise
    except Exception as exc:  # token kedaluwarsa, salah tanda tangan, bukan token
        raise AuthError(f"Token tidak valid: {type(exc).__name__}.", 401) from exc

    uid = str(claims.get("uid") or claims.get("sub") or "").strip()
    if not uid:
        raise AuthError("Token tidak memuat uid.", 401)

    return {
        "uid": uid,
        "email": str(claims.get("email") or ""),
        "peran": role_of(uid),
    }


def require_role(*roles: str):
    """Decorator: butuh token valid dan (bila diisi) salah satu peran."""
    allowed = tuple(roles)

    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            user = authenticate(required=True)
            if user is None:  # tidak mungkin: required=True selalu mengembalikan user
                raise AuthError("Token tidak valid.", 401)
            if allowed and user["peran"] not in allowed:
                raise AuthError(
                    f"Peran '{user['peran']}' tidak diizinkan untuk aksi ini.", 403
                )
            g.user = user
            return view(*args, **kwargs)

        return wrapper

    return decorator


def register_error_handlers(app) -> None:
    @app.errorhandler(AuthError)
    def _handle_auth_error(error: AuthError):
        response = jsonify(error=error.message)
        response.status_code = error.status
        if error.status == 401:
            response.headers["WWW-Authenticate"] = "Bearer"
        return response
