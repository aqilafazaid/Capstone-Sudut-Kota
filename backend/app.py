"""Sudut Kota — REST API lokal (Flask).

Dijalankan di terminal terpisah dari frontend:

    cd backend
    python app.py          # http://127.0.0.1:5000

nginx menjadi satu-satunya pintu masuk HTTP: ia menyajikan `frontend/` dan
mem-proxy `/api` ke proses ini (playlist & segmen HLS dilayani nginx langsung
dari disk). Flask tetap bind 127.0.0.1 supaya tidak pernah terekspos langsung.

Otorisasi:

- Baca publik: daftar node (tanpa RTSP), status stream, playlist/segmen HLS.
- Fitur `dashboard` (bawaan `admin`, `teknisi`): CRUD node, start/stop stream, detail node.
- Fitur `ai` (bawaan `admin`, `teknisi`): panel Kontrol Modul AI di halaman CCTV.
- Fitur `akun` (bawaan `admin`): CRUD akun dan penetapan akses fitur.
- Setiap akun punya field `akses` di profilnya; Administrator bisa memberi atau
  mencabut fitur lewat halaman Kelola Akun. Peran hanya menetapkan nilai bawaan,
  `akses` adalah sumber kebenaran (lihat `auth.require_feature`).

Identitas operator diverifikasi dari Firebase ID token (lihat `auth.py`), bukan
token bersama. URL RTSP tidak pernah dikirim ke peramban kecuali lewat endpoint
detail yang dilindungi.
"""

from __future__ import annotations

import atexit
import logging
import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, g, jsonify, request, send_file
from flask_cors import CORS

import accounts
import auth
import nodes as node_store
from social import instagram as social_instagram
import stats as stats_store
from streamer import MEDIA_ROOT as HLS_ROOT
from streamer import manager as hls_manager

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

APP_VERSION = "0.4.0"
STARTED_AT = time.time()
HOST = os.environ.get("API_HOST", "127.0.0.1")
PORT = int(os.environ.get("API_PORT", "5000"))
FFMPEG_OK = hls_manager.ffmpeg_tersedia()

MODELS_DIR = BASE_DIR / "ai_engine" / "model_ai"
LOWLIGHT_DIR = MODELS_DIR / "LowLight"
YOLO_DIR = MODELS_DIR / "Yolo"


def _truthy(value: object) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


# Pola origin Vercel milik proyek ini: domain produksi dan setiap URL preview
# (`capstone-sudut-kota-<hash>.vercel.app`) yang dibuat otomatis setelah push.
# Tanpa pola ini, login dari URL preview gagal karena preflight tidak membawa
# Access-Control-Allow-Origin (halaman melaporkan "gagal menghubungi server").
DEFAULT_ORIGIN_PATTERNS = [r"https://capstone-sudut-kota[a-z0-9-]*\.vercel\.app"]


def _origins() -> list[str]:
    raw = os.environ.get(
        "ALLOWED_ORIGINS",
        "http://127.0.0.1:8080,http://localhost:8080,"
        "http://127.0.0.1:8787,http://localhost:8787",
    )
    origins = [part.strip() for part in raw.split(",") if part.strip()]
    extra = os.environ.get("ALLOWED_ORIGIN_PATTERNS", "")
    origins.extend(part.strip() for part in extra.split(",") if part.strip())
    origins.extend(DEFAULT_ORIGIN_PATTERNS)
    return origins


# Origin frontend yang diizinkan (domain Vercel ditambahkan lewat ALLOWED_ORIGINS).
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


def _stop_node(node_id: str, purge: bool = False) -> None:
    """Hentikan ffmpeg; `purge=True` sekaligus menghapus playlist lama.

    Playlist yang dibiarkan akan tetap dilayani di `/hls/<id>/index.m3u8`,
    sehingga peramban memutar konfigurasi lama setelah node diubah/dihapus.
    """
    if purge:
        hls_manager.purge(node_id)
    else:
        hls_manager.stop(node_id)


def create_app() -> Flask:
    app = Flask(__name__)
    CORS(
        app,
        resources={r"/api/*": {"origins": ALLOWED_ORIGINS}},
        allow_headers=["Authorization", "Content-Type"],
        # Halaman Vercel (HTTPS publik) yang dibuka di mesin operator memanggil
        # backend lewat loopback/tailnet; Chrome menolak tanpa header ini.
        allow_private_network=True,
    )

    node_store.init_db()

    auth.register_error_handlers(app)
    accounts.register_error_handlers(app)

    @app.errorhandler(node_store.NodeError)
    def handle_node_error(error: node_store.NodeError):
        return jsonify(error=error.message), error.status

    @app.after_request
    def hls_cors(response):
        # hls.js mengambil playlist & segmen dari origin lain (halaman Vercel).
        # Endpoint ini publik; yang dilindungi adalah endpoint tulis.
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
            auth_configured=auth.configured(),
            allow_test_sources=node_store.allow_test_sources(),
            stream_autostart=_truthy(os.environ.get("STREAM_AUTOSTART", "true")),
        )

    @app.get("/api/status")
    @auth.require_feature("dashboard")
    def status():
        """Ringkasan kesiapan backend. Operator saja: memuat path & daftar model."""
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
            auth_configured=auth.configured(),
            node_db=str(node_store.db_path()),
            nodes=node_store.count_nodes(),
            models={"lowlight": lowlight, "yolo": yolo},
        )

    # --- Konfigurasi kamera -------------------------------------------
    @app.get("/api/nodes")
    def nodes_list():
        """Publik: daftar node tanpa URL RTSP."""
        return jsonify([_with_stream(node) for node in node_store.list_nodes()])

    @app.get("/api/nodes/<node_id>")
    @auth.require_feature("dashboard")
    def node_detail(node_id):
        return jsonify(_with_stream(node_store.get_node(node_id)))

    @app.post("/api/nodes")
    @auth.require_feature("dashboard")
    def node_create():
        node = node_store.create_node(request.get_json(silent=True))
        if node["aktif"]:
            _start_node(node)
        return jsonify(_with_stream(_without_rtsp(node))), 201

    @app.put("/api/nodes/<node_id>")
    @auth.require_feature("dashboard")
    def node_update(node_id):
        before = node_store.get_node(node_id)
        node = node_store.update_node(node_id, request.get_json(silent=True))

        if not node["aktif"]:
            _stop_node(node_id, purge=True)
        elif (
            before["rtsp"] != node["rtsp"]
            or not before["aktif"]
            or not hls_manager.get(node_id).running
        ):
            # Folder dibersihkan dulu: segmen & playlist sumber lama tidak boleh
            # tercampur dengan hasil ffmpeg untuk URL RTSP yang baru.
            _stop_node(node_id, purge=True)
            _start_node(node)

        return jsonify(_with_stream(_without_rtsp(node)))

    @app.delete("/api/nodes/<node_id>")
    @auth.require_feature("dashboard")
    def node_delete(node_id):
        node_store.get_node(node_id)
        # Folder HLS ikut dihapus: tanpa ini /hls/<id>/index.m3u8 tetap
        # dilayani untuk node yang sudah tidak ada.
        _stop_node(node_id, purge=True)
        node_store.delete_node(node_id)
        return jsonify(ok=True, id=node_id)

    @app.post("/api/nodes/reset")
    @auth.require_feature("dashboard")
    def node_reset():
        hls_manager.stop_all()
        node_store.reset_nodes()
        # Node lama (ID berbeda) tidak boleh meninggalkan folder HLS-nya.
        hls_manager.prune([node["id"] for node in node_store.list_nodes()])
        started = []
        for node in node_store.list_nodes():
            if node["aktif"]:
                _start_node(node_store.get_node(node["id"]))
                started.append(node["id"])
        return jsonify(
            nodes=[_with_stream(node) for node in node_store.list_nodes()],
            started=started,
        )

    # --- Akun operator -------------------------------------------------
    @app.get("/api/akun/me")
    @auth.require_role()
    def akun_me():
        user = auth.authenticate(required=True)
        profile = auth.profile_of(user["uid"])
        if profile is None:
            return jsonify(error="Profil belum dibuat.", uid=user["uid"]), 404
        return jsonify(profile)

    @app.post("/api/akun/self")
    @auth.require_role()
    def akun_self():
        user = auth.authenticate(required=True)
        profile = accounts.ensure_self_profile(
            user["uid"], user.get("email", ""), request.get_json(silent=True) or {}
        )
        return jsonify(profile), 201

    @app.get("/api/akun")
    @auth.require_feature("akun")
    def akun_list():
        return jsonify(accounts.list_accounts())

    @app.post("/api/akun")
    @auth.require_feature("akun")
    def akun_create():
        return jsonify(accounts.create_account(request.get_json(silent=True))), 201

    @app.put("/api/akun/<uid>")
    @auth.require_feature("akun")
    def akun_update(uid):
        return jsonify(accounts.update_account(uid, request.get_json(silent=True),
                                               g.user.get("uid", "")))

    @app.delete("/api/akun/<uid>")
    @auth.require_feature("akun")
    def akun_delete(uid):
        user = auth.authenticate(required=True)
        return jsonify(accounts.delete_account(uid, user["uid"]))

    # --- Statistik (agregat telemetri RTDB) -----------------------------
    @app.get("/api/stats/telemetry")
    def stats_telemetry():
        """Publik: agregat per jam/hari dari RTDB, tanpa data mentah kamera.

        ``?days=N`` membatasi rentang (default ``STATS_MAX_DAYS``); halaman
        Statistik memakai default karena periode terpanjangnya "Seluruhnya".
        """
        raw_days = request.args.get("days")
        try:
            days = int(raw_days) if raw_days else None
        except ValueError:
            days = None
        response = jsonify(stats_store.read_telemetry(days))
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/stats/live")
    def stats_live():
        """Publik: snapshot telemetri terakhir tiap node, langsung dari RTDB.

        Dipakai kartu statistik halaman CCTV. Tidak ada angka simulasi: node
        yang belum mengirim snapshot tampil 0 dengan status OFFLINE.
        """
        return jsonify(stats_store.live_snapshots())

    # --- Media sosial: kiriman Instagram asli ---------------------------
    @app.get("/api/sosmed/instagram")
    def sosmed_instagram():
        """Publik: kiriman Instagram asli, berhalaman, dengan cache.

        Scrape hanya dijalankan ketika cache kedaluwarsa (IG_CACHE_SECONDS);
        permintaan berikutnya dilayani dari data/instagram-cache.json.
        """
        try:
            page_no = int(request.args.get("page", "1"))
        except ValueError:
            page_no = 1
        try:
            per_page = int(request.args.get("per_page", "6"))
        except ValueError:
            per_page = 6
        result = social_instagram.page(page_no, per_page)
        response = jsonify(result)
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/api/sosmed/instagram/image/<code>.jpg")
    def sosmed_instagram_image(code):
        path = social_instagram.image_file(code)
        if not path:
            return jsonify(error="Gambar tidak tersedia."), 404
        return send_file(path, mimetype="image/jpeg", max_age=3600)

    @app.post("/api/stats/collect")
    @auth.require_feature("dashboard")
    def stats_collect():
        result = stats_store.collect_once()
        return jsonify(result), (200 if result.get("ok") else 503)

    # --- HLS: dipakai saat dev tanpa nginx (python -m http.server 8787) --
    @app.get("/hls/<path:filename>")
    def hls_file(filename):
        """Sajikan playlist dan segmen HLS hasil ffmpeg."""
        safe = (HLS_ROOT / filename).resolve()
        if HLS_ROOT.resolve() not in safe.parents or not safe.is_file():
            return jsonify(error="Berkas HLS tidak ditemukan."), 404
        if safe.suffix not in {".m3u8", ".ts"}:
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
    @auth.require_feature("dashboard")
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
    @auth.require_feature("dashboard")
    def stream_stop(name):
        # Playlist lama ikut dibuang supaya pemutar tidak memutar stream beku.
        return jsonify(hls_manager.purge(name))

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
    nodes = node_store.list_nodes()
    # Sisa folder dari sesi sebelumnya (node dihapus/ID berubah) dibuang dulu.
    hls_manager.prune([node["id"] for node in nodes])
    started = []
    for node in nodes:
        if not node["aktif"]:
            continue
        try:
            _start_node(node_store.get_node(node["id"]))
        except node_store.NodeError:
            continue
        started.append(node["id"])
    return started


WATCHDOG_INTERVAL = float(os.environ.get("STREAM_WATCHDOG_INTERVAL", "5"))


def start_stream_watchdog():
    """Nyalakan ulang ffmpeg yang mati (kamera putus / proses crash).

    Tanpa ini playlist berhenti bertambah dan pemutar membeku sampai halaman
    dimuat ulang. Backoff per node mencegah spawn berulang saat kamera benar-
    benar mati, dan prune() membuang stream untuk node yang sudah dihapus.
    """
    if not FFMPEG_OK or not _truthy(os.environ.get("STREAM_WATCHDOG", "true")):
        return None
    if not _truthy(os.environ.get("STREAM_AUTOSTART", "true")):
        return None

    def loop() -> None:
        backoff: dict[str, list[float]] = {}
        while True:
            time.sleep(WATCHDOG_INTERVAL)
            try:
                nodes = node_store.list_nodes()
            except Exception:
                continue

            for node in nodes:
                node_id = node["id"]
                if not node["aktif"]:
                    backoff.pop(node_id, None)
                    continue

                if hls_manager.get(node_id).running:
                    backoff.pop(node_id, None)
                    continue

                now = time.time()
                state = backoff.get(node_id)
                if state and now < state[0]:
                    continue

                delay = min(state[1] * 2 if state else 10.0, 60.0)
                backoff[node_id] = [now + delay, delay]
                try:
                    _start_node(node_store.get_node(node_id))
                except node_store.NodeError:
                    continue

            hls_manager.prune([node["id"] for node in nodes if node["aktif"]])

    thread = threading.Thread(target=loop, daemon=True, name="hls-watchdog")
    thread.start()
    print(f"[STREAM] Watchdog aktif (interval {WATCHDOG_INTERVAL:g} dtk).")
    return thread


def _access_log_handler() -> Path | None:
    """Access log werkzeug ke berkas, bukan ke konsol.

    Konsol Windows berhenti menerima tulisan saat jendelanya sedang diseleksi
    (QuickEdit/Mark). ``logging`` menahan lock saat menulis, jadi satu baris log
    yang macet membuat seluruh thread request ikut menunggu dan server tampak
    mati walau socket-nya masih LISTENING. Menulis ke berkas menghilangkan
    ketergantungan itu.
    """
    log_dir = BASE_DIR / "logs"
    try:
        log_dir.mkdir(exist_ok=True)
        handler = logging.FileHandler(log_dir / "backend.log", encoding="utf-8")
    except OSError:
        return None
    handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
    logger = logging.getLogger("werkzeug")
    logger.handlers = [handler]
    logger.propagate = False
    logger.setLevel(logging.INFO)
    return log_dir / "backend.log"


if __name__ == "__main__":
    access_log = _access_log_handler()
    if _truthy(os.environ.get("STREAM_AUTOSTART", "true")):
        print(f"[STREAM] Autostart: {', '.join(start_active_streams()) or '-'}")
    start_stream_watchdog()
    if not _truthy(os.environ.get("STATS_COLLECTOR", "true")):
        print("[STATS] Kolektor dimatikan lewat STATS_COLLECTOR=false.")
    else:
        stats_store.start_collector()
    print(f"Sudut Kota API v{APP_VERSION} -> http://{HOST}:{PORT}")
    if access_log:
        print(f"[backend] access log: {access_log}  (jangan menyeleksi jendela ini)")
    app.run(host=HOST, port=PORT, debug=False)
