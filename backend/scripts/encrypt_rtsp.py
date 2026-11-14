"""Enkripsi URL RTSP yang sudah tersimpan di SQLite (tool operator).

CRUD lewat API selalu menulis kolom `rtsp` sebagai ciphertext AES-256-GCM
(``enc:v2:...``). Skrip ini mengubah **baris lama** yang masih teks biasa.

Kunci 32 byte diambil dari `NODE_SECRET` (backend/.env) atau dari berkas
``backend/data/node_secret.key``; bila keduanya belum ada, `--apply` membuat
berkas kunci itu supaya hasilnya bisa didekripsi lagi.

    cd backend
    .venv/Scripts/python.exe scripts/encrypt_rtsp.py             # lihat saja
    .venv/Scripts/python.exe scripts/encrypt_rtsp.py --apply     # tulis

`--apply` menulis cadangan JSON berisi URL asli sebelum mengubah apa pun.
Cadangan itu dihapus lagi setelah verifikasi lulus; pakai `--keep-backup`
kalau memang ingin menyimpannya (ingat: isinya sandi kamera).

Peringatan: kunci harus disimpan di luar database. Kalau kunci hilang/berubah,
URL RTSP terenkripsi tidak bisa dibuka (stream berhenti) — pulihkan kuncinya,
atau isi ulang URL lewat Dashboard.
"""

from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(BASE_DIR / ".env")

import nodes  # noqa: E402


def scrub(path: Path) -> bool:
    """Buang sisa teks biasa dari free page / WAL.

    UPDATE tidak menimpa sel lama: tanpa VACUUM, URL asli masih bisa dibaca
    dengan grep pada berkas .db. Fungsi ini membangun ulang berkas lalu
    memastikan tidak ada lagi "rtsp://" di dalamnya.
    """
    for attempt in range(3):
        try:
            conn = sqlite3.connect(path, timeout=15)
            try:
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                conn.execute("VACUUM")
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            finally:
                conn.close()
            break
        except sqlite3.OperationalError as exc:
            print(f"scrub    : percobaan {attempt + 1} gagal ({exc}); ulangi…")
    sisa = [name for name in (path.name, path.name + "-wal")
            if (path.parent / name).exists() and b"rtsp://" in (path.parent / name).read_bytes()]
    if sisa:
        print(f"FAIL     : jejak teks biasa masih ada di {', '.join(sisa)}")
        return False
    print("PASS     : berkas database bersih dari teks biasa (VACUUM + checkpoint)")
    return True


def main(argv: list[str]) -> int:
    apply = "--apply" in argv
    keep_backup = "--keep-backup" in argv

    path = nodes.db_path()
    if not path.exists():
        print(f"GAGAL: database tidak ditemukan: {path}")
        return 1

    origin = nodes.key_origin()
    if apply and nodes._key_bytes(create=True) is None:  # noqa: SLF001 - tool operator
        print("GAGAL: kunci AES-256 tidak bisa disiapkan.")
        print("       Isi NODE_SECRET (base64 32 byte) atau pastikan backend/data/ bisa ditulisi.")
        return 1
    if apply:
        origin = nodes.key_origin()

    sumber = {
        "env": "NODE_SECRET (backend/.env)",
        "file": f"berkas {nodes._KEY_FILE}",
    }.get(origin, "belum ada (dibuat saat --apply)")

    with nodes._db() as conn:  # noqa: SLF001
        rows = conn.execute("SELECT id, rtsp FROM nodes ORDER BY id").fetchall()

    plain = [row for row in rows if row["rtsp"] and not row["rtsp"].startswith(nodes._ENC_PREFIX)]
    done = len(rows) - len(plain)

    print(f"database : {path}")
    print(f"kunci    : {sumber}")
    print(f"node     : {len(rows)} ({done} terenkripsi AES-256-GCM, {len(plain)} teks biasa)")
    for row in plain:
        print(f"  - {row['id']}: akan dienkripsi")

    if not plain:
        print("baris    : tidak ada yang perlu diubah.")
        if apply and not scrub(path):
            return 1
        print("HASIL: tidak ada yang perlu diubah.")
        return 0

    if not apply:
        print("HASIL: dry-run. Jalankan dengan --apply untuk menulis.")
        return 0

    backup_dir = BASE_DIR / "data" / "backup"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = backup_dir / f"rtsp-encrypt-{stamp}.json"
    backup.write_text(
        json.dumps([{"id": row["id"], "rtsp": row["rtsp"]} for row in plain], indent=2),
        encoding="utf-8",
    )
    print(f"cadangan : {backup}  (berisi URL asli)")

    with nodes._DB_LOCK, nodes._db() as conn:  # noqa: SLF001
        for row in plain:
            conn.execute(
                "UPDATE nodes SET rtsp = ? WHERE id = ?",
                (nodes.protect_source(row["rtsp"]), row["id"]),
            )

    # Baca ulang: pastikan nilai terenkripsi bisa dibuka kembali.
    with nodes._db() as conn:  # noqa: SLF001
        after = conn.execute("SELECT id, rtsp FROM nodes ORDER BY id").fetchall()

    gagal = 0
    for row in after:
        if not row["rtsp"].startswith(nodes._ENC_PREFIX):
            print(f"FAIL {row['id']}: masih teks biasa")
            gagal += 1
            continue
        if nodes.reveal_source(row["rtsp"]).startswith(("rtsp://", "rtsps://", "http://", "https://")):
            print(f"PASS {row['id']}: terenkripsi dan bisa dibuka")
        else:
            print(f"FAIL {row['id']}: tidak bisa didekripsi")
            gagal += 1

    scrub_ok = True
    if gagal == 0:
        scrub_ok = scrub(path)

    if gagal == 0 and not keep_backup:
        backup.unlink(missing_ok=True)
        print("cadangan : dihapus (verifikasi lulus; pakai --keep-backup untuk menyimpan)")
    elif gagal:
        print(f"cadangan : disimpan di {backup} karena verifikasi gagal")

    print(f"HASIL: {len(after) - gagal}/{len(after)} lulus")
    return 0 if gagal == 0 and scrub_ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
