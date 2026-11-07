"""Sudut Kota — REST API lokal (Flask).

Dijalankan di terminal terpisah dari frontend:

    cd backend
    python app.py          # http://127.0.0.1:5000

nginx menjadi satu-satunya pintu masuk HTTP: ia menyajikan `frontend/` dan
mem-proxy `/api` + `/hls` ke proses ini. Flask tetap bind 127.0.0.1 supaya
tidak pernah terekspos langsung.

Konfigurasi kamera disimpan di SQLite (`NODE_DB`). URL RTSP tidak pernah
dikirim ke peramban kecuali lewat endpoint detail yang dilindungi
`X-SK-Token`; daftar node hanya memuat `hls_url`.
"""

from __future__ import annotations

import atexit
import hmac
import os
import time
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from urllib.parse import quote, urljoin, urlparse
from urllib.request import urlopen

from dotenv import load_dotenv
from flask import Flask, Response, jsonify, request, send_file
from flask_cors import CORS

import nodes as node_store
from streamer import MEDIA_ROOT as HLS_ROOT
from streamer import manager as hls_manager

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

APP_VERSION = "0.2.0"
STARTED_AT = time.time()
HOST = os.environ.get("API_HOST", "127.0.0.1")
PORT = int(os.environ.get("API_PORT", "5000"))
FFMPEG_OK = hls_manager.ffmpeg_tersedia()

MODELS_DIR = BASE_DIR / "ai_engine" / "model_ai"
LOWLIGHT_DIR = MODELS_DIR / "LowLight"
YOLO_DIR = MODELS_DIR / "Yolo"

# Host yang boleh diproksikan. Kosong = hanya localhost (aman untuk pengujian).
PROXY_ALLOWED_HOSTS = {
    h.strip() for h in os.environ.get("PROXY_ALLOWED_HOSTS", "").split(",") if h.strip()
} or {"127.0.0.1", "localhost"}


def _truthy(value: object) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _origins() -> list[str]:
    raw = os.environ.get(
        "ALLOWED_ORIGINS",
        "http://127.0.0.1:8080,http://localhost:8080,"
        "http://127.0.0.1:8787,http://localhost:8787",
    )
    return [part.strip() for part in raw.split(",") if part.strip()]


# Origin frontend yang diizinkan (Vercel ditambahkan lewat ALLOWED_ORIGINS).
ALLOWED_ORIGINS = _origins()

# Kunci Web SDK bersifat publik; endpoint config hanya melaporkan ada/tidak.
REQUIRED_ENV = [
    "FIREBASE_API_KEY",
    "FIREBASE_DATABASE_URL",
    "FIREBASE_PROJECT_ID",
    "FIREBASE_APP_ID",
]


def _with_stream(node: dict) -> dict:
    """Tambahkan status ffmpeg yang sebenarnya ke data node publik."""
    data = dict(node)
    stream = hls_manager.get(node["id"]).status()
    data["stream"] = stream
    if not data.get("aktif"):
        data["status"] = "OFFLINE"
    elif stream.get("running"):
        data["status"] = "ONLINE"
    else:
        data["status"] = "STANDBY"
    return data


def _without_rtsp(node: dict) -> dict:
    """Respons tulis tidak boleh membawa kredensial kamera ke cache browser."""
    return {key: value for key, value in node.items() if key != "rtsp"}


def _start_node(node: dict) -> None:
    if not FFMPEG_OK:
        return
    hls_manager.start_async(node["id"], node["rtsp"])


def _stop_node(node_id: str) -> None:
    hls_manager.get(node_id).stop()


def _write_failure():
    """None bila token benar; response error bila tidak."""
    expected = os.environ.get("API_WRITE_TOKEN", "").strip()
    if not expected:
        return jsonify(error="API_WRITE_TOKEN belum diatur di backend/.env."), 503
    supplied = request.headers.get("X-SK-Token", "")
    if not hmac.compare_digest(supplied, expected):
        return jsonify(error="Token operator tidak valid atau belum diisi."), 401
    return None


def require_write_token(view):
    """Lindungi POST/PUT/DELETE dengan header X-SK-Token."""

    @wraps(view)
    def wrapper(*args, **kwargs):
        failure = _write_failure()
        if failure is not None:
            return failure
        return view(*args, **kwargs)

    return wrapper


def create_app() -> Flask:
    app = Flask(__name__)
    CORS(
        app,
        resources={r"/api/*": {"origins": ALLOWED_ORIGINS}},
        allow_headers=["Content-Type", "X-SK-Token"],
    )

    node_store.init_db()
    node_store.seed_defaults()

    @app.errorhandler(node_store.NodeError)
    def handle_node_error(error: node_store.NodeError):
        return jsonify(error=error.message), error.status

    @app.after_request
    def hls_cors(response):
        # hls.js mengambil playlist & segmen dari origin lain (halaman Vercel).
        if request.path.startswith("/hls/"):
            response.headers["Access-Control-Allow-Origin"] = "*"
        return response

    @app.get("/api/health")
    def health():
        return jsonify(
            status="ok",
            service="sudut-kota-backend",
            version=APP_VERSION,
            time=datetime.now(timezone.utc).isoformat(),
        )

    @app.get("/api/config")
    def config_status():
        """Status konfigurasi publik. Tidak pernah mengembalikan nilai rahasia."""
        return jsonify(
            env_file=(BASE_DIR / ".env").exists(),
            configured={key: bool(os.environ.get(key)) for key in REQUIRED_ENV},
            allow_test_sources=node_store.allow_test_sources(),
            stream_autostart=_truthy(os.environ.get("STREAM_AUTOSTART", "true")),
            write_token_required=bool(os.environ.get("API_WRITE_TOKEN", "").strip()),
        )

    @app.get("/api/status")
    def status():
        """Ringkasan kesiapan backend: model, .env, database, dan runtime."""
        lowlight = sorted(
            p.name for p in LOWLIGHT_DIR.glob("*")
            if p.is_file() and p.suffix in {".pt", ".pth"}
        )
        yolo = sorted(p.name for p in YOLO_DIR.glob("*.pt"))
        return jsonify(
            service="sudut-kota-backend",
            version=APP_VERSION,
            uptime_seconds=round(time.time() - STARTED_AT, 1),
            env_file=(BASE_DIR / ".env").exists(),
            configured={key: bool(os.environ.get(key)) for key in REQUIRED_ENV},
            node_db=str(node_store.db_path()),
            nodes=node_store.count_nodes(),
            models={"lowlight": lowlight, "yolo": yolo},
        )

    # --- Konfigurasi kamera -------------------------------------------
    @app.get("/api/nodes")
    def nodes_list():
        return jsonify([_with_stream(node) for node in node_store.list_nodes()])

    @app.get("/api/nodes/<node_id>")
    @require_write_token
    def node_detail(node_id):
        return jsonify(_with_stream(node_store.get_node(node_id)))

    @app.post("/api/nodes")
    @require_write_token
    def node_create():
        node = node_store.create_node(request.get_json(silent=True))
        if node["aktif"]:
            _start_node(node)
        return jsonify(_with_stream(_without_rtsp(node))), 201

    @app.put("/api/nodes/<node_id>")
    @require_write_token
    def node_update(node_id):
        before = node_store.get_node(node_id)
        node = node_store.update_node(node_id, request.get_json(silent=True))

        if not node["aktif"]:
            _stop_node(node_id)
        elif (
            before["rtsp"] != node["rtsp"]
            or not before["aktif"]
            or not hls_manager.get(node_id).running
        ):
            _stop_node(node_id)
            _start_node(node)

        return jsonify(_with_stream(_without_rtsp(node)))

    @app.delete("/api/nodes/<node_id>")
    @require_write_token
    def node_delete(node_id):
        node_store.get_node(node_id)
        _stop_node(node_id)
        node_store.delete_node(node_id)
        return jsonify(ok=True, id=node_id)

    @app.post("/api/nodes/reset")
    @require_write_token
    def node_reset():
        hls_manager.stop_all()
        node_store.reset_nodes()
        started = []
        for node in node_store.list_nodes():
            if node["aktif"]:
                _start_node(node_store.get_node(node["id"]))
                started.append(node["id"])
        return jsonify(
            nodes=[_with_stream(node) for node in node_store.list_nodes()],
            started=started,
        )

    # --- Proxy HLS (playlist + segmen) -------------------------------
    @app.get("/api/proxy")
    def proxy():
        """Proxy HLS agar halaman HTTPS bisa memutar stream HTTP.

        Hanya host di PROXY_ALLOWED_HOSTS yang dilayani (default: localhost).
        URI di dalam playlist ditulis ulang supaya segmen juga lewat proxy.
        """
        target = request.args.get("url", "")
        if not target:
            return jsonify(error="Parameter url wajib diisi."), 400

        parsed = urlparse(target)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            return jsonify(error="URL harus http/https."), 400
        if parsed.hostname not in PROXY_ALLOWED_HOSTS:
            return jsonify(error=f"Host {parsed.hostname} tidak diizinkan."), 403

        try:
            with urlopen(target, timeout=10) as upstream:
                body = upstream.read()
                content_type = upstream.headers.get("Content-Type", "application/octet-stream")
        except Exception as exc:
            return jsonify(error=f"Gagal mengambil {target}: {exc}"), 502

        if "mpegurl" in content_type or parsed.path.endswith(".m3u8"):
            text = body.decode("utf-8", errors="replace")
            rewritten = []
            for line in text.splitlines():
                if line.startswith("#") or not line.strip():
                    rewritten.append(line)
                    continue
                absolute = urljoin(target, line.strip())
                rewritten.append(f"/api/proxy?url={quote(absolute, safe='')}")
            body = "\n".join(rewritten).encode("utf-8")
            content_type = "application/vnd.apple.mpegurl"

        response = Response(body, mimetype=content_type)
        response.headers["Access-Control-Allow-Origin"] = "*"
        return response

    # --- HLS: ffmpeg mengubah RTSP menjadi m3u8 ------------------------
    @app.get("/hls/<path:filename>")
    def hls_file(filename):
        """Sajikan playlist dan segmen HLS hasil ffmpeg."""
        safe = (HLS_ROOT / filename).resolve()
        if HLS_ROOT.resolve() not in safe.parents or not safe.is_file():
            return jsonify(error="Berkas HLS tidak ditemukan."), 404

        content_type = "application/vnd.apple.mpegurl" if safe.suffix == ".m3u8" else "video/mp2t"
        response = send_file(safe, mimetype=content_type, conditional=True)
        # Playlist berubah tiap beberapa detik: jangan pernah di-cache.
        response.headers["Cache-Control"] = "no-store" if safe.suffix == ".m3u8" else "max-age=30"
        return response

    @app.get("/api/streams")
    def streams():
        return jsonify(
            ffmpeg=FFMPEG_OK,
            alur="RTSP -> backend lokal (ffmpeg) -> HLS -> peramban",
            streams=hls_manager.list(),
        )

    @app.post("/api/streams/<name>")
    @require_write_token
    def stream_start(name):
        payload = request.get_json(silent=True) or {}
        rtsp_url = (payload.get("rtsp") or "").strip()
        if not rtsp_url:
            rtsp_url = node_store.get_node(name)["rtsp"]
        rtsp_url = node_store.validate_source(rtsp_url)

        if not FFMPEG_OK:
            return jsonify(error="ffmpeg tidak ditemukan di PATH."), 503

        copy = bool(payload.get("copy", True))
        result = hls_manager.start(name, rtsp_url, copy=copy)
        return jsonify(result), (200 if result.get("ok") else 502)

    @app.delete("/api/streams/<name>")
    @require_write_token
    def stream_stop(name):
        return jsonify(hls_manager.stop(name))

    @app.errorhandler(404)
    def not_found(_error):
        return jsonify(error="Endpoint tidak ditemukan."), 404

    return app


app = create_app()
atexit.register(hls_manager.stop_all)


def start_active_streams() -> list[str]:
    """Jalankan ffmpeg untuk semua node aktif; dipakai saat app.py start."""
    if not FFMPEG_OK:
        return []
    started = []
    for node in node_store.list_nodes():
        if not node["aktif"]:
            continue
        try:
            _start_node(node_store.get_node(node["id"]))
        except node_store.NodeError:
            continue
        started.append(node["id"])
    return started


if __name__ == "__main__":
    if _truthy(os.environ.get("STREAM_AUTOSTART", "true")):
        print(f"[STREAM] Autostart: {', '.join(start_active_streams()) or '-'}")
    print(f"Sudut Kota API v{APP_VERSION} -> http://{HOST}:{PORT}")
    app.run(host=HOST, port=PORT, debug=False)
