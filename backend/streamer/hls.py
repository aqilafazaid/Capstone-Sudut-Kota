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

Kelancaran pemutaran bergantung pada dua hal yang diatur di sini:

1. Segmen dipotong tepat di keyframe dan ditulis secara atomik (`temp_file`),
   sehingga peramban tidak pernah menerima segmen setengah jadi atau segmen
   yang baru dihapus saat sedang diunduh (`hls_delete_threshold`).
2. Folder kamera dibersihkan saat node diubah/dihapus (`purge`). Tanpa itu
   `index.m3u8` lama tetap dilayani dan pemutar memutar konfigurasi lama.
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
        self._lock = threading.RLock()

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
        """Hentikan ffmpeg; playlist lama dibiarkan (dipakai saat shutdown)."""
        with self._lock:
            self._terminate()
            return self.status()

    def purge(self) -> dict:
        """Hentikan ffmpeg lalu hapus seluruh folder HLS kamera ini.

        Dipakai saat node diubah/dihapus/dihentikan: kalau playlist lama
        dibiarkan, `/hls/<id>/index.m3u8` tetap dilayani dan peramban memutar
        konfigurasi lama sampai ffmpeg menulis ulang.
        """
        with self._lock:
            self._terminate()

            error = ""
            for attempt in range(8):
                try:
                    if self.dir.exists():
                        shutil.rmtree(self.dir)
                    return {"ok": True, **self.status()}
                except OSError as exc:
                    # Windows menahan handle beberapa ratus ms setelah terminate.
                    error = str(exc)
                    time.sleep(0.2 * (attempt + 1))

            return {
                "ok": False,
                "error": f"Folder HLS belum bisa dihapus: {error}",
                **self.status(),
            }

    # --- internal --------------------------------------------------------
    def _terminate(self) -> None:
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                try:
                    self.process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    pass
        self.process = None
        self.started_at = None

    def _build_command(self, rtsp_url: str, copy: bool) -> list[str]:
        cmd = ["ffmpeg", "-hide_banner", "-loglevel", "warning", "-nostdin"]

        if rtsp_url.lower().startswith(("rtsp://", "rtsps://")):
            # TCP lebih stabil daripada UDP untuk jaringan kota; timeout socket
            # mencegah ffmpeg menggantung saat kamera hilang tanpa menutup koneksi.
            cmd += ["-rtsp_transport", "tcp", "-timeout", "5000000"]
        else:
            # Berkas/HTTP diputar secepat disk; -re memaksa laju nyata.
            cmd += ["-re"]

        # Jangan tunggu buffer besar sebelum segmen pertama: mengurangi waktu
        # sampai frame pertama tampil. `nobuffer`/`low_delay` hanya dipakai saat
        # transcode: pada mode copy keduanya membuat paket RTSP yang datang
        # tidak beraturan ikut dibuang, dan pemutar menerima PTS bolong-bolong
        # (gejala: gambar tersendat / "Non-monotonous DTS" di log ffmpeg).
        if copy:
            cmd += ["-fflags", "+genpts", "-probesize", "1000000", "-analyzeduration", "1000000"]
        else:
            cmd += ["-fflags", "+genpts+nobuffer", "-flags", "low_delay",
                    "-probesize", "1000000", "-analyzeduration", "1000000"]
        cmd += ["-i", rtsp_url, "-an"]

        if copy:
            cmd += ["-c:v", "copy"]
        else:
            cmd += [
                "-c:v", "libx264", "-preset", "veryfast", "-tune", "zerolatency",
                "-pix_fmt", "yuv420p", "-profile:v", "main",
                "-b:v", "2500k", "-maxrate", "2500k", "-bufsize", "5000k",
                # Keyframe tepat di batas segmen. Tanpa ini `hls_time` hanya
                # saran: segmen jadi tak beraturan dan pemutar tersendat.
                "-sc_threshold", "0",
                "-force_key_frames", f"expr:gte(t,n_forced*{self.hls_time})",
            ]

        cmd += [
            "-f", "hls",
            "-hls_time", str(self.hls_time),
            "-hls_list_size", str(self.segments),
            # Simpan 2 segmen sebelum menghapus yang paling lama, supaya klien
            # yang sedang mengunduh segmen itu tidak menerima 404.
            "-hls_delete_threshold", "2",
            # temp_file: segmen ditulis sebagai .tmp lalu di-rename, jadi
            # peramban tidak pernah membaca segmen setengah jadi.
            "-hls_flags", "delete_segments+independent_segments+omit_endlist+temp_file",
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

    def purge(self, name: str) -> dict:
        """Hentikan stream dan hapus folder HLS-nya (konfigurasi lama ikut hilang)."""
        return self.get(name).purge()

    def prune(self, keep_names) -> list[str]:
        """Buang stream & folder HLS yang tidak lagi punya node.

        Menangani sisa dari node yang dihapus, diganti ID-nya, atau dari proses
        backend yang berhenti mendadak: folder seperti itu tidak pernah dipakai
        lagi tetapi tetap dilayani di `/hls/<nama>/`.
        """
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
                if not folder.is_dir() or folder.name in keep:
                    continue
                try:
                    shutil.rmtree(folder)
                    removed.append(folder.name)
                except OSError:
                    continue

        return removed

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
