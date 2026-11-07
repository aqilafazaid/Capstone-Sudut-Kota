"""Penyimpanan konfigurasi kamera di SQLite.

Node kamera sebelumnya hidup di `localStorage` frontend. Modul ini memindahkannya
ke backend supaya URL RTSP (yang biasanya memuat user:password) tidak pernah
dikirim ke peramban. Frontend hanya menerima `hls_url`; detail RTSP hanya
dikembalikan lewat endpoint yang dilindungi token tulis.

Berkas database ditentukan `NODE_DB` (default `backend/data/sudutkota.db`).
"""

from __future__ import annotations

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
    updated_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_nodes_zona ON nodes(zona);
"""

SEED_NODES = [
    {
        "id": "cam_29", "channel": "29", "nama": "Simpang Ponolawen",
        "zona": "Kota Pekalongan", "jalan": "Simpang Ponolawen",
        "kota": "KOTA PEKALONGAN",
        "rtsp": "rtsp://10.28.110.253:554/Streaming/Channels/2901",
        "aktif": False,
    },
    {
        "id": "cam_35", "channel": "35", "nama": "Simpang Grogolan / Alun-Alun",
        "zona": "Kota Pekalongan", "jalan": "Simpang Grogolan",
        "kota": "KOTA PEKALONGAN",
        "rtsp": "rtsp://10.28.110.253:554/Streaming/Channels/3501",
        "aktif": False,
    },
    {
        "id": "cam_43", "channel": "43", "nama": "Simpang THR / Pusri",
        "zona": "Kota Pekalongan", "jalan": "Simpang THR",
        "kota": "KOTA PEKALONGAN",
        "rtsp": "rtsp://10.28.110.253:554/Streaming/Channels/4301",
        "aktif": False,
    },
]

# Hanya dipakai bila ALLOW_TEST_SOURCES=true. Sumbernya HLS publik, bukan RTSP,
# sehingga tidak boleh ikut pada konfigurasi produksi.
DEMO_NODES = [
    {
        "id": "cam_uji-1", "channel": "", "nama": "Stream Uji 1 — Big Buck Bunny",
        "zona": "Zona Uji (Demo)", "jalan": "Stream Uji 1 — Big Buck Bunny",
        "kota": "STREAM UJI",
        "rtsp": "https://test-streams.mux.dev/x36xhzz/x36xhzz.m3u8", "aktif": True,
    },
    {
        "id": "cam_uji-2", "channel": "", "nama": "Stream Uji 2 — Mux Multi-Bitrate",
        "zona": "Zona Uji (Demo)", "jalan": "Stream Uji 2 — Mux Multi-Bitrate",
        "kota": "STREAM UJI",
        "rtsp": "https://stream.mux.com/v69RSHhFelSm4701snP22dYz2jICy4E4FUyk02rW4gxRM.m3u8",
        "aktif": True,
    },
    {
        "id": "cam_uji-3", "channel": "", "nama": "Stream Uji 3 — Apple BipBop",
        "zona": "Zona Uji (Demo)", "jalan": "Stream Uji 3 — Apple BipBop",
        "kota": "STREAM UJI",
        "rtsp": "https://devstreaming-cdn.apple.com/videos/streaming/examples/img_bipbop_adv_example_ts/master.m3u8",
        "aktif": True,
    },
    {
        "id": "cam_uji-4", "channel": "", "nama": "Stream Uji 4 — Tears of Steel",
        "zona": "Zona Uji (Demo)", "jalan": "Stream Uji 4 — Tears of Steel",
        "kota": "STREAM UJI",
        "rtsp": "https://demo.unified-streaming.com/k8s/features/stable/video/tears-of-steel/tears-of-steel.ism/.m3u8",
        "aktif": True,
    },
]


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


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _text(value: Any, field: str, required: bool = False, max_len: int = 255) -> str:
    text = "" if value is None else str(value).strip()
    if required and not text:
        raise NodeError(f"{field} wajib diisi.")
    if len(text) > max_len:
        raise NodeError(f"{field} terlalu panjang (maks {max_len} karakter).")
    return text


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
        data["channel"] = _text(payload.get("channel"), "Nomor channel", max_len=20)
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
    }


def _row_detail(row: sqlite3.Row) -> dict[str, Any]:
    data = _row_public(row)
    data["rtsp"] = row["rtsp"]
    data["created_at"] = row["created_at"]
    return data


def count_nodes() -> int:
    with _db() as conn:
        return int(conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0])


def list_nodes() -> list[dict[str, Any]]:
    with _db() as conn:
        rows = conn.execute("SELECT * FROM nodes ORDER BY zona, nama").fetchall()
    return [_row_public(row) for row in rows]


def get_node(node_id: str, include_rtsp: bool = True) -> dict[str, Any]:
    with _db() as conn:
        row = conn.execute("SELECT * FROM nodes WHERE id = ?", (node_id,)).fetchone()
    if row is None:
        raise NodeError("Node tidak ditemukan.", 404)
    return _row_detail(row) if include_rtsp else _row_public(row)


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
            data.get("jalan", ""), data.get("kota", ""), data["rtsp"],
            int(data.get("aktif", 1)), now, now,
        ),
    )


def create_node(payload: Any, node_id: str | None = None) -> dict[str, Any]:
    data = _validate_payload(payload, partial=False)
    data["id"] = _new_id(data, node_id)

    with _DB_LOCK, _db() as conn:
        exists = conn.execute("SELECT 1 FROM nodes WHERE id = ?", (data["id"],)).fetchone()
        if exists:
            raise NodeError(f"Node {data['id']} sudah ada.", 409)
        _insert(conn, data)

    return get_node(data["id"])


def update_node(node_id: str, payload: Any) -> dict[str, Any]:
    data = _validate_payload(payload, partial=True)
    if not data:
        raise NodeError("Tidak ada field yang diubah.")

    data["updated_at"] = _now()
    columns = ", ".join(f"{key} = ?" for key in data)
    values = list(data.values()) + [node_id]

    with _DB_LOCK, _db() as conn:
        row = conn.execute("SELECT 1 FROM nodes WHERE id = ?", (node_id,)).fetchone()
        if row is None:
            raise NodeError("Node tidak ditemukan.", 404)
        conn.execute(f"UPDATE nodes SET {columns} WHERE id = ?", values)

    return get_node(node_id)


def delete_node(node_id: str) -> bool:
    with _DB_LOCK, _db() as conn:
        cursor = conn.execute("DELETE FROM nodes WHERE id = ?", (node_id,))
    return cursor.rowcount > 0


def seed_defaults(force: bool = False, seed_demo: bool | None = None) -> None:
    """Isi tabel kosong dengan node Pekalongan; demo hanya bila diizinkan."""
    if count_nodes() and not force:
        return

    demo = allow_test_sources() if seed_demo is None else seed_demo
    with _DB_LOCK, _db() as conn:
        for node in SEED_NODES:
            _insert(conn, dict(node))
        if demo:
            for node in DEMO_NODES:
                _insert(conn, dict(node))


def reset_nodes(seed_demo: bool | None = None) -> None:
    with _DB_LOCK, _db() as conn:
        conn.execute("DELETE FROM nodes")
    seed_defaults(force=True, seed_demo=seed_demo)
