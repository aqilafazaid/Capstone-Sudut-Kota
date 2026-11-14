"""Bersihkan sisa data node yang sudah tidak ada di direktori (tool operator).

Menghapus node lewat Dashboard sudah membersihkan RTDB + log + folder HLS.
Skrip ini menutup kasus lain: sisa data dari versi lama, node yang dihapus
sebelum pembersihan itu ada, atau folder/log yatim setelah reset manual.

Yang dipindai (semua dibandingkan dengan tabel `nodes` di SQLite):

- ``media/hls/<node>/`` folder HLS tanpa node,
- ``media/hls/_logs/<node>.log`` log engine tanpa node,
- ``<RTDB_ROOT>/cam_<channel>`` telemetri live tanpa node,
- ``<RTDB_ROOT>/statistik/<tanggal>/<jam>/<node>`` agregat per jam,
- ``<RTDB_ROOT>/statistik_harian/<tanggal>/<node>`` agregat harian.

    cd backend
    .venv/Scripts/python.exe scripts/purge_orphan_data.py            # lihat saja
    .venv/Scripts/python.exe scripts/purge_orphan_data.py --apply    # hapus

Tanpa ``--apply`` tidak ada yang diubah.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(BASE_DIR / ".env")

import nodes  # noqa: E402
import stats  # noqa: E402
from ai_engine.engine_manager import LOG_ROOT  # noqa: E402
from streamer import MEDIA_ROOT  # noqa: E402


def scan() -> dict:
    """Kumpulkan kandidat yatim tanpa mengubah apa pun."""
    # Termasuk node di tempat sampah: barisnya masih milik direktori sampai
    # dihapus permanen, jadi statistik/telemetrinya BUKAN yatim.
    node_rows = nodes.list_nodes(include_deleted=True)
    node_ids = {node["id"] for node in node_rows}
    channels = {str(node.get("channel") or "") for node in node_rows if node.get("channel")}

    hasil = {"dirs": [], "logs": [], "channels": [], "nodes": [], "errors": []}

    media = Path(MEDIA_ROOT)
    if media.exists():
        for path in media.iterdir():
            if path.is_dir() and path.name != "_logs" and path.name not in node_ids:
                hasil["dirs"].append(path)
    if Path(LOG_ROOT).exists():
        for path in Path(LOG_ROOT).glob("*.log"):
            if path.stem not in node_ids:
                hasil["logs"].append(path)

    # Telemetri live: kunci root `cam_<channel>` tanpa node.
    try:
        root_keys = stats._ref("").get(shallow=True) or {}  # noqa: SLF001
    except Exception as exc:
        hasil["errors"].append(f"akar RTDB: {exc}")
        root_keys = {}
    for key in root_keys:
        if key.startswith("cam_") and key[4:] not in channels:
            hasil["channels"].append(key)

    # Agregat: kumpulkan id node yang muncul di statistik.
    kandidat: set[str] = set()
    try:
        for day in (stats._ref(stats.HOURS_ROOT).get(shallow=True) or {}):  # noqa: SLF001
            hours = stats._ref(stats.HOURS_ROOT, day).get() or {}  # noqa: SLF001
            if not isinstance(hours, dict):
                continue
            for items in hours.values():
                if isinstance(items, dict):
                    kandidat.update(items.keys())
        for day in (stats._ref(stats.DAILY_ROOT).get(shallow=True) or {}):  # noqa: SLF001
            items = stats._ref(stats.DAILY_ROOT, day).get() or {}  # noqa: SLF001
            if isinstance(items, dict):
                kandidat.update(items.keys())
    except Exception as exc:
        hasil["errors"].append(f"statistik: {exc}")

    hasil["nodes"] = sorted(kandidat - node_ids)
    return hasil


def main(argv: list[str]) -> int:
    apply = "--apply" in argv
    kandidat = scan()

    print(f"node terdaftar (termasuk tempat sampah) : {len(nodes.list_nodes(include_deleted=True))}")
    print(f"folder HLS yatim : {len(kandidat['dirs'])}")
    for path in kandidat["dirs"]:
        print(f"  - {path.name}/")
    print(f"log yatim : {len(kandidat['logs'])}")
    for path in kandidat["logs"]:
        print(f"  - {path.name}")
    print(f"cam_<channel> yatim : {len(kandidat['channels'])}")
    for key in kandidat["channels"]:
        print(f"  - {key}")
    print(f"node di statistik : {len(kandidat['nodes'])}")
    for node_id in kandidat["nodes"]:
        print(f"  - {node_id}")

    for err in kandidat["errors"]:
        print(f"WARN: {err}")

    total = sum(len(kandidat[k]) for k in ("dirs", "logs", "channels", "nodes"))
    if total == 0:
        print("HASIL: tidak ada sisa data.")
        return 0

    if not apply:
        print("HASIL: dry-run. Jalankan dengan --apply untuk menghapus.")
        return 0

    gagal = 0
    for path in kandidat["dirs"]:
        shutil.rmtree(path, ignore_errors=True)
        print(("PASS " if not path.exists() else "FAIL ") + f"folder {path.name}/")
        gagal += 1 if path.exists() else 0

    for path in kandidat["logs"]:
        try:
            path.unlink(missing_ok=True)
            print("PASS " + f"log {path.name}")
        except OSError as exc:
            print(f"FAIL log {path.name}: {exc}")
            gagal += 1

    for node_id in kandidat["nodes"]:
        report = stats.purge_node(node_id)
        print(("PASS " if not report["errors"] else "FAIL ") +
              f"statistik {node_id} (jam={report['hours']}, hari={report['days']})")
        gagal += 1 if report["errors"] else 0

    for key in kandidat["channels"]:
        try:
            stats._ref(key).delete()  # noqa: SLF001
            print("PASS " + f"telemetri {key}")
        except Exception as exc:
            print(f"FAIL telemetri {key}: {exc}")
            gagal += 1

    print(f"HASIL: {'semua bersih' if gagal == 0 else f'{gagal} gagal'}")
    return 0 if gagal == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
