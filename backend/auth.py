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

# --- Akses fitur -----------------------------------------------------------
# Sama dengan model di accounts.py: peran adalah batas atas, `akses` per akun
# hanya boleh mempersempit. Endpoint tulis memakai require_feature() supaya
# sakelar di halaman Kelola Akun benar-benar menutup API, bukan hanya menu.
FEATURES = ("cctv", "statistik", "dashboard", "ai", "akun")
FEATURE_LABEL = {
    "cctv": "CCTV Live",
    "statistik": "Statistik",
    "dashboard": "Command Center",
    "ai": "Kontrol Modul AI",
    "akun": "Kelola Akun",
}
ROLE_FEATURES = {
    "admin": frozenset(FEATURES),
    "teknisi": frozenset(("cctv", "statistik", "dashboard", "ai")),
    "visitor": frozenset(("cctv", "statistik")),
}

_lock = threading.Lock()
_profile_cache: dict[str, tuple[dict[str, Any], float]] = {}

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
        _profile_cache.clear()


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


def default_akses(peran: str) -> dict[str, bool]:
    """Nilai bawaan sakelar untuk sebuah peran."""
    allowed = ROLE_FEATURES.get(peran, ROLE_FEATURES["visitor"])
    return {feature: feature in allowed for feature in FEATURES}


def _merge_akses(peran: str, raw: Any) -> dict[str, bool]:
    """Bawaan peran yang ditimpa boolean eksplisit dari profil."""
    result = default_akses(peran)
    data = raw if isinstance(raw, dict) else {}
    for feature in FEATURES:
        value = data.get(feature)
        if isinstance(value, bool):
            result[feature] = value
    return result


def feature_allows(peran: str, akses: Any, feature: str) -> bool:
    """Nilai `akses` akun; bila tidak ada, jatuh ke bawaan peran.

    Peran bukan lagi pemotong: Administrator boleh memberi fitur apa pun ke
    akun mana pun. Bawaan peran hanya mengisi kunci yang tidak diset.
    """
    data = akses if isinstance(akses, dict) else {}
    value = data.get(feature)
    if isinstance(value, bool):
        return value
    return feature in ROLE_FEATURES.get(peran, ROLE_FEATURES["visitor"])


def _state_of(uid: str) -> dict[str, Any]:
    """Peran + akses efektif satu akun, dengan cache singkat.

    Satu pembacaan RTDB per TTL untuk keduanya; kegagalan baca selalu
    menghasilkan ``visitor`` tanpa akses tambahan (jangan pernah menaikkan
    hak saat sumber tidak bisa dipastikan).
    """
    if _role_resolver is not None:
        peran = _role_resolver(uid)
        return {"peran": peran, "akses": default_akses(peran)}

    now = time.time()
    with _lock:
        cached = _profile_cache.get(uid)
    if cached and now - cached[1] < ROLE_CACHE_TTL:
        return dict(cached[0])

    peran = "visitor"
    raw_akses: Any = None
    dihapus = False
    try:
        from firebase_admin import db as fb_db

        raw = fb_db.reference(_rtdb_path("akun", uid), app=_app()).get() or {}
        data: dict[str, Any] = raw if isinstance(raw, dict) else {}
        candidate = str(data.get("peran") or "").strip().lower()
        if candidate in VALID_ROLES:
            peran = candidate
        raw_akses = data.get("akses")
        dihapus = bool(data.get("deleted_at"))
    except Exception:
        peran = "visitor"
        raw_akses = None
        dihapus = False

    state = {
        "peran": peran,
        "akses": _merge_akses(peran, raw_akses),
        "dihapus": dihapus,
    }
    with _lock:
        _profile_cache[uid] = (state, now)
    return dict(state)


def role_of(uid: str) -> str:
    """Peran operator dari RTDB, dengan cache singkat."""
    return str(_state_of(uid)["peran"])


def akses_of(uid: str) -> dict[str, bool]:
    """Akses fitur efektif akun (gabungan peran + `akses` tersimpan)."""
    return dict(_state_of(uid)["akses"])


def is_deleted(uid: str) -> bool:
    """True bila profil akun ditandai di tempat sampah (soft delete)."""
    return bool(_state_of(uid).get("dihapus"))


def profile_of(uid: str) -> dict[str, Any] | None:
    """Profil publik ``/akun/<uid>`` atau ``None`` bila belum ada."""
    try:
        from firebase_admin import db as fb_db

        data = fb_db.reference(_rtdb_path("akun", uid), app=_app()).get()
    except Exception:
        return None
    if not isinstance(data, dict) or not data:
        return None
    peran = role_of(uid)
    return {
        "uid": uid,
        "nama": str(data.get("nama") or ""),
        "nip": str(data.get("nip") or ""),
        "username": str(data.get("username") or ""),
        "peran": peran,
        "akses": akses_of(uid),
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

    # Akun di tempat sampah tidak boleh memakai API walau tokennya belum
    # kedaluwarsa (±1 jam). Pemeriksaan ini memakai cache profil yang sama.
    if is_deleted(uid):
        raise AuthError("Akun ini dinonaktifkan (di tempat sampah).", 403)

    return {
        "uid": uid,
        "email": str(claims.get("email") or ""),
        "peran": role_of(uid),
        "akses": akses_of(uid),
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


def require_feature(feature: str):
    """Decorator: token valid + fitur dibuka untuk akun ini.

    Hanya `akses` akun yang menentukan (bawaan peran dipakai bila kunci tidak
    diset). Administrator bisa memberi fitur apa pun lewat halaman Kelola Akun,
    jadi tidak ada pemeriksaan peran tambahan di sini.
    """
    label = FEATURE_LABEL.get(feature, feature)

    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            user = authenticate(required=True)
            if user is None:  # tidak mungkin: required=True selalu mengembalikan user
                raise AuthError("Token tidak valid.", 401)

            if not feature_allows(user["peran"], user.get("akses"), feature):
                raise AuthError(f"Fitur '{label}' tidak diaktifkan untuk akun ini.", 403)

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
