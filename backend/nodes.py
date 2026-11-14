"""Penyimpanan konfigurasi kamera di SQLite.

Node kamera sebelumnya hidup di `localStorage` frontend. Modul ini memindahkannya
ke backend supaya URL RTSP (yang biasanya memuat user:password) tidak pernah
dikirim ke peramban. Frontend hanya menerima `hls_url`; detail RTSP hanya
dikembalikan lewat endpoint yang dilindungi token tulis.

Berkas database ditentukan `NODE_DB` (default `backend/data/sudutkota.db`).
"""

from __future__ import annotations

import base64
import logging
import os
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from contextlib import contextmanager
from typing import Any

BASE_DIR = Path(__file__).resolve().parent
_DB_LOCK = threading.Lock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS nodes (
    id          TEXT PRIMARY KEY,
    channel     TEXT,
    nama        TEXT NOT NULL,
    zona        TEXT NOT NULL,
    jalan       TEXT,
    kota        TEXT,
    rtsp        TEXT NOT NULL,
    aktif       INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    deleted_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_nodes_zona ON nodes(zona);
CREATE UNIQUE INDEX IF NOT EXISTS idx_nodes_channel
    ON nodes(channel) WHERE channel IS NOT NULL AND channel <> '';
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

# Tidak ada node bawaan: direktori kamera diisi lewat Dashboard dan
# database baru selalu kosong.


class NodeError(Exception):
    """Kesalahan validasi/bisnis dengan status HTTP yang sesuai."""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


def _truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def allow_test_sources() -> bool:
    return _truthy(os.environ.get("ALLOW_TEST_SOURCES", "false"))


def db_path() -> Path:
    raw = os.environ.get("NODE_DB", "data/sudutkota.db").strip() or "data/sudutkota.db"
    path = Path(raw)
    return path if path.is_absolute() else BASE_DIR / path


def _connect() -> sqlite3.Connection:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def _db():
    """Koneksi pendek dengan commit/close eksplisit (contextmanager sqlite3
    hanya commit, tidak menutup koneksi)."""
    conn = _connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with _DB_LOCK, _db() as conn:
        conn.executescript(SCHEMA)
        # Database lama belum punya kolom soft delete; tambahkan di tempat
        # (SQLite tidak mendukung "ADD COLUMN IF NOT EXISTS").
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(nodes)")}
        if "deleted_at" not in columns:
            conn.execute("ALTER TABLE nodes ADD COLUMN deleted_at TEXT")
        try:
            conn.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS idx_nodes_channel "
                "ON nodes(channel) WHERE channel IS NOT NULL AND channel <> ''"
            )
        except sqlite3.IntegrityError:
            # Database lama bisa sudah punya channel ganda. Jangan gagalkan
            # start: validasi di create/update tetap menolak duplikat baru.
            print("[nodes] PERINGATAN: ada channel ganda; indeks unik tidak dibuat.")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _text(value: Any, field: str, required: bool = False, max_len: int = 255) -> str:
    text = "" if value is None else str(value).strip()
    if required and not text:
        raise NodeError(f"{field} wajib diisi.")
    if len(text) > max_len:
        raise NodeError(f"{field} terlalu panjang (maks {max_len} karakter).")
    return text


def _channel(value: Any) -> str:
    """Nomor channel kanonik: hanya digit, tanpa nol di depan.

    Kanal dipakai sebagai kunci RTDB ``cam_<channel>``; ``048`` dan ``48``
    menunjuk node yang sama, jadi keduanya harus disimpan sebagai ``48``.
    """
    raw_input = str(value or "").strip()
    raw = "".join(ch for ch in raw_input if ch.isdigit())
    if not raw:
        if raw_input:
            raise NodeError("Nomor channel harus berupa angka.")
        return ""
    if len(raw) > 6:
        raise NodeError("Nomor channel maksimal 6 digit.")
    return str(int(raw))


def validate_source(url: Any) -> str:
    """Validasi URL sumber. http(s) hanya bila ALLOW_TEST_SOURCES=true."""
    text = _text(url, "URL RTSP", required=True, max_len=2048)
    schemes = ("rtsp://", "rtsps://")
    if allow_test_sources():
        schemes += ("http://", "https://")
    if not text.lower().startswith(schemes):
        if allow_test_sources():
            raise NodeError("URL harus diawali rtsp://, rtsps://, http://, atau https://.")
        raise NodeError("URL harus diawali rtsp:// atau rtsps://.")
    return text


# --- URL RTSP di disk (AES-256-GCM) ----------------------------------------
# Kolom `rtsp` memuat user:password kamera, jadi nilainya tidak pernah ditulis
# apa adanya: setiap tulis menyimpannya sebagai "enc:v2:<base64(nonce+tag+ct)>".
# Kunci 32 byte diambil dari NODE_SECRET (base64/hex) atau dari berkas
# data/node_secret.key yang dibuat otomatis pada penulisan pertama. Tanpa
# kunci yang bisa dibaca, penulisan DITOLAK (bukan diam-diam jadi teks biasa).
# Baris lama yang masih teks biasa tetap terbaca, dan diubah oleh
# scripts/encrypt_rtsp.py.
_ENC_PREFIX = "enc:v2:"
_ENC_AAD = b"sudutkota:rtsp:v2"
_KEY_ENV = "NODE_SECRET"
_KEY_FILE = BASE_DIR / "data" / "node_secret.key"


def _aead():
    """AES-256-GCM dari `cryptography` (sudah menjadi dependensi firebase-admin)."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    return AESGCM


def _decode_key(raw: str) -> bytes | None:
    text = (raw or "").strip()
    if not text:
        return None
    for decoder in (base64.urlsafe_b64decode, base64.b64decode):
        try:
            key = decoder(text)
        except Exception:
            continue
        if len(key) == 32:
            return key
    try:
        key = bytes.fromhex(text)
    except ValueError:
        return None
    return key if len(key) == 32 else None


def key_origin() -> str:
    """Sumber kunci yang sedang dipakai: 'env', 'file', atau '' bila belum ada."""
    if _decode_key(os.environ.get(_KEY_ENV, "")):
        return "env"
    if _KEY_FILE.exists():
        try:
            if _decode_key(_KEY_FILE.read_text(encoding="ascii")):
                return "file"
        except OSError:
            return ""
    return ""


def _key_bytes(create: bool = False) -> bytes | None:
    key = _decode_key(os.environ.get(_KEY_ENV, ""))
    if key:
        return key

    if _KEY_FILE.exists():
        try:
            key = _decode_key(_KEY_FILE.read_text(encoding="ascii"))
        except OSError:
            key = None
        if key:
            return key
        logging.warning("Berkas kunci %s tidak berisi kunci 32-byte base64 yang sah.", _KEY_FILE)
        return None

    if not create:
        logging.warning(
            "Kunci AES-256 belum ada (%s atau NODE_SECRET): URL RTSP terenkripsi tidak bisa dibuka.",
            _KEY_FILE,
        )
        return None

    key = os.urandom(32)
    try:
        _KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
        _KEY_FILE.write_text(base64.urlsafe_b64encode(key).decode("ascii"), encoding="ascii")
    except OSError as exc:
        logging.error("Gagal membuat kunci AES-256 di %s: %s", _KEY_FILE, exc)
        return None
    logging.warning(
        "Kunci AES-256 dibuat di %s. Cadangkan berkas itu bersama database — "
        "tanpa kunci tersebut URL RTSP yang tersimpan tidak bisa dibuka.",
        _KEY_FILE,
    )
    return key


def protect_source(value: str) -> str:
    """Enkripsi URL RTSP dengan AES-256-GCM sebelum masuk SQLite.

    Tidak ada jalur "simpan sebagai teks biasa": bila kunci tidak tersedia,
    penulisan gagal supaya sandi kamera tidak pernah mendarat di disk.
    """
    if not value or value.startswith(_ENC_PREFIX):
        return value
    key = _key_bytes(create=True)
    if key is None:
        raise NodeError("Kunci enkripsi AES-256 tidak tersedia; URL RTSP tidak disimpan.", 500)
    nonce = os.urandom(12)
    blob = _aead()(key).encrypt(nonce, value.encode("utf-8"), _ENC_AAD)
    return _ENC_PREFIX + base64.urlsafe_b64encode(nonce + blob).decode("ascii")


def reveal_source(value: str) -> str:
    """Kembalikan URL RTSP asli; baris teks biasa (data lama) dilewatkan."""
    if not value:
        return value
    if not value.startswith(_ENC_PREFIX):
        if value.startswith("enc:"):
            logging.warning("Format enkripsi tidak dikenal (%s); isi ulang URL RTSP node ini.", value[:7])
            return ""
        return value
    key = _key_bytes(create=False)
    if key is None:
        return ""
    try:
        raw = base64.urlsafe_b64decode(value[len(_ENC_PREFIX):])
        if len(raw) <= 12 + 16:
            raise ValueError("blob terenkripsi terlalu pendek")
        return _aead()(key).decrypt(raw[:12], raw[12:], _ENC_AAD).decode("utf-8")
    except Exception as exc:
        logging.warning("Gagal mendekripsi URL RTSP (kunci berbeda atau data rusak): %s", exc)
        return ""


def _validate_payload(payload: Any, partial: bool = False) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise NodeError("Body harus berupa objek JSON.")

    data: dict[str, Any] = {}

    if not partial or "nama" in payload:
        data["nama"] = _text(payload.get("nama"), "Nama titik", required=True, max_len=120)
    if not partial or "zona" in payload:
        data["zona"] = _text(payload.get("zona"), "Zona wilayah", required=True, max_len=80)
    if not partial or "jalan" in payload:
        data["jalan"] = _text(payload.get("jalan"), "Nama jalan", max_len=160)
    if not partial or "channel" in payload:
        data["channel"] = _channel(payload.get("channel"))
    if not partial or "rtsp" in payload:
        data["rtsp"] = validate_source(payload.get("rtsp"))

    if "aktif" in payload:
        data["aktif"] = 1 if payload.get("aktif") else 0
    elif not partial:
        data["aktif"] = 1

    if "kota" in payload:
        data["kota"] = _text(payload.get("kota"), "Kota", max_len=80)
    elif "zona" in data:
        data["kota"] = data["zona"].upper()

    return data


def _deleted_at(row: sqlite3.Row) -> str:
    try:
        return str(row["deleted_at"] or "")
    except (IndexError, KeyError):
        return ""


def _row_public(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "channel": row["channel"] or "",
        "nama": row["nama"],
        "zona": row["zona"],
        "jalan": row["jalan"] or "",
        "kota": row["kota"] or "",
        "aktif": bool(row["aktif"]),
        "hls_url": f"/hls/{row['id']}/index.m3u8",
        "updated_at": row["updated_at"],
        "deleted_at": _deleted_at(row),
        "dihapus": bool(_deleted_at(row)),
    }


def _row_detail(row: sqlite3.Row) -> dict[str, Any]:
    data = _row_public(row)
    data["rtsp"] = reveal_source(row["rtsp"])
    data["created_at"] = row["created_at"]
    return data


def count_nodes(include_deleted: bool = False) -> int:
    query = "SELECT COUNT(*) FROM nodes" if include_deleted else "SELECT COUNT(*) FROM nodes WHERE deleted_at IS NULL"
    with _db() as conn:
        return int(conn.execute(query).fetchone()[0])


def list_nodes(include_deleted: bool = False, only_deleted: bool = False) -> list[dict[str, Any]]:
    """Daftar node. Default hanya yang tidak di tempat sampah."""
    if only_deleted:
        query = "SELECT * FROM nodes WHERE deleted_at IS NOT NULL ORDER BY deleted_at DESC"
    elif include_deleted:
        query = "SELECT * FROM nodes ORDER BY zona, nama"
    else:
        query = "SELECT * FROM nodes WHERE deleted_at IS NULL ORDER BY zona, nama"
    with _db() as conn:
        rows = conn.execute(query).fetchall()
    return [_row_public(row) for row in rows]


def get_node(node_id: str, include_rtsp: bool = True, allow_deleted: bool = True) -> dict[str, Any]:
    with _db() as conn:
        row = conn.execute("SELECT * FROM nodes WHERE id = ?", (node_id,)).fetchone()
    if row is None:
        raise NodeError("Node tidak ditemukan.", 404)
    if not allow_deleted and _deleted_at(row):
        raise NodeError("Node berada di tempat sampah.", 404)
    return _row_detail(row) if include_rtsp else _row_public(row)


def soft_delete_node(node_id: str) -> dict[str, Any]:
    """Pindahkan node ke tempat sampah (baris + RTSP dipertahankan).

    Hanya menandai `deleted_at`; data yang bersifat sementara (folder HLS,
    log engine, telemetri live) dibersihkan pemanggil. Statistik historis
    sengaja dipertahankan supaya restore tidak kehilangan riwayat.
    """
    now = _now()
    with _DB_LOCK, _db() as conn:
        row = conn.execute("SELECT * FROM nodes WHERE id = ?", (node_id,)).fetchone()
        if row is None:
            raise NodeError("Node tidak ditemukan.", 404)
        if not _deleted_at(row):
            conn.execute(
                "UPDATE nodes SET deleted_at = ?, updated_at = ? WHERE id = ?",
                (now, now, node_id),
            )
    return get_node(node_id)


def restore_node(node_id: str) -> dict[str, Any]:
    """Batalkan soft delete. Idempoten untuk node yang tidak di tempat sampah."""
    with _DB_LOCK, _db() as conn:
        row = conn.execute("SELECT * FROM nodes WHERE id = ?", (node_id,)).fetchone()
        if row is None:
            raise NodeError("Node tidak ditemukan.", 404)
        if _deleted_at(row):
            conn.execute(
                "UPDATE nodes SET deleted_at = NULL, updated_at = ? WHERE id = ?",
                (_now(), node_id),
            )
    return get_node(node_id)


def _new_id(payload: dict[str, Any], explicit: str | None) -> str:
    if explicit:
        candidate = str(explicit).strip()
        if not candidate:
            raise NodeError("ID node tidak valid.")
        return candidate
    digits = "".join(ch for ch in str(payload.get("channel") or "") if ch.isdigit())
    return f"cam_{digits}" if digits else f"cam_{uuid.uuid4().hex[:8]}"


def _insert(conn: sqlite3.Connection, data: dict[str, Any]) -> None:
    now = _now()
    conn.execute(
        """
        INSERT INTO nodes (id, channel, nama, zona, jalan, kota, rtsp, aktif, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            data["id"], data.get("channel", ""), data["nama"], data["zona"],
            data.get("jalan", ""), data.get("kota", ""), protect_source(data["rtsp"]),
            int(data.get("aktif", 1)), now, now,
        ),
    )


def _assert_channel_free(conn: sqlite3.Connection, channel: str, exclude_id: str = "") -> None:
    """Tolak channel yang sudah dipakai node lain — termasuk isi tempat sampah.

    Node di tempat sampah masih memiliki channel sampai dihapus permanen, jadi
    memakai channel itu sekarang akan bertabrakan saat node dipulihkan.
    """
    if not channel:
        return
    row = conn.execute(
        "SELECT id, deleted_at FROM nodes WHERE channel = ? AND id <> ? LIMIT 1",
        (channel, exclude_id or ""),
    ).fetchone()
    if row is None:
        return
    if _deleted_at(row):
        raise NodeError(
            f"Channel {channel} masih dipakai node {row['id']} di tempat sampah. "
            "Pulihkan atau hapus permanen dulu.",
            409,
        )
    raise NodeError(f"Channel {channel} sudah dipakai node {row['id']}.", 409)


def create_node(payload: Any, node_id: str | None = None) -> dict[str, Any]:
    data = _validate_payload(payload, partial=False)
    data["id"] = _new_id(data, node_id)

    with _DB_LOCK, _db() as conn:
        exists = conn.execute("SELECT deleted_at FROM nodes WHERE id = ?", (data["id"],)).fetchone()
        if exists is not None:
            if _deleted_at(exists):
                raise NodeError(
                    f"Node {data['id']} ada di tempat sampah. Pulihkan atau hapus permanen dulu.",
                    409,
                )
            raise NodeError(f"Node {data['id']} sudah ada.", 409)
        _assert_channel_free(conn, data.get("channel", ""), exclude_id=data["id"])
        _insert(conn, data)

    return get_node(data["id"])


def update_node(node_id: str, payload: Any) -> dict[str, Any]:
    data = _validate_payload(payload, partial=True)
    if not data:
        raise NodeError("Tidak ada field yang diubah.")

    with _DB_LOCK, _db() as conn:
        current = conn.execute("SELECT deleted_at FROM nodes WHERE id = ?", (node_id,)).fetchone()
    if current is None:
        raise NodeError("Node tidak ditemukan.", 404)
    if _deleted_at(current):
        raise NodeError("Node ada di tempat sampah. Pulihkan dulu sebelum diubah.", 409)

    if "rtsp" in data:
        data["rtsp"] = protect_source(data["rtsp"])

    data["updated_at"] = _now()
    columns = ", ".join(f"{key} = ?" for key in data)
    values = list(data.values()) + [node_id]

    with _DB_LOCK, _db() as conn:
        row = conn.execute("SELECT 1 FROM nodes WHERE id = ?", (node_id,)).fetchone()
        if row is None:
            raise NodeError("Node tidak ditemukan.", 404)
        if "channel" in data:
            _assert_channel_free(conn, data["channel"], exclude_id=node_id)
        conn.execute(f"UPDATE nodes SET {columns} WHERE id = ?", values)

    return get_node(node_id)


def delete_node(node_id: str) -> bool:
    with _DB_LOCK, _db() as conn:
        cursor = conn.execute("DELETE FROM nodes WHERE id = ?", (node_id,))
    return cursor.rowcount > 0


def reset_nodes() -> None:
    """Kosongkan direktori node (aksi eksplisit operator).

    Tidak ada seed: setelah reset direktori benar-benar kosong, dan backend
    tidak pernah menanam node sendiri saat start.
    """
    with _DB_LOCK, _db() as conn:
        conn.execute("DELETE FROM nodes")
