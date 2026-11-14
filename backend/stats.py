"""Kolektor statistik: telemetri RTDB -> agregat per jam & per hari -> RTDB.

Engine AI menulis snapshot hitungan kendaraan ke ``<RTDB_ROOT>/cam_<channel>``
setiap dua detik. Snapshot itu hanya berisi kondisi *saat ini*; tidak ada
riwayat. Modul ini mengambil sampel berkala dan mengakumulasikannya ke

    <RTDB_ROOT>/statistik/<YYYY-MM-DD>/<HH>/<node_id>        (per jam)
    <RTDB_ROOT>/statistik_harian/<YYYY-MM-DD>/<node_id>      (per hari)

Agregat harian ditulis bersamaan dengan agregat jam supaya halaman Statistik
tidak perlu membaca ±24 record jam untuk setiap hari pada rentang panjang
(1 tahun ke atas). Halaman membaca keduanya lewat ``GET /api/stats/telemetry``.

Nilai yang disimpan adalah penjumlahan hitungan per sampel (mirip
kendaraan-menit bila sampel diambil tiap menit), ditambah ``samples`` dan
``max_total`` untuk analisis. Sampel yang lebih tua dari ``STATS_STALE_SECONDS``
dilewati supaya stream yang mati tidak terus menambah angka.

Selama engine AI belum pernah mengirim telemetri, RTDB tidak punya satu pun
sampel sehingga halaman menampilkan nol. Tidak ada data contoh yang dibangkitkan
di mana pun: satu-satunya penulis koleksi ini adalah kolektor di bawah, dari
snapshot AI yang sungguhan.
"""

from __future__ import annotations

import os
import threading
from datetime import date, datetime, timedelta, timezone
from typing import Any

import firebase_init

# Indonesia tidak memakai DST; offset tetap lebih sederhana daripada zoneinfo
# yang butuh paket tzdata di Windows.
WIB = timezone(timedelta(hours=7))

KELAS = ("mobil", "motor", "truk", "bus")
COUNT_KEYS = KELAS + ("total",)
_FIELD = {k: f"jumlah_{k}" for k in KELAS}

# Akar koleksi di RTDB. Nama lama ``statistik`` dipertahankan supaya aturan
# dan data yang sudah ada tetap berlaku.
HOURS_ROOT = "statistik"
DAILY_ROOT = "statistik_harian"
META_ROOT = "statistik_meta"

DEFAULT_SAMPLE_SECONDS = 60
DEFAULT_STALE_SECONDS = 300
# Cukup untuk "Seluruhnya" (sejak DATA_START) supaya label rentang di halaman
# tidak menjanjikan periode yang datanya dipotong.
DEFAULT_MAX_DAYS = 4000
DEFAULT_CACHE_SECONDS = 30

# Sejak kapan arsip contoh dimulai; sama dengan DATA_START di frontend/js/store.js.
DATA_START = date(2019, 1, 1)

_lock = threading.Lock()
_cache: dict[str, Any] = {"at": 0.0, "data": None}
_thread: threading.Thread | None = None
_stop = threading.Event()


def _env_int(name: str, default: int) -> int:
    try:
        return max(1, int(str(os.environ.get(name, default)).strip()))
    except (TypeError, ValueError):
        return default


def sample_seconds() -> int:
    return _env_int("STATS_SAMPLE_SECONDS", DEFAULT_SAMPLE_SECONDS)


def stale_seconds() -> int:
    return _env_int("STATS_STALE_SECONDS", DEFAULT_STALE_SECONDS)


def max_days() -> int:
    return _env_int("STATS_MAX_DAYS", DEFAULT_MAX_DAYS)


def _cache_seconds() -> int:
    return _env_int("STATS_CACHE_SECONDS", DEFAULT_CACHE_SECONDS)


def _app():
    return firebase_init.init_firebase()


def _root() -> str:
    return os.environ.get("RTDB_ROOT", "cctv_data").strip("/") or "cctv_data"


def _ref(*parts: str):
    from firebase_admin import db as fb_db

    segments = [_root(), *[p.strip("/") for p in parts if p and p.strip("/")]]
    return fb_db.reference("/" + "/".join(segments), app=_app())


def _int(value: Any) -> int:
    try:
        return max(0, int(float(value)))
    except (TypeError, ValueError):
        return 0


def _float(value: Any) -> float:
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return 0.0


def _empty_bucket() -> dict[str, int]:
    return {"mobil": 0, "motor": 0, "truk": 0, "bus": 0, "total": 0}


def _add(target: dict[str, int], value: dict[str, int]) -> None:
    for key in COUNT_KEYS:
        target[key] = target.get(key, 0) + _int(value.get(key))


def _snapshot_time(raw: dict[str, Any], fallback: datetime) -> datetime | None:
    """Waktu snapshot AI. ``None`` bila tidak ada/ tidak masuk akal."""
    value = raw.get("timestamp")
    if value in (None, ""):
        return fallback
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return None
    # timestamp milidetik dari sumber lain tetap diterima.
    if seconds > 1e11:
        seconds /= 1000.0
    try:
        return datetime.fromtimestamp(seconds, WIB)
    except (OverflowError, OSError, ValueError):
        return None


def _counts(raw: dict[str, Any]) -> dict[str, int]:
    data = {k: _int(raw.get(_FIELD[k])) for k in KELAS}
    data["total"] = _int(raw.get("total_kendaraan")) or sum(data.values())
    return data


# ---------------------------------------------------------------------------
# Penyimpanan sampel
# ---------------------------------------------------------------------------

def collect_once(nodes: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Ambil satu sampel dari setiap node ber-``channel`` dan simpan ke RTDB.

    ``nodes`` diisi hanya oleh tes; produksi memakai daftar node SQLite.
    """
    if nodes is None:
        import nodes as node_store

        nodes = node_store.list_nodes()

    if firebase_init.missing_keys() or not _configured():
        return {"ok": False, "reason": "firebase belum dikonfigurasi", "collected": [], "skipped": []}

    now = datetime.now(WIB)
    stale = stale_seconds()
    collected: list[str] = []
    skipped: list[dict[str, str]] = []

    for node in nodes:
        channel = str(node.get("channel") or "").strip()
        node_id = str(node.get("id") or "").strip()
        if not channel or not node_id:
            continue

        try:
            raw = _ref("cam_" + channel).get()
        except Exception as exc:  # RTDB tidak terjangkau: satu node gagal, lanjut
            skipped.append({"id": node_id, "reason": type(exc).__name__})
            continue

        if not isinstance(raw, dict) or not raw:
            skipped.append({"id": node_id, "reason": "belum ada telemetri"})
            continue
        if str(raw.get("status") or "").upper() == "OFFLINE":
            skipped.append({"id": node_id, "reason": "offline"})
            continue

        stamp = _snapshot_time(raw, now)
        if stamp is None:
            skipped.append({"id": node_id, "reason": "timestamp tidak valid"})
            continue
        if (now - stamp).total_seconds() > stale:
            skipped.append({"id": node_id, "reason": "telemetri basi"})
            continue

        counts = _counts(raw)
        day_key = stamp.strftime("%Y-%m-%d")
        hour_key = f"{stamp.hour:02d}"
        epoch = stamp.timestamp()

        def _accumulate(current: Any) -> dict[str, Any]:
            data = dict(current) if isinstance(current, dict) else {}
            for key in COUNT_KEYS:
                data[key] = _int(data.get(key)) + counts[key]
            data["samples"] = _int(data.get("samples")) + 1
            data["max_total"] = max(_int(data.get("max_total")), counts["total"])
            data["first_ts"] = min(float(data.get("first_ts") or epoch), epoch)
            data["last_ts"] = max(float(data.get("last_ts") or epoch), epoch)
            return data

        try:
            # Jam dan hari diakumulasi dari sampel yang sama supaya total
            # "1 Hari" selalu identik dengan kontribusi hari ini di "1 Minggu".
            _ref(HOURS_ROOT, day_key, hour_key, node_id).transaction(_accumulate)
            _ref(DAILY_ROOT, day_key, node_id).transaction(_accumulate)
            collected.append(node_id)
        except Exception as exc:
            skipped.append({"id": node_id, "reason": "gagal menulis: " + type(exc).__name__})

    if collected:
        invalidate_cache()
    return {
        "ok": True,
        "at": now.isoformat(timespec="seconds"),
        "collected": collected,
        "skipped": skipped,
    }


def _configured() -> bool:
    import auth

    return auth.configured()


def invalidate_cache() -> None:
    with _lock:
        _cache["at"] = 0.0
        _cache["data"] = None


def _bucket(raw: dict[str, Any]) -> dict[str, int]:
    """Hanya angka yang dipakai halaman; field analisis tidak dikirim."""
    return {key: _int(raw.get(key)) for key in COUNT_KEYS}


def _meta() -> dict[str, Any]:
    """Penanda seed terakhir (opsional; kegagalan baca tidak fatal)."""
    try:
        raw = _ref(META_ROOT).get()
    except Exception:
        return {}
    return raw if isinstance(raw, dict) else {}


# ---------------------------------------------------------------------------
# Baca agregat untuk halaman Statistik
# ---------------------------------------------------------------------------

def _empty_live(reason: str) -> dict[str, Any]:
    return {
        "status": "OFFLINE",
        "stale": True,
        "age_seconds": None,
        "timestamp": None,
        "jumlah_mobil": 0,
        "jumlah_motor": 0,
        "jumlah_truk": 0,
        "jumlah_bus": 0,
        "total_kendaraan": 0,
        "server_fps": 0.0,
        "night_vision_status": False,
        "lowlight_variant": "",
        "lowlight_model": "",
        "deteksi_aktif": False,
        "yolo_weights": "",
        "latency_ms": 0.0,
        "fps_in": 0.0,
        "enhance_ms": 0.0,
        "yolo_ms": 0.0,
        "detect_fps": 0.0,
        "encoder": "",
        "device": "",
        "engine": "",
        "reason": reason,
    }


def live_snapshots(nodes: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Snapshot terakhir per node, dibaca langsung dari RTDB ``cam_<channel>``.

    Halaman CCTV memakai ini untuk kartu Mobil/Motor/Truk/Bus/Total/FPS.
    Tidak ada simulasi di peramban: bila engine AI belum menulis snapshot
    (atau sudah basi), nilainya nol dan ``status`` = OFFLINE.
    """
    if nodes is None:
        import nodes as node_store

        nodes = node_store.list_nodes()

    now = datetime.now(WIB)
    result: dict[str, Any] = {
        "ok": True,
        "generated_at": now.isoformat(),
        "stale_seconds": stale_seconds(),
        "nodes": {},
    }

    if firebase_init.missing_keys() or not _configured():
        result.update(ok=False, reason="firebase belum dikonfigurasi")
        return result

    stale = stale_seconds()

    for node in nodes:
        node_id = str(node.get("id") or "").strip()
        channel = str(node.get("channel") or "").strip()
        if not node_id:
            continue
        if not channel:
            result["nodes"][node_id] = _empty_live("tanpa channel")
            continue

        try:
            raw = _ref("cam_" + channel).get()
        except Exception as exc:  # RTDB tidak terjangkau: satu node gagal, lanjut
            result["nodes"][node_id] = _empty_live(type(exc).__name__)
            continue

        if not isinstance(raw, dict) or not raw:
            result["nodes"][node_id] = _empty_live("belum ada telemetri")
            continue

        counts = _counts(raw)
        stamp = _snapshot_time(raw, now)
        age = round((now - stamp).total_seconds(), 1) if stamp else None
        fresh = age is not None and age <= stale
        status = str(raw.get("status") or ("ONLINE" if fresh else "OFFLINE")).upper()
        if not fresh:
            status = "OFFLINE"

        try:
            fps = round(float(raw.get("server_fps") or 0), 1)
        except (TypeError, ValueError):
            fps = 0.0

        result["nodes"][node_id] = {
            "status": status,
            "stale": not fresh,
            "age_seconds": age,
            "timestamp": stamp.timestamp() if stamp else None,
            "jumlah_mobil": counts["mobil"],
            "jumlah_motor": counts["motor"],
            "jumlah_truk": counts["truk"],
            "jumlah_bus": counts["bus"],
            "total_kendaraan": counts["total"],
            "server_fps": fps,
            "night_vision_status": bool(raw.get("night_vision_status")),
            # Panel Kontrol Modul AI membaca keadaan engine dari sini, bukan
            # dari localStorage: yang tampil harus yang benar-benar berjalan.
            "lowlight_variant": str(raw.get("lowlight_variant") or ""),
            "lowlight_model": str(raw.get("lowlight_model") or ""),
            "deteksi_aktif": bool(raw.get("deteksi_aktif")),
            "yolo_weights": str(raw.get("yolo_weights") or ""),
            "latency_ms": _float(raw.get("latency_ms")),
            # Beban kerja engine: terlihat apakah AI jalan di GPU atau CPU
            # dan seberapa cepat deteksi diperbarui.
            "fps_in": _float(raw.get("fps_in")),
            "enhance_ms": _float(raw.get("enhance_ms")),
            "yolo_ms": _float(raw.get("yolo_ms")),
            "detect_fps": _float(raw.get("detect_fps")),
            "encoder": str(raw.get("encoder") or ""),
            "device": str(raw.get("device") or ""),
            "engine": str(raw.get("engine") or ""),
        }

    return result


def write_ai_status(channel: str, status: dict[str, Any]) -> dict[str, Any]:
    """Titipkan permintaan modul AI ke ``<RTDB_ROOT>/cam_<channel>/ai_status``.

    Engine AI membacanya tiap 2 detik, jadi perubahan berlaku tanpa restart.
    Backend tidak menulis state "seolah sudah jalan": engine yang melaporkan
    keadaan sebenarnya lewat ``cam_<channel>``.
    """
    channel = str(channel or "").strip()
    if not channel:
        raise ValueError("channel kosong")
    ref = _ref("cam_" + channel, "ai_status")
    ref.update(status)
    return dict(status)


def purge_live(node_id: str, channel: str = "") -> dict[str, Any]:
    """Hapus hanya telemetri live ``cam_<channel>`` (dipakai soft delete).

    Statistik historis tidak disentuh: node yang dipulihkan harus mendapat
    riwayatnya kembali. Hapus permanen memakai :func:`purge_node`.
    """
    node_id = (node_id or "").strip()
    chan = str(channel or "").strip() or "".join(ch for ch in node_id if ch.isdigit())
    report: dict[str, Any] = {"node": node_id, "cam": 0, "errors": []}
    if not chan:
        return report
    try:
        _ref("cam_" + chan).delete()
        report["cam"] = 1
    except Exception as exc:
        report["errors"].append(f"cam_{chan}: {exc}")
    return report


def purge_node(node_id: str, channel: str = "") -> dict[str, Any]:
    """Hapus seluruh jejak satu node di RTDB.

    Node yang dihapus dari direktori tidak boleh meninggalkan data di Firebase:

    - ``cam_<channel>`` — telemetri live + ``ai_status`` (dibaca panel CCTV),
    - ``statistik/<tanggal>/<jam>/<node>`` — agregat per jam,
    - ``statistik_harian/<tanggal>/<node>`` — agregat harian (tabel Statistik).

    Semua langkah best-effort: kegagalan dicatat di ``errors`` tanpa
    menggagalkan penghapusan node, karena koneksi Firebase bisa sedang mati.
    Biayanya satu shallow read untuk daftar tanggal + satu read per tanggal
    (24 jam × node), dan hanya dijalankan saat operator menghapus node.
    """
    node_id = (node_id or "").strip()
    report: dict[str, Any] = {"node": node_id, "cam": 0, "hours": 0, "days": 0, "errors": []}
    if not node_id:
        return report

    chan = str(channel or "").strip()
    if not chan:
        chan = "".join(ch for ch in node_id if ch.isdigit())

    live = purge_live(node_id, chan)
    report["cam"] = live["cam"]
    report["errors"].extend(live["errors"])

    try:
        hours_days = _ref(HOURS_ROOT).get(shallow=True) or {}
    except Exception as exc:
        report["errors"].append(f"{HOURS_ROOT}: {exc}")
        hours_days = {}

    for day in sorted(hours_days)[:4000]:
        try:
            hours = _ref(HOURS_ROOT, day).get() or {}
        except Exception as exc:
            report["errors"].append(f"{HOURS_ROOT}/{day}: {exc}")
            continue
        if not isinstance(hours, dict):
            continue
        for hour, nodes in hours.items():
            if not isinstance(nodes, dict) or node_id not in nodes:
                continue
            try:
                _ref(HOURS_ROOT, day, hour, node_id).delete()
                report["hours"] += 1
            except Exception as exc:
                report["errors"].append(f"{HOURS_ROOT}/{day}/{hour}/{node_id}: {exc}")

    try:
        daily_days = _ref(DAILY_ROOT).get(shallow=True) or {}
    except Exception as exc:
        report["errors"].append(f"{DAILY_ROOT}: {exc}")
        daily_days = {}

    for day in sorted(daily_days)[:4000]:
        try:
            if _ref(DAILY_ROOT, day, node_id).get(shallow=True) is None:
                continue
            _ref(DAILY_ROOT, day, node_id).delete()
            report["days"] += 1
        except Exception as exc:
            report["errors"].append(f"{DAILY_ROOT}/{day}/{node_id}: {exc}")

    # Cache agregat di memori memuat node ini; buang supaya halaman Statistik
    # tidak menyajikan angka lama sampai TTL habis.
    with _lock:
        _cache["data"] = None
        _cache["at"] = 0.0

    return report


def read_telemetry(days: int | None = None) -> dict[str, Any]:
    """Agregat siap-pakai untuk ``Store.stats()`` di peramban.

    ``daily`` berisi total per tanggal per node (periode >= 1 minggu),
    ``hourly`` berisi 24 jam hari ini per node (periode 1 hari).

    Pembacaan dibatasi ke rentang yang diminta: koleksi harian dibaca dengan
    ``start_at``/``end_at`` pada kunci tanggal, dan jam hanya untuk hari ini.
    Tanpa batas itu, arsip setahun penuh berarti ±26.000 record per muat halaman.
    """
    span = days if days and days > 0 else max_days()

    with _lock:
        cached = _cache["data"]
        if (
            cached is not None
            and _cache.get("span") == span
            and (datetime.now(WIB).timestamp() - _cache["at"]) < _cache_seconds()
        ):
            return cached

    today = datetime.now(WIB).date()
    cutoff = today - timedelta(days=span - 1)
    today_key = today.isoformat()

    raw_daily = (
        _ref(DAILY_ROOT)
        .order_by_key()
        .start_at(cutoff.isoformat())
        .end_at(today_key)
        .get()
        or {}
    )
    if not isinstance(raw_daily, dict):
        raw_daily = {}

    daily: dict[str, dict[str, dict[str, int]]] = {}
    for day_key, nodes in raw_daily.items():
        if not isinstance(nodes, dict):
            continue
        for node_id, record in nodes.items():
            if isinstance(record, dict):
                daily.setdefault(str(day_key), {})[str(node_id)] = _bucket(record)

    # Jam hari ini: dipakai periode "1 Hari" dan sebagai cadangan untuk node
    # yang agregat hariannya belum sempat ditulis (data lama sebelum koleksi
    # harian ada, atau transaksi kedua gagal).
    raw_hours = _ref(HOURS_ROOT, today_key).get() or {}
    hourly: dict[str, list[dict[str, int]]] = {}
    if isinstance(raw_hours, dict):
        for hour_key, nodes in raw_hours.items():
            try:
                hour = int(str(hour_key))
            except ValueError:
                continue
            if not 0 <= hour <= 23 or not isinstance(nodes, dict):
                continue
            for node_id, record in nodes.items():
                if not isinstance(record, dict):
                    continue
                slots = hourly.setdefault(str(node_id), [_empty_bucket() for _ in range(24)])
                _add(slots[hour], _bucket(record))

    today_nodes = daily.get(today_key, {})
    for node_id, slots in hourly.items():
        if node_id in today_nodes:
            continue
        fallback = _empty_bucket()
        for slot in slots:
            _add(fallback, slot)
        if any(fallback[key] for key in COUNT_KEYS):
            today_nodes[node_id] = fallback
    if today_nodes:
        daily[today_key] = today_nodes

    # Node di tempat sampah tidak ditampilkan di halaman/ekspor: riwayatnya
    # tetap tersimpan supaya restore mengembalikan angka lamanya. Node yang
    # tidak ada di direktori (yatim) juga tidak ikut ditampilkan.
    try:
        import nodes as node_store

        aktif = {node["id"] for node in node_store.list_nodes()}
    except Exception:
        aktif = None
    if aktif is not None:
        daily = {
            day: {node_id: record for node_id, record in items.items() if node_id in aktif}
            for day, items in daily.items()
        }
        daily = {day: items for day, items in daily.items() if items}
        hourly = {node_id: slots for node_id, slots in hourly.items() if node_id in aktif}

    meta = _meta()

    payload = {
        "source": "firebase",
        "has_data": bool(daily),
        "generated_at": datetime.now(WIB).isoformat(timespec="seconds"),
        "days": span,
        "daily": daily,
        "hourly": hourly,
        "seeded_at": meta.get("seeded_at"),
        "seeded_days": meta.get("seeded_days"),
    }

    with _lock:
        _cache["data"] = payload
        _cache["at"] = datetime.now(WIB).timestamp()
        _cache["span"] = span
    return payload


# ---------------------------------------------------------------------------
# Thread sampler
# ---------------------------------------------------------------------------

def start_collector() -> bool:
    """Mulai thread sampler. ``False`` bila Firebase belum dikonfigurasi."""
    global _thread
    if not _configured():
        print("[STATS] Firebase belum dikonfigurasi; kolektor statistik tidak dijalankan.")
        return False
    if _thread is not None and _thread.is_alive():
        return True

    def _loop() -> None:
        while not _stop.wait(sample_seconds()):
            try:
                result = collect_once()
                if result.get("collected"):
                    print(f"[STATS] sampel tersimpan: {', '.join(result['collected'])}")
            except Exception as exc:  # kolektor tidak boleh mematikan backend
                print(f"[STATS] gagal mengambil sampel: {type(exc).__name__}: {exc}")

    _thread = threading.Thread(target=_loop, name="stats-collector", daemon=True)
    _thread.start()
    print(f"[STATS] kolektor aktif tiap {sample_seconds()} detik.")
    return True


def stop_collector() -> None:
    _stop.set()


def register_error_handlers(app) -> None:
    """Tidak ada error khusus: kegagalan RTDB dilaporkan di body respons."""
