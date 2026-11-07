"""RTSP -> HLS dengan FFmpeg.

Alur yang dipakai sistem ini:

    CCTV --RTSP--> backend lokal (ffmpeg) --HLS--> Vercel --HLS--> peramban

FFmpeg membaca RTSP lalu menulis playlist `index.m3u8` + segmen `.ts` ke
`backend/media/hls/<nama>/`. Flask menyajikan folder itu di `/hls/<nama>/...`,
jadi peramban cukup memutar satu URL m3u8 — sama untuk mode AI maupun non-AI.

Dua mode keluaran:
- `copy=True`  : video diteruskan apa adanya (hemat CPU, sumber sudah H.264)
- `copy=False` : di-transcode H.264 (dipakai bila sumber bukan H.264, atau
                 saat frame sudah dimodifikasi engine AI)
"""

from __future__ import annotations

import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional

MEDIA_ROOT = Path(__file__).resolve().parent.parent / "media" / "hls"


class HlsStream:
    """Satu proses ffmpeg untuk satu kamera."""

    def __init__(self, name: str, out_root: Path = MEDIA_ROOT, hls_time: int = 2, segments: int = 6) -> None:
        self.name = name
        self.dir = Path(out_root) / name
        self.hls_time = hls_time
        self.segments = segments
        self.process: Optional[subprocess.Popen] = None
        self.started_at: Optional[float] = None
        self.source: str = ""
        self.transcoding = False
        self._log_path = self.dir / "ffmpeg.log"
        # start()/stop() bisa dipanggil dari thread CRUD dan thread autostart.
        self._lock = threading.Lock()

    # --- status ----------------------------------------------------------
    @property
    def playlist(self) -> Path:
        return self.dir / "index.m3u8"

    @property
    def running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def status(self) -> dict:
        return {
            "name": self.name,
            "running": self.running,
            "transcoding": self.transcoding,
            "uptime": round(time.time() - self.started_at, 1) if self.started_at and self.running else 0,
            "playlist": f"/hls/{self.name}/index.m3u8",
            "ready": self.playlist.exists(),
        }

    # --- kontrol ---------------------------------------------------------
    def start(self, rtsp_url: str, copy: bool = True) -> dict:
        with self._lock:
            if self.running:
                return {"ok": True, "sudah_berjalan": True, **self.status()}

            self.dir.mkdir(parents=True, exist_ok=True)
            try:
                for old in self.dir.glob("*"):
                    old.unlink(missing_ok=True)
            except OSError as exc:
                # Folders can still be held by an ffmpeg process from a previous
                # backend run (Windows keeps inherited handles open). Report it
                # instead of crashing the autostart thread.
                return {
                    "ok": False,
                    "error": f"Folder HLS masih dipakai proses lain: {exc}. Hentikan ffmpeg lama lalu coba lagi.",
                    **self.status(),
                }

            self.source = rtsp_url
            self.transcoding = not copy
            cmd = self._build_command(rtsp_url, copy)

            # Close the parent handle immediately after spawn: on Windows the
            # child inherits it, and keeping it open here would block the next
            # start() from deleting ffmpeg.log.
            log = open(self._log_path, "wb")
            try:
                self.process = subprocess.Popen(
                    cmd, stdin=subprocess.DEVNULL, stdout=log, stderr=log, cwd=str(self.dir)
                )
            finally:
                log.close()
            self.started_at = time.time()

            # Tunggu playlist pertama muncul (maks 15 dtk) supaya klien tidak
            # langsung meminta manifest yang belum ada.
            deadline = time.time() + 15
            while time.time() < deadline:
                if self.playlist.exists():
                    return {"ok": True, **self.status()}
                if not self.running:
                    return {"ok": False, "error": self._tail_log(), **self.status()}
                time.sleep(0.3)
            return {"ok": self.running, "error": "Playlist belum muncul dalam 15 detik.", **self.status()}

    def stop(self) -> dict:
        with self._lock:
            if self.process and self.running:
                self.process.terminate()
                try:
                    self.process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.process.kill()
            self.process = None
            self.started_at = None
            return self.status()

    # --- internal --------------------------------------------------------
    def _build_command(self, rtsp_url: str, copy: bool) -> list[str]:
        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "warning", "-nostdin"]
        if rtsp_url.lower().startswith("rtsp://"):
            cmd += ["-rtsp_transport", "tcp"]
        else:
            # Berkas/HTTP diputar secepat disk; -re memaksa laju nyata.
            cmd += ["-re"]
        cmd += ["-i", rtsp_url, "-an"]
        if copy:
            cmd += ["-c:v", "copy"]
        else:
            cmd += [
                "-c:v", "libx264", "-preset", "veryfast", "-tune", "zerolatency",
                "-pix_fmt", "yuv420p", "-g", "50", "-sc_threshold", "0", "-b:v", "2500k",
            ]
        cmd += [
            "-f", "hls",
            "-hls_time", str(self.hls_time),
            "-hls_list_size", str(self.segments),
            "-hls_flags", "delete_segments+independent_segments+omit_endlist",
            "-hls_segment_filename", str(self.dir / "seg_%05d.ts"),
            str(self.playlist),
        ]
        return cmd

    def _tail_log(self, lines: int = 4) -> str:
        try:
            text = self._log_path.read_text(encoding="utf-8", errors="replace").strip().splitlines()
            return " | ".join(text[-lines:]) or "ffmpeg berhenti tanpa pesan."
        except OSError:
            return "ffmpeg berhenti tanpa pesan."


class HlsManager:
    """Kumpulan HlsStream, satu per kamera, aman dipanggil dari beberapa request."""

    def __init__(self, out_root: Path = MEDIA_ROOT) -> None:
        self.out_root = Path(out_root)
        self._streams: dict[str, HlsStream] = {}
        self._lock = threading.Lock()

    def get(self, name: str) -> HlsStream:
        with self._lock:
            if name not in self._streams:
                self._streams[name] = HlsStream(name, self.out_root)
            return self._streams[name]

    def start(self, name: str, rtsp_url: str, copy: bool = True) -> dict:
        return self.get(name).start(rtsp_url, copy=copy)

    def start_async(self, name: str, rtsp_url: str, copy: bool = True) -> threading.Thread:
        """Mulai ffmpeg di latar agar request CRUD tidak menunggu 15 detik."""
        thread = threading.Thread(
            target=self.start,
            args=(name, rtsp_url),
            kwargs={"copy": copy},
            daemon=True,
            name=f"hls-{name}",
        )
        thread.start()
        return thread

    def stop(self, name: str) -> dict:
        return self.get(name).stop()

    def list(self) -> list[dict]:
        with self._lock:
            return [stream.status() for stream in self._streams.values()]

    def stop_all(self) -> None:
        for stream in list(self._streams.values()):
            stream.stop()

    @staticmethod
    def ffmpeg_tersedia() -> bool:
        return shutil.which("ffmpeg") is not None


manager = HlsManager()
