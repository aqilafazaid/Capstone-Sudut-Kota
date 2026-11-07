"""Audit batas akses RTSP vs HLS.

Kontrak yang diperiksa:

- Pengunjung tanpa token tetap bisa streaming: ``/api/nodes`` memberi
  ``hls_url`` dan berkas ``/hls/<id>/index.m3u8`` dapat diambil.
- URL RTSP hanya untuk admin/teknisi lewat ``GET /api/nodes/<id>``;
  visitor 403, tanpa token 401.
- Tidak ada respons publik yang memuat ``rtsp://``.
- Berkas non-media di folder HLS (mis. ``ffmpeg.log``) tidak bisa diunduh dan
  path traversal ditolak.

Tidak menyentuh Firebase: verifier dan pembaca peran disuntik seperti unit
test (``auth.set_verifier`` / ``auth.set_role_resolver``), jadi aman dijalankan
kapan saja tanpa kredensial.

    cd backend
    .venv/Scripts/python.exe scripts/audit_akses.py

Exit code 0 bila semua kontrak terpenuhi, 1 bila ada yang bocor.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app  # noqa: E402
import auth  # noqa: E402

PERAN_UJI = {"visitor", "teknisi", "admin"}
PUBLIK = ("/api/health", "/api/config", "/api/nodes", "/api/streams")
HASIL: list[tuple[bool, str, str]] = []


def catat(ok: bool, label: str, detail: str = "") -> None:
    HASIL.append((ok, label, detail))


def klien():
    auth.set_verifier(lambda token: {"uid": token, "email": token + "@uji.local"})
    auth.set_role_resolver(lambda uid: uid if uid in PERAN_UJI else "visitor")
    auth.reset_cache()
    return app.app.test_client()


def kode(client, method: str, path: str, who: str | None = None) -> int:
    headers = {"Authorization": "Bearer " + who} if who else {}
    return client.open(path, method=method, headers=headers).status_code


def main() -> int:
    client = klien()

    # 1. Semua orang bisa streaming: daftar node memuat hls_url, tanpa rtsp.
    nodes = client.get("/api/nodes").get_json() or []
    catat(bool(nodes), "GET /api/nodes berisi node", f"{len(nodes)} node")
    catat(all("hls_url" in n for n in nodes), "setiap node punya hls_url")
    catat(not any("rtsp" in n for n in nodes), "payload /api/nodes tanpa field rtsp")

    # 2. Playlist HLS tidak menuntut login (404 hanya bila stream belum pernah jalan).
    for node in nodes[:2]:
        status = kode(client, "GET", node["hls_url"])
        catat(status in (200, 404), f"GET {node['hls_url']} tanpa token", f"HTTP {status}")

    # 3. Detail node (satu-satunya sumber RTSP) mengikuti peran.
    node_id = nodes[0]["id"] if nodes else "cam_9"
    harapan = {None: 401, "visitor": 403, "teknisi": 200, "admin": 200}
    for who, ingin in harapan.items():
        status = kode(client, "GET", f"/api/nodes/{node_id}", who)
        catat(status == ingin, f"GET /api/nodes/{node_id} sebagai {who or 'anonim'}",
              f"HTTP {status} (harap {ingin})")

    rtsp_teknisi = client.get(f"/api/nodes/{node_id}",
                              headers={"Authorization": "Bearer teknisi"}).get_json() or {}
    catat("rtsp" in rtsp_teknisi, "teknisi menerima URL rtsp")
    catat("hls_url" in rtsp_teknisi, "detail juga membawa hls_url")

    # 4. Tidak ada respons publik yang membocorkan URL RTSP.
    for path in PUBLIK + (f"/hls/{node_id}/index.m3u8", "/api/tidak-ada"):
        body = client.get(path).get_data(as_text=True)
        catat("rtsp://" not in body, f"{path} tidak memuat rtsp://")

    # 5. Berkas non-media di folder HLS tidak bisa diunduh; traversal ditolak.
    for path in (f"/hls/{node_id}/ffmpeg.log", "/hls/../.env", f"/hls/{node_id}/..%2f..%2f.env"):
        status = kode(client, "GET", path)
        catat(status == 404, f"GET {path} ditolak", f"HTTP {status}")

    # 6. Endpoint tulis tetap tertutup untuk anonim dan visitor.
    for method, path in (("POST", "/api/nodes"), ("POST", "/api/streams/" + node_id),
                         ("DELETE", "/api/nodes/" + node_id)):
        for who, ingin in ((None, 401), ("visitor", 403)):
            status = kode(client, method, path, who)
            catat(status == ingin, f"{method} {path} sebagai {who or 'anonim'}",
                  f"HTTP {status} (harap {ingin})")

    gagal = [item for item in HASIL if not item[0]]
    for ok, label, detail in HASIL:
        print(f"[{'OK  ' if ok else 'BOCOR'}] {label}" + (f" - {detail}" if detail else ""))
    print()
    if gagal:
        print(f"{len(gagal)} kontrak gagal dari {len(HASIL)} pemeriksaan.")
        return 1
    print(f"Semua {len(HASIL)} pemeriksaan lolos: streaming publik, RTSP hanya admin/teknisi.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
