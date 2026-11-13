"""Hapus agregat statistik RTDB untuk node yang sudah tidak ada di SQLite.

Node CCTV bersumber dari ``backend/data/sudutkota.db``. Ketika sebuah node
dihapus, arsip agregat di RTDB tetap menyimpan id lamanya sehingga halaman
Statistik bisa memuat data untuk kamera yang tidak lagi terdaftar. Skrip ini
menyisir kedua koleksi dan membuang entri milik id yatim.

Selalu membuat cadangan JSON sebelum menghapus:

    backend/data/backup/stats-prune-<YYYYmmdd-HHMMSS>.json

Pakai:
    python scripts/prune_stats.py --dry-run     # lihat apa yang akan dibuang
    python scripts/prune_stats.py               # cadangkan lalu hapus
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))
os.chdir(BASE_DIR)

import firebase_init  # noqa: E402
import nodes as node_store  # noqa: E402
import stats  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Prune agregat statistik yatim di RTDB.")
    parser.add_argument("--dry-run", action="store_true", help="tampilkan tanpa menghapus")
    args = parser.parse_args()

    if firebase_init.missing_keys():
        print("Kredensial Firebase belum lengkap:", ", ".join(firebase_init.missing_keys()))
        return 1
    firebase_init.init_firebase()

    known = {node["id"] for node in node_store.list_nodes()}
    print(f"node di SQLite: {len(known)} -> {sorted(known)}")

    daily = stats._ref(stats.DAILY_ROOT).get() or {}
    hourly_today = stats._ref(stats.HOURS_ROOT).get() or {}

    stale: set[str] = set()
    for day, per_node in (daily or {}).items():
        if isinstance(per_node, dict):
            stale.update(node_id for node_id in per_node if node_id not in known)
    for day, per_hour in (hourly_today or {}).items():
        if not isinstance(per_hour, dict):
            continue
        for hour, per_node in per_hour.items():
            if isinstance(per_node, dict):
                stale.update(node_id for node_id in per_node if node_id not in known)

    if not stale:
        print("Tidak ada id yatim. RTDB sudah sinkron dengan SQLite.")
        return 0

    print(f"id yatim: {len(stale)} -> {sorted(stale)}")

    # Kumpulkan dulu isi yang akan dibuang, supaya ada rollback berbentuk JSON.
    dump: dict[str, dict] = {"daily": {}, "hourly": {}}
    for day, per_node in (daily or {}).items():
        hits = {nid: rec for nid, rec in (per_node or {}).items() if nid in stale}
        if hits:
            dump["daily"][day] = hits
    for day, per_hour in (hourly_today or {}).items():
        day_hits: dict[str, dict] = {}
        for hour, per_node in (per_hour or {}).items():
            hits = {nid: rec for nid, rec in (per_node or {}).items() if nid in stale}
            if hits:
                day_hits[hour] = hits
        if day_hits:
            dump["hourly"][day] = day_hits

    if args.dry_run:
        print(json.dumps({k: len(v) for k, v in dump.items()}, ensure_ascii=False))
        print("--dry-run: tidak ada yang dihapus.")
        return 0

    backup_dir = BASE_DIR / "data" / "backup"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = backup_dir / f"stats-prune-{stamp}.json"
    backup.write_text(json.dumps(dump, indent=2, ensure_ascii=False), encoding="utf-8")
    print("cadangan:", backup)

    # Penghapusan dibatch supaya tidak menembak RTDB ribuan kali:
    # - direktori node kosong  -> seluruh koleksi memang yatim, hapus 2 root;
    # - satu hari yatim penuh  -> hapus node hari itu;
    # - selain itu             -> hapus per (hari, node).
    whole_tree = not known
    removed_daily = removed_hourly = 0

    if whole_tree:
        removed_daily = sum(len(hits) for hits in dump["daily"].values())
        removed_hourly = sum(len(hits) for hours in dump["hourly"].values()
                             for hits in hours.values())
        stats._ref(stats.DAILY_ROOT).delete()
        stats._ref(stats.HOURS_ROOT).delete()
        # Metadata seed ikut dibuang: kalau tidak, API masih melaporkan
        # "seeded_days" untuk arsip yang sudah tidak ada.
        stats._ref(stats.META_ROOT).delete()
        print("meta seed (seeded_days) dihapus.")
    else:
        for day, hits in dump["daily"].items():
            per_day = {nid for nid in (daily.get(day) or {})}
            if per_day <= stale:
                stats._ref(stats.DAILY_ROOT, day).delete()
                removed_daily += len(hits)
            else:
                for node_id in hits:
                    stats._ref(stats.DAILY_ROOT, day, node_id).delete()
                    removed_daily += 1
        for day, hours in dump["hourly"].items():
            per_day = set()
            for per_node in (hourly_today.get(day) or {}).values():
                per_day.update((per_node or {}).keys())
            if per_day <= stale:
                stats._ref(stats.HOURS_ROOT, day).delete()
                removed_hourly += sum(len(h) for h in hours.values())
            else:
                for hour, hits in hours.items():
                    for node_id in hits:
                        stats._ref(stats.HOURS_ROOT, day, hour, node_id).delete()
                        removed_hourly += 1

    stats.invalidate_cache()
    print(f"dihapus: {removed_daily} entri harian, {removed_hourly} entri per jam"
          + (" (seluruh koleksi)" if whole_tree else ""))
    print("Rollback: import ulang isi", backup.name, "ke", stats.DAILY_ROOT, "/", stats.HOURS_ROOT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
