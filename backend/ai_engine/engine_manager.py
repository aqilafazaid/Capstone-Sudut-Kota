"""Manajer proses engine AI (pengganti ffmpeg polos di streamer).

Antarmuka sengaja dibuat sama dengan ``streamer.hls.HlsManager`` supaya
``app.py`` bisa memilih backend stream tanpa mengubah kontrak API/frontend:

    manager.get(node_id).status()   -> dict
    manager.start(node_id, rtsp)    -> dict
    manager.stop(node_id) / purge(node_id) / prune(keep) / list() / stop_all()
    manager.ffmpeg_tersedia()

Satu node = satu proses ``ai_engine/main_ai.py``. Proses itu menulis HLS ke
``media/hls/<node_id>`` — folder yang sama yang dibaca frontend — sehingga
yang tampil di web adalah video yang sudah di-enhance dan diberi kotak YOLO.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Optional

from streamer import MEDIA_ROOT

AI_DIR = Path(__file__).resolve().parent
BACKEND_DIR = AI_DIR.parent
ENGINE = AI_DIR / "main_ai.py"
LOG_ROOT = Path(MEDIA_ROOT) / "_logs"
START_TIMEOUT = 40.0


def _truthy(value: str | None, default: bool = True) -> bool:
    if value is None or str(value).strip() == "":
        return default
    return str(value).strip().lower() not in {"0", "false", "no", "off"}


def enabled() -> bool:
    """AI aktif kalau ``AI_ENGINE`` true/auto dan engine + bobot tersedia."""
    raw = os.environ.get("AI_ENGINE")
    if raw is not None and str(raw).strip() != "":
        if not _truthy(raw):
            return False
    if not ENGINE.exists() or ENGINE.stat().st_size == 0:
        return False
    yolo = AI_DIR / "model_ai" / "Yolo" / "Model"
    return any(yolo.glob("*.pt"))


class AiStream:
    def __init__(self, name: str, out_root: Path = MEDIA_ROOT) -> None:
        self.name = name
        self.dir = Path(out_root) / name
        self.log_path = LOG_ROOT / f"{name}.log"
        self.process: Optional[subprocess.Popen] = None
        self.started_at: Optional[float] = None
        self.source = ""
        self.variant = (os.environ.get("AI_LOWLIGHT_MODEL") or "mobile_mirnet").replace("-", "_")
        self._lock = threading.RLock()

    # --- status --------------------------------------------------------
    @property
    def playlist(self) -> Path:
        return self.dir / "index.m3u8"

    @property
    def running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def stats(self) -> dict:
        """Isi ``ai_stats.json`` yang ditulis engine (atau {} bila belum ada)."""
        try:
            raw = (self.dir / "ai_stats.json").read_text(encoding="utf-8")
            data = json.loads(raw)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def status(self) -> dict:
        ai = self.stats()
        return {
            "name": self.name,
            "engine": "ai",
            "running": self.running,
            "transcoding": True,
            "uptime": round(time.time() - self.started_at, 1) if self.started_at and self.running else 0,
            "playlist": f"/hls/{self.name}/index.m3u8",
            "ready": self.playlist.exists(),
            "ai": ai,
        }

    # --- kontrol -------------------------------------------------------
    def _tail(self, lines: int = 8) -> str:
        try:
            text = self.log_path.read_text(encoding="utf-8", errors="replace").splitlines()
            return " | ".join(text[-lines:])
        except OSError:
            return ""

    def start(self, source_url: str, copy: bool = True) -> dict:  # noqa: ARG002 - kompatibilitas
        with self._lock:
            if self.running:
                return {"ok": True, "sudah_berjalan": True, **self.status()}

            channel = "".join(ch for ch in self.name if ch.isdigit())
            self.dir.mkdir(parents=True, exist_ok=True)
            LOG_ROOT.mkdir(parents=True, exist_ok=True)
            # Playlist lama tidak boleh dilayani selama model dimuat (bisa
            # menampilkan video sesi sebelumnya). Engine juga membersihkan
            # folder saat start; ini menutup jendela sebelum model siap.
            try:
                for old in self.dir.glob("*"):
                    if old.is_file():
                        old.unlink(missing_ok=True)
            except OSError as exc:
                return {"ok": False, "error": f"Folder HLS masih dipakai proses lain: {exc}", **self.status()}
            (self.dir / "stop.flag").unlink(missing_ok=True)

            cmd = [
                sys.executable,
                str(ENGINE),
                "--node-id", self.name,
                "--channel", channel,
                "--input", source_url,
                "--out", str(self.dir),
                "--lowlight", self.variant,
                # 0 = kanvas resolusi asli; AI bekerja di frame kecil terpisah.
                "--max-side", os.environ.get("AI_MAX_SIDE", "0"),
                "--ai-side", os.environ.get("AI_AI_SIDE", "960"),
            ]
            if _truthy(os.environ.get("AI_YOLO", "true")):
                pass
            else:
                cmd.append("--no-yolo")
            if not _truthy(os.environ.get("AI_LOWLIGHT", "true")):
                cmd.append("--no-lowlight")
            if _truthy(os.environ.get("AI_RTDB", "true")):
                pass
            else:
                cmd.append("--no-rtdb")

            log = open(self.log_path, "wb")
            try:
                env = dict(os.environ, PYTHONUNBUFFERED="1")
                self.process = subprocess.Popen(
                    cmd, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                    cwd=str(BACKEND_DIR), env=env,
                )
            finally:
                log.close()
            self.started_at = time.time()
            self.source = source_url

            deadline = time.time() + START_TIMEOUT
            while time.time() < deadline:
                if self.playlist.exists():
                    return {"ok": True, **self.status()}
                if not self.running:
                    return {"ok": False, "error": self._tail(), **self.status()}
                time.sleep(0.3)
            return {"ok": self.running, "error": "Playlist AI belum muncul (cek _logs).", **self.status()}

    def stop(self) -> dict:
        """Hentikan engine dengan sopan lewat ``stop.flag`` (menulis OFFLINE)."""
        with self._lock:
            if self.process is None:
                return {"ok": True, "sudah_berhenti": True, **self.status()}
            (self.dir / "stop.flag").write_text("stop", encoding="utf-8")
            deadline = time.time() + 12
            while time.time() < deadline and self.running:
                time.sleep(0.2)
            if self.running:
                self.process.terminate()
                try:
                    self.process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self.process.kill()
            self.process = None
            self.started_at = None
            return {"ok": True, **self.status()}

    def purge(self) -> dict:
        self.stop()
        removed = 0
        if self.dir.exists():
            for path in self.dir.rglob("*"):
                if path.is_file():
                    removed += 1
        shutil.rmtree(self.dir, ignore_errors=True)
        return {"ok": True, "removed_files": removed}


class AiManager:
    """Kumpulan AiStream, satu per node."""

    def __init__(self, out_root: Path = MEDIA_ROOT) -> None:
        self.out_root = Path(out_root)
        self._streams: dict[str, AiStream] = {}
        self._lock = threading.Lock()

    def get(self, name: str) -> AiStream:
        with self._lock:
            if name not in self._streams:
                self._streams[name] = AiStream(name, self.out_root)
            return self._streams[name]

    def start(self, name: str, rtsp_url: str, copy: bool = True) -> dict:
        return self.get(name).start(rtsp_url, copy=copy)

    def start_async(self, name: str, rtsp_url: str, copy: bool = True) -> threading.Thread:
        thread = threading.Thread(
            target=self.start, args=(name, rtsp_url), kwargs={"copy": copy},
            daemon=True, name=f"ai-{name}",
        )
        thread.start()
        return thread

    def stop(self, name: str) -> dict:
        return self.get(name).stop()

    def purge(self, name: str) -> dict:
        return self.get(name).purge()

    def prune(self, keep_names) -> list[str]:
        keep = {str(name) for name in keep_names if name}
        removed: list[str] = []
        with self._lock:
            stale = [name for name in self._streams if name not in keep]
        for name in stale:
            self._streams[name].purge()
            with self._lock:
                self._streams.pop(name, None)
            removed.append(name)

        root = Path(self.out_root)
        if root.exists():
            for folder in root.iterdir():
                if not folder.is_dir() or folder.name in keep or folder.name.startswith("_"):
                    continue
                shutil.rmtree(folder, ignore_errors=True)
                removed.append(folder.name)
        return removed

    def list(self) -> list[dict]:
        with self._lock:
            return [stream.status() for stream in self._streams.values()]

    def stop_all(self) -> None:
        for stream in list(self._streams.values()):
            stream.stop()

    def stats(self, name: str) -> dict:
        return self.get(name).stats()

    @staticmethod
    def ffmpeg_tersedia() -> bool:
        return shutil.which("ffmpeg") is not None


manager = AiManager(MEDIA_ROOT)
