"""Pastikan Tailscale Funnel meneruskan port backend ke HTTPS publik.

Dipanggil oleh ``start-backend.bat`` supaya satu klik cukup untuk dua mode:

    lokal   : start-backend.bat + start-frontend.bat -> halaman 8787 memanggil
              http://127.0.0.1:5000 (config.js memilih alamat ini sendiri)
    Vercel  : start-backend.bat saja -> halaman Vercel memanggil
              https://<node>.<tailnet>.ts.net lewat Funnel

Yang dikerjakan:

1. Membaca nama node Tailscale (``tailscale status --json``) dan menulis
   ``PUBLIC_BACKEND_URL`` di ``backend/.env`` bila berbeda.
2. Menjalankan ulang ``scripts/sync_public_config.py`` bila
   ``frontend/js/public-config.js`` belum memuat alamat itu.
3. Menyalakan ``tailscale funnel --bg <port>`` bila belum ada.

Kegagalan Funnel tidak menggagalkan backend: mode lokal tetap jalan.

Perintah::

    python scripts/funnel_serve.py --port 5000
    python scripts/funnel_serve.py --reset      # tutup akses publik

Exit code: 0 funnel siap, 2 funnel belum diaktifkan di tailnet (link dicetak),
3 Tailscale tidak tersedia/berhenti, 1 kesalahan lain.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
ROOT_DIR = BASE_DIR.parent
ENV_FILE = BASE_DIR / ".env"
PUBLIC_FILE = ROOT_DIR / "frontend" / "js" / "public-config.js"
SYNC_SCRIPT = BASE_DIR / "scripts" / "sync_public_config.py"

ENABLE_LINK_RE = re.compile(r"https://login\.tailscale\.com/\S+")
ENABLE_TIMEOUT = 8  # detik; CLI menggantung menunggu konfirmasi di peramban


def tailscale_exe() -> str | None:
    candidates = [os.environ.get("TAILSCALE_EXE", ""), shutil.which("tailscale") or ""]
    for base in (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)")):
        if base:
            candidates.append(str(Path(base) / "Tailscale" / "tailscale.exe"))
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    return None


def run(exe: str, args: list[str], timeout: int = 25) -> subprocess.CompletedProcess:
    return subprocess.run([exe, *args], capture_output=True, text=True, timeout=timeout)


def node_url(exe: str) -> str:
    out = (run(exe, ["status", "--json"], 20).stdout or "").strip()
    data = json.loads(out) if out.startswith("{") else {}
    dns = str((data.get("Self") or {}).get("DNSName") or "").strip().rstrip(".")
    return f"https://{dns}" if dns else ""


def set_env(key: str, value: str) -> bool:
    lines = ENV_FILE.read_text(encoding="utf-8").splitlines() if ENV_FILE.exists() else []
    changed = False
    for index, line in enumerate(lines):
        if line.strip().startswith(key + "="):
            if line.strip() != f"{key}={value}":
                lines[index] = f"{key}={value}"
                changed = True
            break
    else:
        lines.append(f"{key}={value}")
        changed = True
    if changed:
        ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return changed


def funnel_entries(exe: str) -> list[tuple[str, str, bool]]:
    """Daftar (host, proxy, publik) dari ``tailscale funnel status --json``."""
    raw = (run(exe, ["funnel", "status", "--json"], 20).stdout or "").strip()
    data = json.loads(raw) if raw.startswith("{") else {}
    allow = data.get("AllowFunnel") or {}
    entries: list[tuple[str, str, bool]] = []
    for host, config in (data.get("Web") or {}).items():
        for handler in ((config or {}).get("Handlers") or {}).values():
            proxy = str((handler or {}).get("Proxy") or "")
            if proxy:
                entries.append((host, proxy, bool(allow.get(host))))
    return entries


def serves(entries: list[tuple[str, str, bool]], port: int) -> bool:
    return any(public and re.search(rf"(127\.0\.0\.1|localhost):{port}\b", proxy)
               for _, proxy, public in entries)


def enable(exe: str, port: int) -> tuple[str, int | None]:
    """Jalankan ``funnel --bg``; kembalikan (keluaran, exit code atau None bila timeout)."""
    try:
        result = run(exe, ["funnel", "--bg", "--yes", str(port)], ENABLE_TIMEOUT)
        return (result.stdout or "") + (result.stderr or ""), result.returncode
    except subprocess.TimeoutExpired as exc:
        text = exc.stdout or exc.stderr or ""
        if isinstance(text, bytes):
            text = text.decode(errors="replace")
        return str(text), None


def sync_frontend(url: str, force: bool) -> bool:
    current = PUBLIC_FILE.read_text(encoding="utf-8") if PUBLIC_FILE.exists() else ""
    if not force and url in current:
        return False
    if not SYNC_SCRIPT.exists():
        print(f"[funnel] {SYNC_SCRIPT} tidak ditemukan; public-config.js tidak diperbarui.")
        return False
    result = subprocess.run([sys.executable, str(SYNC_SCRIPT)], cwd=BASE_DIR,
                            capture_output=True, text=True)
    print((result.stdout or result.stderr or "").strip())
    return result.returncode == 0


def reset(exe: str) -> int:
    result = run(exe, ["funnel", "reset"], 20)
    message = ((result.stdout or "") + (result.stderr or "")).strip()
    print(f"[funnel] reset: {message or 'selesai'}")
    return 0


# ---------------------------------------------------------------------------
# Kesiapan backend + verifikasi jalur publik
# ---------------------------------------------------------------------------

def env_values() -> dict[str, str]:
    """Baca backend/.env tanpa dependensi tambahan (kunci=tanda kutip diabaikan)."""
    data: dict[str, str] = {}
    if not ENV_FILE.exists():
        return data
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        data[key.strip()] = value.strip().strip('"').strip("'")
    return data


def http_probe(url: str, method: str = "GET", origin: str = "") -> tuple[int, dict[str, str]]:
    """Kembalikan (status, header) tanpa melempar exception."""
    request = urllib.request.Request(url, method=method)
    if origin:
        request.add_header("Origin", origin)
        request.add_header("Access-Control-Request-Method", "GET")
        request.add_header("Access-Control-Request-Headers", "authorization")
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            return response.status, {k.lower(): v for k, v in response.headers.items()}
    except urllib.error.HTTPError as exc:
        return exc.code, {k.lower(): v for k, v in (exc.headers or {}).items()}
    except Exception:
        return 0, {}


def wait_health(port: int, timeout: int) -> bool:
    """Tunggu nginx+Flask menjawab /api/health sebelum Funnel dibuka.

    Tanpa ini Funnel menyala saat Flask masih impor modul, sehingga permintaan
    pertama dari halaman Vercel (termasuk login) menerima 502.
    """
    deadline = time.time() + timeout
    announced = False
    while time.time() < deadline:
        status, _ = http_probe(f"http://127.0.0.1:{port}/api/health")
        if status == 200:
            print(f"[funnel] backend siap di :{port} - Funnel dinyalakan.")
            return True
        if not announced:
            print(f"[funnel] menunggu backend di :{port} siap ...")
            announced = True
        time.sleep(0.5)
    return False


def verify(public_url: str) -> int:
    """Cek jalur publik: /api/health dan preflight CORS origin Vercel."""
    if not public_url:
        print("[funnel] verifikasi dilewati: URL publik tidak diketahui.")
        return 0

    ok = True
    status, _ = http_probe(public_url + "/api/health")
    print(f"[funnel] cek  {public_url}/api/health -> {status or 'tidak terjangkau'}")
    ok = ok and status == 200

    origins = [part.strip() for part in
               (env_values().get("ALLOWED_ORIGINS") or os.environ.get("ALLOWED_ORIGINS", "")).split(",")
               if part.strip()]
    vercel = [item for item in origins if item.startswith("https://") and ".vercel.app" in item]
    for origin in vercel[:2]:
        status, headers = http_probe(public_url + "/api/akun/me", "OPTIONS", origin)
        allow = headers.get("access-control-allow-origin", "-")
        good = status == 200 and allow == origin
        ok = ok and good
        print(f"[funnel] cek  preflight {origin} -> {status} ACAO={allow}")

    print("[funnel] verifikasi:", "OK" if ok else "ADA MASALAH - lihat pesan di atas")
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Siapkan Tailscale Funnel untuk backend.")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--reset", action="store_true", help="tutup akses publik lalu keluar")
    parser.add_argument("--wait-health", type=int, default=0, metavar="SECONDS",
                        help="tunggu /api/health di --port siap sebelum menyalakan Funnel")
    parser.add_argument("--verify", action="store_true",
                        help="setelah aktif, cek /api/health publik + preflight CORS")
    args = parser.parse_args()

    exe = tailscale_exe()
    if not exe:
        print("[funnel] tailscale.exe tidak ditemukan; mode Vercel dilewati, mode lokal tetap jalan.")
        return 3

    if args.reset:
        return reset(exe)

    if args.wait_health and not wait_health(args.port, args.wait_health):
        print(f"[funnel] backend belum menjawab di :{args.port} selama {args.wait_health} dtk;")
        print("         Funnel tidak dinyalakan supaya halaman Vercel tidak menerima 502.")
        return 4

    try:
        url = node_url(exe)
    except Exception as exc:  # JSON rusak / CLI gagal
        print(f"[funnel] gagal membaca status Tailscale: {exc}")
        return 3
    if not url:
        print("[funnel] Tailscale tidak berjalan atau belum login; mode Vercel dilewati.")
        return 3

    changed = set_env("PUBLIC_BACKEND_URL", url)
    if sync_frontend(url, force=changed):
        print("[funnel] public-config.js diperbarui - commit & push supaya Vercel ikut:")
        print("         git add frontend/js/public-config.js && git commit -m 'chore: backendBase Vercel' && git push")

    entries = funnel_entries(exe)
    if serves(entries, args.port):
        host = next(host for host, proxy, public in entries
                    if public and f":{args.port}" in proxy)
        print(f"[funnel] aktif: https://{host.split(':')[0]}/api/health -> 127.0.0.1:{args.port}")
        return verify(url) if args.verify else 0

    output, code = enable(exe, args.port)
    link = ENABLE_LINK_RE.search(output or "")
    if link:
        print("[funnel] Funnel belum diaktifkan untuk tailnet ini.")
        print(f"         Buka sekali: {link.group(0)}")
        print("         Setelah aktif, tutup dan jalankan ulang start-backend.bat.")
        return 2
    if code == 0:
        print(f"[funnel] aktif: {url}")
        return verify(url) if args.verify else 0

    detail = (output or "").strip().splitlines()
    print("[funnel] gagal menyalakan Funnel" + (f": {detail[0]}" if detail else "."))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
