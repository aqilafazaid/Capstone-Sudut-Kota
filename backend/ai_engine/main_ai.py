"""Engine AI Sudut Kota — jembatan MirNet / Zero-DCE family / YOLO.

Alur satu frame:

    RTSP / file  ->  enhancer low-light (varian pilihan)  ->  YOLO
                 ->  gambar kotak + HUD  ->  ffmpeg  ->  HLS  ->  web

Kebijakan device: ``auto`` = GPU NVIDIA bila terdeteksi, kalau tidak CPU
(``AI_DEVICE=cpu`` memaksa CPU; ``AI_FP16=0`` mematikan FP16 di GPU).
Di GPU, enhance dan deteksi berjalan di dua thread terpisah.

Resolusi
--------
Yang tampil di web selalu resolusi asli sumber (``--max-side 0``). Frame kerja
AI diperkecil ke ``--ai-side`` (default 960) supaya enhance + YOLO tetap
ringan, lalu hasilnya diperbesar kembali ke kanvas sebelum ditulis ke ffmpeg.

Statistik
---------
``server_fps`` yang dikirim ke RTDB dan ke ``ai_stats.json`` adalah FPS
*real* video yang tampil di web: jumlah frame yang benar-benar masuk ke
encoder HLS dibagi waktu berjalan. ``fps_in`` (frame sumber) dan
``enhance_ms``/``yolo_ms`` dilaporkan terpisah supaya bottleneck terlihat.

Kontrol runtime
---------------
Tanpa restart, engine membaca ``<RTDB_ROOT>/cam_<channel>/ai_status``
setiap 2 detik: ``lowlight_enabled``, ``lowlight_model``, ``yolo_enabled``.
Semua I/O Firebase berjalan di thread ``RtdbBridge``; loop frame tidak pernah
menunggu jaringan, karena satu panggilan lambat langsung menurunkan FPS.
"""

from __future__ import annotations

import argparse
import json
import os
from collections import deque
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

import cv2
import numpy as np

AI_DIR = Path(__file__).resolve().parent
BACKEND_DIR = AI_DIR.parent
for _path in (AI_DIR, BACKEND_DIR):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

MODELS_DIR = AI_DIR / "model_ai"
YOLO_DIR = MODELS_DIR / "Yolo"
DEFAULT_HLS_ROOT = BACKEND_DIR / "media" / "hls"

# Nama varian low-light mengikuti registry (satu file inference per model).
DEFAULT_VARIANT = os.environ.get("AI_LOWLIGHT_MODEL", "mobile_mirnet")

PUSH_INTERVAL = 2.0
STATUS_POLL_INTERVAL = 2.0
STATUS_FILE_INTERVAL = 1.0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    from model_ai.LowLightEnhancement import registry

    parser = argparse.ArgumentParser(description="Engine AI Sudut Kota (low-light + YOLO -> HLS)")
    parser.add_argument("--channel", required=False, default="", help="Nomor channel CCTV, mis. 48")
    parser.add_argument("--node-id", default="", help="ID node (default cam_<channel>)")
    parser.add_argument("--input", "--rtsp", dest="source", default=os.environ.get("RTSP_URL", ""),
                        help="URL RTSP/HTTP atau path file video")
    parser.add_argument("--root", default=os.environ.get("RTDB_ROOT", "cctv_data"))
    parser.add_argument("--lowlight", default=DEFAULT_VARIANT, choices=registry.available(),
                        help=f"Varian low-light (default {DEFAULT_VARIANT})")
    parser.add_argument("--device", default=os.environ.get("AI_DEVICE", "auto"),
                        help="auto (GPU kalau ada, kalau tidak CPU), cpu, cuda, atau cuda:0")
    parser.add_argument("--max-side", type=int, default=int(os.environ.get("AI_MAX_SIDE", "0")),
                        help="Sisi terpanjang kanvas HLS; 0 = resolusi asli sumber (default 0)")
    parser.add_argument("--ai-side", type=int, default=int(os.environ.get("AI_AI_SIDE", "960")),
                        help="Sisi terpanjang frame kerja AI; 0 = sama dengan kanvas. "
                             "Mode CPU otomatis 640 kecuali diisi eksplisit")
    parser.add_argument("--enhance-side", type=int, default=0,
                        help="Override resolusi kerja enhancer (default per model)")
    parser.add_argument("--imgsz", type=int, default=int(os.environ.get("AI_YOLO_IMGSZ", "640")))
    parser.add_argument("--conf", type=float, default=float(os.environ.get("AI_YOLO_CONF", "0.35")))
    parser.add_argument("--out", default="", help="Folder HLS tujuan (default media/hls/<node>)")
    parser.add_argument("--no-stream", action="store_true", help="Tanpa HLS (uji model)")
    parser.add_argument("--no-yolo", action="store_true", help="Matikan YOLO")
    parser.add_argument("--no-lowlight", action="store_true", help="Matikan enhancement")
    parser.add_argument("--no-rtdb", action="store_true", help="Jangan tulis ke Firebase RTDB")
    parser.add_argument("--push-interval", type=float, default=PUSH_INTERVAL)
    parser.add_argument("--duration", type=float, default=0.0,
                        help="Berhenti otomatis setelah N detik (uji)")
    parser.add_argument("--warmup", type=int, default=1, help="Jumlah frame pemanasan model")
    parser.add_argument("--print-json", action="store_true", help="Cetak ringkasan JSON saat keluar")
    parser.add_argument("--benchmark", action="store_true",
                        help="Uji muat semua varian low-light lalu keluar")
    return parser.parse_args(argv)


def resolve_source(args: argparse.Namespace) -> str:
    if args.source:
        return args.source
    template = os.environ.get("RTSP_URL_TEMPLATE", "")
    if template and args.channel:
        return template.format(channel=args.channel)
    raise SystemExit("Sumber belum diisi: lewatkan --input/--rtsp, RTSP_URL, atau RTSP_URL_TEMPLATE.")


def resolve_out(args: argparse.Namespace) -> Path | None:
    if args.no_stream:
        return None
    if args.out:
        return Path(args.out)
    node_id = args.node_id or (f"cam_{args.channel}" if args.channel else "cam_0")
    return Path(os.environ.get("HLS_OUT_DIR", str(DEFAULT_HLS_ROOT))) / node_id


def even_size(width: int, height: int, limit: int) -> tuple[int, int]:
    """Ukuran kanvas: sisi terpanjang <= ``limit`` (0 = resolusi asli), genap."""
    longest = max(height, width)
    if limit and limit > 0 and longest > limit:
        factor = limit / float(longest)
        return (max(16, int(round(width * factor)) // 2 * 2),
                max(16, int(round(height * factor)) // 2 * 2))
    return (max(16, width // 2 * 2), max(16, height // 2 * 2))


def gain_lut(source_small: np.ndarray, enhanced_small: np.ndarray) -> np.ndarray | None:
    """LUT pencerahan per kanal dari pasangan frame kecil: asli vs hasil model.

    Model low-light dijalankan di resolusi kerja, jadi hasilnya tidak layak
    diperbesar ke 1080p (lunak). Yang dipakai untuk tampilan hanya *selisih
    kecerahannya*: LUT 256 entri per kanal BGR, dibentuk sebagai kurva gamma
    yang memetakan rata-rata kanal frame asli ke rata-rata kanal hasil model,
    lalu diterapkan ke frame resolusi penuh (``cv2.LUT`` mendukung LUT
    per-kanal). Hasilnya tetap tajam; efeknya mendekati model, bukan identik.
    """
    if source_small.size == 0 or enhanced_small.size == 0:
        return None

    values = np.arange(256, dtype=np.float32)
    channels = []
    for index in range(3):
        source_channel = source_small[:, :, index]
        target = float(enhanced_small[:, :, index].mean())
        if target < 1.0:
            return None
        hist = cv2.calcHist([source_channel], [0], None, [256], [0, 256]).ravel()
        total = float(hist.sum()) or 1.0

        def curve_mean(gamma: float, hist=hist, total=total) -> float:
            return float((hist * (255.0 * np.power(values / 255.0, gamma))).sum() / total)

        lo, hi = 0.25, 3.0
        if target >= curve_mean(lo):
            gamma = lo
        elif target <= curve_mean(hi):
            gamma = hi
        else:
            for _ in range(18):
                mid = (lo + hi) / 2.0
                if curve_mean(mid) > target:
                    lo = mid
                else:
                    hi = mid
            gamma = (lo + hi) / 2.0
        channels.append(np.clip(255.0 * np.power(values / 255.0, gamma), 0, 255).astype(np.uint8))

    lut = np.stack(channels, axis=1).reshape(256, 1, 3)
    # Perubahan terlalu kecil: biarkan frame asli apa adanya.
    if np.abs(lut.astype(np.int16) - np.arange(256, dtype=np.int16)[:, None, None]).max() < 6:
        return None
    return lut


class AiWorker:
    """Enhance dan deteksi di dua thread terpisah; jalur tampilan tidak menunggu.

    Satu putaran AI (enhance + YOLO) butuh 100-250 ms; kalau dijalankan
    berurutan, kotak deteksi hanya diperbarui 4-9x per detik. Di sini keduanya
    dipisah:

    * thread ``ai-enhance`` memperkecil frame, menjalankan model low-light
      **hanya sesering ``enhance_hz``** (LUT kecerahan berubah lambat, tidak
      perlu tiap frame), lalu menerbitkan LUT;
    * thread ``ai-detect`` mengambil frame kecil terbaru, menerapkan LUT
      (``cv2.LUT``, ~1 ms) dan menjalankan YOLO secepat GPU/CPU mampu.

    Hasilnya deteksi mengikuti laju sumber, sementara model low-light yang
    mahal tetap dijalankan secukupnya — GPU dipakai untuk dua alur kerja yang
    saling tumpang tindih, bukan satu antrean panjang.
    """

    def __init__(self, enhancer, detector, ai_size: tuple[int, int], device,
                 variant: str, model_label: str, registry_names: list[str],
                 yolo_active: bool, enhance_side: int | None = None,
                 enhance_hz: float = 6.0) -> None:
        # cudnn autotune (benchmark=True) bisa macet kalau dipanggil dari
        # thread non-utama saat pertama melihat ukuran input baru — terbukti
        # hang pada Mobile-MIRNet 960x540. Worker memakai heuristik cudnn.
        import torch

        torch.backends.cudnn.benchmark = False
        self._lock = threading.Lock()
        self._native: np.ndarray | None = None      # frame masuk (belum diolah)
        self._small: np.ndarray | None = None       # frame kerja terbaru
        self._small_version = 0
        self._request: dict | None = None
        self._wake_prep = threading.Event()
        self._wake_enhance = threading.Event()
        self._wake_detect = threading.Event()
        self._stop = threading.Event()
        self._enhance_hz = max(0.5, float(enhance_hz))
        self._threads = [
            threading.Thread(target=self._prep_loop, name="ai-prep", daemon=True),
            threading.Thread(target=self._enhance_loop, name="ai-enhance", daemon=True),
            threading.Thread(target=self._detect_loop, name="ai-detect", daemon=True),
        ]
        self._enhancer = enhancer
        self._detector = detector
        self._device = device
        self._ai_size = ai_size
        self._enhance_side = enhance_side or None
        self._registry_names = list(registry_names)
        self._yolo_locked = False
        self._detect_meter = FpsMeter(2.5)
        self._detect_count = 0
        self.result: dict = {
            "variant": variant,
            "model_label": model_label,
            "yolo_active": bool(yolo_active),
            "counts": {"mobil": 0, "motor": 0, "truk": 0, "bus": 0},
            "boxes": [],
            "lut": None,
            "enhance_ms": 0.0,
            "yolo_ms": 0.0,
            "detect_fps": 0.0,
            "seq": 0,
            "detect_seq": 0,
            "error": "",
        }

    # --- API -------------------------------------------------------------
    @property
    def detector(self):
        """Detektor aktif (dipakai jalur tampilan untuk menggambar kotak)."""
        return self._detector

    def start(self) -> "AiWorker":
        for thread in self._threads:
            thread.start()
        return self

    def submit(self, frame: np.ndarray) -> None:
        """Frame bersih (belum digambar) untuk diproses; salinan agar aman."""
        with self._lock:
            self._native = frame.copy()
        self._wake_prep.set()

    def request(self, **changes) -> None:
        with self._lock:
            self._request = {**(self._request or {}), **changes}
        self._wake_prep.set()
        self._wake_enhance.set()

    def snapshot(self) -> dict:
        with self._lock:
            self._detect_meter.sample(time.time(), self._detect_count)
            data = dict(self.result)
            data["boxes"] = list(self.result["boxes"])
            data["counts"] = dict(self.result["counts"])
            data["detect_fps"] = round(self._detect_meter.rate(), 1)
            return data

    def stop(self) -> None:
        self._stop.set()
        self._wake_prep.set()
        self._wake_enhance.set()
        self._wake_detect.set()
        for thread in self._threads:
            thread.join(timeout=3)
        self._enhancer.close()
        self._detector.close()

    # --- Thread prep: perkecil tiap frame (cepat, tidak boleh diblokir) ---
    def _prep_loop(self) -> None:
        while not self._stop.is_set():
            self._wake_prep.wait(0.2)
            self._wake_prep.clear()
            if self._stop.is_set():
                break
            with self._lock:
                native, self._native = self._native, None
            if native is None:
                continue
            try:
                small = native if (native.shape[1], native.shape[0]) == self._ai_size else cv2.resize(
                    native, self._ai_size, interpolation=cv2.INTER_AREA)
                with self._lock:
                    self._small = small
                    self._small_version += 1
                self._wake_detect.set()
                self._wake_enhance.set()
            except Exception as exc:  # noqa: BLE001
                print(f"[WARN] worker AI (prep): {type(exc).__name__}: {exc}")

    # --- Thread enhance: model low-light, dibatasi enhance_hz ------------
    def _enhance_loop(self) -> None:
        last_run = 0.0
        min_gap = 1.0 / self._enhance_hz
        while not self._stop.is_set():
            self._wake_enhance.wait(0.2)
            self._wake_enhance.clear()
            if self._stop.is_set():
                break
            with self._lock:
                changes, self._request = self._request, None
            if changes:
                self._apply(changes)
            with self._lock:
                small = self._small
                variant = self.result["variant"]
            if small is None:
                continue
            now = time.perf_counter()
            if now - last_run < min_gap:
                continue  # LUT masih segar
            last_run = now
            try:
                t0 = time.perf_counter()
                enhanced = self._enhancer.enhance(small)
                enhance_ms = (time.perf_counter() - t0) * 1000.0

                lut = None if variant == "none" else gain_lut(small, enhanced)
                with self._lock:
                    self.result.update(
                        lut=lut,
                        enhance_ms=round(enhance_ms, 1),
                        variant=variant,
                        model_label=self._enhancer.label,
                        seq=self.result["seq"] + 1,
                        error="",
                    )
            except Exception as exc:  # noqa: BLE001 - worker tidak boleh mati
                message = f"{type(exc).__name__}: {exc}"
                with self._lock:
                    self.result["error"] = message
                print(f"[WARN] worker AI (enhance): {message}")

    # --- Thread deteksi --------------------------------------------------
    def _detect_loop(self) -> None:
        last_version = 0
        while not self._stop.is_set():
            self._wake_detect.wait(0.05)
            self._wake_detect.clear()
            if self._stop.is_set():
                break
            with self._lock:
                small, version = self._small, self._small_version
                lut = self.result["lut"]
                active = self.result["yolo_active"]
                detector = self._detector
            if small is None or version == last_version:
                continue
            last_version = version
            try:
                frame = cv2.LUT(small, lut) if lut is not None else small
                t0 = time.perf_counter()
                detections = detector.detect(frame)
                yolo_ms = (time.perf_counter() - t0) * 1000.0
                counts = detector.counts(detections)
                with self._lock:
                    self.result.update(
                        counts=counts,
                        boxes=list(detections) if active else [],
                        yolo_ms=round(yolo_ms, 1),
                        detect_seq=self.result["detect_seq"] + 1,
                        error="",
                    )
                    self._detect_count += 1
            except Exception as exc:  # noqa: BLE001
                message = f"{type(exc).__name__}: {exc}"
                with self._lock:
                    self.result["error"] = message
                print(f"[WARN] worker AI (detect): {message}")

    # --- Kontrol ---------------------------------------------------------
    def _apply(self, changes: dict) -> None:
        requested = changes.get("variant")
        if requested and requested in self._registry_names and requested != self.result["variant"]:
            try:
                candidate = load_enhancer(requested, self._device, self._enhance_side)
            except Exception as exc:  # noqa: BLE001 - engine tetap jalan
                print(f"[WARN] gagal memuat {requested}: {exc}")
            else:
                old = self._enhancer
                self._enhancer = candidate
                old.close()
                if self._device.type == "cuda":
                    import torch

                    torch.cuda.empty_cache()
                with self._lock:
                    self.result["variant"] = requested
                    self.result["model_label"] = candidate.label
                print(f"[AI] model low-light diganti: {candidate.label}")

        if "yolo" in changes and not self._yolo_locked:
            from model_ai.Yolo.Inference.yolo_inference import NoopDetector, VehicleDetector

            want = bool(changes["yolo"])
            if want != self.result["yolo_active"]:
                old = self._detector
                if want:
                    self._detector = VehicleDetector(device=str(self._device))
                else:
                    self._detector = NoopDetector()
                old.close()
                with self._lock:
                    self.result["yolo_active"] = want
                    self.result["boxes"] = [] if not want else self.result["boxes"]
                print(f"[AI] YOLO {'dinyalakan' if want else 'dimatikan'} lewat RTDB")


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------
def load_enhancer(name: str, device, work_side: int | None):
    from model_ai.LowLightEnhancement import registry

    return registry.create(name, device=device, work_size=work_side)


def load_detector(args: argparse.Namespace, device):
    from model_ai.Yolo.Inference import yolo_inference

    if args.no_yolo:
        return yolo_inference.NoopDetector()
    return yolo_inference.VehicleDetector(device=str(device), imgsz=args.imgsz, conf=args.conf)


def benchmark(device) -> int:
    """Muat tiap varian lalu ukur 5 frame 960x540 (kanvas produksi)."""
    import torch

    frame = np.full((540, 960, 3), 35, dtype=np.uint8)
    frame[140:400, 200:760] = (90, 90, 90)
    frame[:, ::40] = (110, 110, 110)
    from model_ai.LowLightEnhancement import registry

    print(f"device: {device} frame=960x540")
    failures = 0
    for name in [n for n in registry.available() if n != "none"]:
        try:
            started = time.perf_counter()
            enhancer = load_enhancer(name, device, None)
            load_s = time.perf_counter() - started
            enhancer.enhance(frame)  # pemanasan (autotune cudnn)
            if device.type == "cuda":
                torch.cuda.synchronize()
            timings = []
            for _ in range(5):
                t0 = time.perf_counter()
                enhancer.enhance(frame)
                if device.type == "cuda":
                    torch.cuda.synchronize()
                timings.append((time.perf_counter() - t0) * 1000)
            print(
                f"{name:16s} params={enhancer.params_m:7.2f}M load={load_s:5.2f}s "
                f"ms(min/avg)={min(timings):6.0f}/{sum(timings) / len(timings):6.0f}"
            )
        except Exception as exc:  # noqa: BLE001 - benchmark harus lanjut
            failures += 1
            print(f"{name:16s} GAGAL {type(exc).__name__}: {exc}")
    return 1 if failures else 0


# ---------------------------------------------------------------------------
# Sumber video (thread pembaca, selalu frame terbaru)
# ---------------------------------------------------------------------------
class FrameSource:
    """Baca frame di thread terpisah; loop utama selalu ambil yang terbaru."""

    def __init__(self, source: str, loop_file: bool = False, buffer: int = 3) -> None:
        self.source = source
        self.loop_file = loop_file
        # Antrean kecil (bukan 1) supaya burst dari tautan kamera tidak dibuang:
        # kamera yang mengirim 5 frame sekaligus lalu diam membuat loop hanya
        # sempat menulis 1 frame per burst. Tiga frame = ~0,12 s latensi.
        self._queue: queue.Queue[tuple[float, np.ndarray]] = queue.Queue(maxsize=max(1, int(buffer)))
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="frame-source", daemon=True)
        self.read_fps = 0.0
        self.error = ""
        self._capture: cv2.VideoCapture | None = None

    def start(self) -> "FrameSource":
        self._thread.start()
        return self

    def _open(self) -> cv2.VideoCapture:
        if os.name != "nt":
            cap = cv2.VideoCapture(self.source, cv2.CAP_FFMPEG, [cv2.CAP_PROP_BUFFERSIZE, 1])
        else:
            cap = cv2.VideoCapture(self.source, cv2.CAP_FFMPEG)
        if not cap.isOpened() and not self.source.lower().startswith(("rtsp", "http")):
            cap.release()
            cap = cv2.VideoCapture(self.source)
        return cap

    def _run(self) -> None:
        failures = 0
        reads = 0
        window = time.time()
        is_file = not self.source.lower().startswith(("rtsp", "http"))
        while not self._stop.is_set():
            cap = self._open()
            self._capture = cap
            if not cap.isOpened():
                failures += 1
                self.error = f"gagal membuka sumber ({failures})"
                time.sleep(min(10.0, 2.0 * failures))
                continue
            failures = 0
            self.error = ""
            fps_hint = cap.get(cv2.CAP_PROP_FPS) or 25.0
            if fps_hint <= 0 or fps_hint > 120:
                fps_hint = 25.0
            interval = 1.0 / fps_hint if is_file else 0.0
            next_at = time.time()
            while not self._stop.is_set():
                try:
                    ok, frame = cap.read()
                except cv2.error as exc:
                    self.error = f"decoder error: {exc.code if hasattr(exc, 'code') else exc}"
                    break
                if not ok:
                    if is_file and self.loop_file:
                        # File uji: ulang dari awal tanpa membuka decoder baru.
                        cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                        next_at = time.time()
                        continue
                    self.error = "frame habis / koneksi putus"
                    break
                captured = time.time()
                reads += 1
                now = time.time()
                if now - window >= 1.0:
                    self.read_fps = reads / (now - window)
                    reads = 0
                    window = now
                try:
                    self._queue.get_nowait()
                except queue.Empty:
                    pass
                try:
                    self._queue.put_nowait((captured, frame))
                except queue.Full:
                    pass
                if interval:
                    # File diputar selaras FPS aslinya supaya uji HLS real-time.
                    next_at = max(next_at + interval, time.time() - interval)
                    delay = next_at - time.time()
                    if delay > 0:
                        time.sleep(delay)
            cap.release()
            if not self._stop.is_set():
                time.sleep(1.0)

    def latest(self, timeout: float = 1.0) -> tuple[float, np.ndarray] | None:
        try:
            return self._queue.get(timeout=timeout)
        except queue.Empty:
            return None

    @property
    def alive(self) -> bool:
        return self._thread.is_alive()

    def stop(self) -> None:
        self._stop.set()
        if self._capture is not None:
            self._capture.release()
        self._thread.join(timeout=3)


# ---------------------------------------------------------------------------
# HLS writer
# ---------------------------------------------------------------------------
_ENCODER_CACHE: str | None = None


def pick_encoder() -> str:
    """Encoder H.264: NVENC kalau GPU/tidak terbebani CPU, kalau tidak libx264.

    ``AI_ENCODER`` = ``auto`` (default) | ``nvenc`` | ``libx264``. NVENC
    memindahkan encoding 1080p dari CPU ke blok encoder GPU, jadi core CPU
    tetap bebas untuk pembaca RTSP, LUT, dan menggambar kotak. Di mesin tanpa
    GPU NVIDIA, ``auto`` otomatis kembali ke libx264.
    """
    global _ENCODER_CACHE
    if _ENCODER_CACHE:
        return _ENCODER_CACHE
    pref = (os.environ.get("AI_ENCODER") or "auto").strip().lower()
    if pref in ("libx264", "x264", "cpu"):
        _ENCODER_CACHE = "libx264"
        return _ENCODER_CACHE
    try:
        probe = subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error",
             "-f", "lavfi", "-i", "color=c=black:s=320x240:d=0.2",
             "-c:v", "h264_nvenc", "-preset", "p2", "-tune", "ll",
             "-f", "null", "-"],
            capture_output=True, timeout=15,
        )
        if probe.returncode == 0:
            _ENCODER_CACHE = "h264_nvenc"
            return _ENCODER_CACHE
    except (OSError, subprocess.SubprocessError):
        pass
    _ENCODER_CACHE = "libx264"
    return _ENCODER_CACHE


class HlsWriter:
    """Frame BGR -> ffmpeg -> HLS fMP4 (live edge, daftar segmen pendek).

    Timestamp memakai wallclock supaya video yang tampil benar-benar
    merekam laju nyata (VFR): kalau pemrosesan 10 fps, yang tampil 10 fps,
    bukan slideshow yang makin tertinggal.
    """

    def __init__(self, out_dir: Path, size: tuple[int, int], crf: int = 20) -> None:
        self.out_dir = Path(out_dir)
        self.size = size
        self.crf = int(crf)
        self.process: subprocess.Popen | None = None
        self.log_path = self.out_dir / "engine.log"
        self.encoder = "libx264"

    def start(self) -> None:
        self.out_dir.mkdir(parents=True, exist_ok=True)
        for old in self.out_dir.glob("*"):
            old.unlink(missing_ok=True)

        width, height = self.size
        # Keyframe maksimal tiap N frame. Engine menulis 3-5 fps VFR, jadi
        # GOP 30 berarti segmen HLS 6-10 detik -> pemutar tertinggal jauh dari
        # live. GOP 12 memotongnya jadi ~2-3 detik (sedikit menambah bitrate).
        try:
            gop = max(2, int(os.environ.get("AI_HLS_GOP", "12") or 12))
        except ValueError:
            gop = 12
        self.encoder = pick_encoder()
        # Skala CRF (x264) dan CQ (NVENC) tidak identik: pada scene statis,
        # CQ 20 menghasilkan bitrate ~10x lipat CRF 20. Default NVENC dibuat
        # lebih tinggi supaya ukuran segmen setara; AI_CRF menimpa keduanya.
        quality = int(os.environ.get("AI_CRF", "0") or 0) or (26 if self.encoder == "h264_nvenc" else self.crf)
        if self.encoder == "h264_nvenc":
            # p2 = preset cepat NVENC; tune ll memangkas latensi frame.
            # sc_threshold bukan opsi NVENC — keyframe diatur -g/-keyint_min.
            codec = ["-c:v", "h264_nvenc", "-preset", "p2", "-tune", "ll",
                     "-rc", "vbr", "-cq", str(quality), "-b:v", "0",
                     "-maxrate", "2500k", "-bufsize", "2500k",
                     "-profile:v", "main", "-pix_fmt", "yuv420p",
                     "-g", str(gop), "-keyint_min", str(gop)]
        else:
            codec = ["-c:v", "libx264", "-preset", "veryfast", "-tune", "zerolatency",
                     "-crf", str(quality), "-maxrate", "2500k", "-bufsize", "2500k",
                     "-pix_fmt", "yuv420p",
                     "-g", str(gop), "-keyint_min", str(gop), "-sc_threshold", "0"]
        cmd = [
            "ffmpeg", "-hide_banner", "-loglevel", "warning", "-y",
            "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{width}x{height}",
            "-use_wallclock_as_timestamps", "1", "-i", "pipe:0",
            "-an", *codec,
            "-fps_mode", "vfr",
            "-f", "hls", "-hls_time", "1", "-hls_list_size", "5",
            # program_date_time: tiap segmen membawa waktu absolut, sehingga
            # peramban (hls.js) bisa menghitung latensi end-to-end yang benar-
            # benar tampil, bukan hanya latensi internal engine.
            "-hls_flags", "delete_segments+independent_segments+omit_endlist+temp_file+program_date_time",
            "-hls_segment_type", "fmp4", "-hls_fmp4_init_filename", "init.mp4",
            "-hls_segment_filename", "seg_%05d.m4s",
            "index.m3u8",
        ]
        log = open(self.log_path, "wb")
        try:
            self.process = subprocess.Popen(
                cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                stderr=log, cwd=str(self.out_dir),
            )
        finally:
            log.close()
        print(f"[AI] encoder={self.encoder}")

    @property
    def running(self) -> bool:
        return self.process is not None and self.process.poll() is None

    def write(self, frame_bgr: np.ndarray) -> bool:
        if not self.running or self.process is None or self.process.stdin is None:
            return False
        if frame_bgr.shape[1] != self.size[0] or frame_bgr.shape[0] != self.size[1]:
            frame_bgr = cv2.resize(frame_bgr, self.size, interpolation=cv2.INTER_LINEAR)
        try:
            self.process.stdin.write(frame_bgr.tobytes())
            return True
        except (BrokenPipeError, OSError, ValueError):
            return False

    def close(self) -> None:
        if self.process is None:
            return
        try:
            if self.process.stdin:
                self.process.stdin.close()
            self.process.wait(timeout=8)
        except Exception:
            self.process.kill()


# ---------------------------------------------------------------------------
# Statistik
# ---------------------------------------------------------------------------
class FpsMeter:
    """FPS = selisih jumlah frame / selisih waktu nyata, jendela 2,5 detik.

    Definisi yang sama dengan FPS playback di peramban (totalVideoFrames /
    waktu nyata), jadi angka server dan angka di layar bisa dibandingkan
    langsung — bukan dua definisi yang berbeda.
    """

    def __init__(self, window: float = 2.5) -> None:
        self.window = float(window)
        self._samples: deque[tuple[float, int]] = deque()

    def sample(self, at: float, frames: int) -> None:
        self._samples.append((at, int(frames)))
        while len(self._samples) > 2 and at - self._samples[0][0] > self.window:
            self._samples.popleft()

    def rate(self) -> float:
        if len(self._samples) < 2:
            return 0.0
        (t0, f0), (t1, f1) = self._samples[0], self._samples[-1]
        span = t1 - t0
        return (f1 - f0) / span if span > 0 else 0.0


def device_summary(device: str) -> str:
    """'cuda (NVIDIA …)' -> 'GPU · NVIDIA …'; 'cpu' -> 'CPU'."""
    text = str(device or "").strip()
    kind = "GPU" if text.lower().startswith("cuda") else "CPU"
    name = text.split("(", 1)[1].rstrip(")").strip() if "(" in text else ""
    return f"{kind} · {name}" if name else kind


def hud(frame: np.ndarray, *, lowlight: str, yolo: str, device: str, scale: float = 1.0) -> None:
    """Overlay kiri-bawah: model AI yang dipakai + perangkat pemrosesnya.

    Dua baris ringkas di sudut kiri-bawah, karena kamera biasanya membakar OSD
    sendiri di kiri-atas (nama kanal), kanan-atas (jam), dan kanan-bawah
    (lokasi). Teks putih dengan tepi hitam tebal, tanpa kotak latar.
    """
    s = max(1.0, float(scale))
    font = cv2.FONT_HERSHEY_SIMPLEX
    size = 0.60 * s
    thickness = max(1, int(round(s)))
    # Tepi hitam harus cukup tebal: di atas langit terang + kompresi x264,
    # tepi tipis "meleleh" dan teks putih menyatu dengan latar.
    outline = thickness + 5
    step = int(32 * s)
    x = int(16 * s)

    lines = (
        f"Low-Light : {lowlight}    YOLO : {yolo}",
        f"Prosesor  : {device}",
    )
    y = frame.shape[0] - int(18 * s) - step * (len(lines) - 1)
    for text in lines:
        # Bayangan 2 px + tepi hitam tebal di bawah teks putih.
        cv2.putText(frame, text, (x + thickness, y + thickness), font, size,
                    (0, 0, 0), outline, cv2.LINE_AA)
        cv2.putText(frame, text, (x, y), font, size, (0, 0, 0), outline, cv2.LINE_AA)
        cv2.putText(frame, text, (x, y), font, size, (255, 255, 255), thickness, cv2.LINE_AA)
        y += step


def write_status_file(out_dir: Path | None, payload: dict) -> None:
    if out_dir is None:
        return
    target = out_dir / "ai_stats.json"
    tmp = out_dir / "ai_stats.tmp"
    try:
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        tmp.replace(target)
    except OSError:
        pass


# ---------------------------------------------------------------------------
# Firebase RTDB
# ---------------------------------------------------------------------------
def connect_rtdb(root: str, channel: str):
    try:
        from firebase_init import init_firebase

        init_firebase()
        from firebase_admin import db

        return db.reference(f"{root.strip('/')}/cam_{channel}")
    except Exception as exc:  # noqa: BLE001 - engine tetap jalan tanpa RTDB
        print(f"[WARN] Firebase tidak aktif: {exc}")
        return None


def read_ai_status(db_ref) -> dict:
    if db_ref is None:
        return {}
    try:
        return db_ref.child("ai_status").get() or {}
    except Exception as exc:  # noqa: BLE001
        print(f"[WARN] gagal membaca ai_status: {exc}")
        return {}


class RtdbBridge:
    """Baca status & kirim statistik RTDB di thread sendiri.

    Firebase adalah I/O jaringan: satu panggilan lambat di dalam loop frame
    langsung menurunkan FPS yang tampil (terukur 6.6 -> 2.6 fps pada tautan
    lambat). Loop hanya menitipkan payload terbaru; thread pengirim yang
    menunggu jaringan. Kebijakan "nilai terakhir menang" sudah cukup karena
    statistik berikutnya menimpa yang sebelumnya.
    """

    def __init__(self, db_ref, push_interval: float, poll_interval: float) -> None:
        self.ref = db_ref
        self.push_interval = max(0.5, float(push_interval))
        self.poll_interval = max(0.5, float(poll_interval))
        self.status: dict = {}
        self._payload: dict | None = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []

    def start(self) -> "RtdbBridge":
        for target, name in ((self._poll, "rtdb-status"), (self._push, "rtdb-stats")):
            thread = threading.Thread(target=target, name=name, daemon=True)
            thread.start()
            self._threads.append(thread)
        return self

    def _poll(self) -> None:
        while not self._stop.is_set():
            state = read_ai_status(self.ref)
            if isinstance(state, dict):
                self.status = state
            if self._stop.wait(self.poll_interval):
                return

    def _push(self) -> None:
        while not self._stop.wait(self.push_interval):
            with self._lock:
                payload, self._payload = self._payload, None
            if not payload:
                continue
            try:
                self.ref.update(payload)
            except Exception as exc:  # noqa: BLE001 - engine tetap jalan
                print(f"[WARN] gagal update RTDB: {exc}")

    def submit(self, payload: dict) -> None:
        with self._lock:
            self._payload = payload

    def stop(self) -> None:
        self._stop.set()
        for thread in self._threads:
            thread.join(timeout=3)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    from model_ai.LowLightEnhancement.common import device_label, fp16_enabled, pick_device

    device = pick_device(args.device)
    print(f"[AI] device={device_label(device)}")
    if device.type == "cuda":
        print(f"[AI] FP16={'ya' if fp16_enabled(device) else 'tidak'} (AI_FP16=0 untuk mematikan)")
    else:
        # CPU: pakai semua core untuk torch & OpenCV; tanpa ini torch hanya
        # memakai sebagian thread dan AI jadi jauh lebih lambat.
        import torch

        threads = int(os.environ.get("AI_CPU_THREADS", "0") or 0) or (os.cpu_count() or 4)
        torch.set_num_threads(max(1, threads))
        cv2.setNumThreads(max(1, threads))
        print(f"[AI] CPU mode: torch={torch.get_num_threads()} thread, cv2={cv2.getNumThreads()} thread")

    if args.benchmark:
        return benchmark(device)

    source_url = resolve_source(args)
    channel = args.channel or "".join(ch for ch in (args.node_id or "") if ch.isdigit())
    node_id = args.node_id or f"cam_{channel or '0'}"
    out_dir = resolve_out(args)

    variant = "none" if args.no_lowlight else args.lowlight
    print(f"[AI] node={node_id} channel={channel or '-'} variant={variant}")

    from model_ai.LowLightEnhancement import registry as lowlight_registry

    registry_names = lowlight_registry.available()
    enhancer = load_enhancer(variant, device, args.enhance_side or None)
    model_label = enhancer.label
    print(f"[AI] lowlight={enhancer.label} params={enhancer.params_m:.3f}M")
    detector = load_detector(args, device)
    # Keadaan YOLO yang sebenarnya berjalan (bisa dimatikan lewat RTDB), bukan
    # sekadar flag CLI: telemetri harus mencerminkan detektor yang dipakai.
    yolo_active = not args.no_yolo
    print(f"[AI] yolo={getattr(detector, 'path', '-')} device={detector.device}")

    # Pemanasan: kernel cudnn/torch pertama bisa 1-8 detik; jangan sampai
    # frame pertama yang tampil ke web ikut menunggu.
    warm_frame = np.full((180, 320, 3), 45, dtype=np.uint8)
    for _ in range(max(0, args.warmup)):
        enhancer.enhance(warm_frame)
        detector.detect(warm_frame)
    if device.type == "cuda":
        import torch

        torch.cuda.synchronize()
    print("[AI] warmup selesai")

    # Durasi uji dihitung sejak streaming, bukan sejak impor torch/YOLO.
    started = time.time()

    db_ref = None if args.no_rtdb else connect_rtdb(args.root, channel or "0")
    bridge = None
    if db_ref is not None:
        print(f"[AI] RTDB aktif: {args.root}/cam_{channel or '0'} (I/O di thread terpisah)")
        bridge = RtdbBridge(db_ref, args.push_interval, STATUS_POLL_INTERVAL).start()
    else:
        print("[AI] RTDB nonaktif; statistik hanya di ai_stats.json")

    try:
        source_buffer = max(1, int(os.environ.get("AI_SOURCE_BUFFER", "3") or 3))
    except ValueError:
        source_buffer = 3
    source = FrameSource(source_url, loop_file=True, buffer=source_buffer).start()
    first = source.latest(timeout=20.0)
    if first is None:
        source.stop()
        raise SystemExit(f"Sumber tidak menghasilkan frame: {source_url}")

    _, first_frame = first
    height, width = first_frame.shape[:2]
    # Kanvas HLS = resolusi asli sumber (AI_MAX_SIDE=0). Frame kerja AI boleh
    # lebih kecil supaya enhance + YOLO tetap ringan; hasilnya diperbesar
    # kembali ke kanvas sebelum dikirim ke ffmpeg.
    size = even_size(width, height, args.max_side)
    # Mesin tanpa GPU: frame kerja AI diperkecil ke 640 supaya model tetap
    # sanggup jalan mendekati real-time di CPU. Bisa ditimpa AI_AI_SIDE.
    ai_side = args.ai_side or args.max_side
    if device.type == "cpu" and "AI_AI_SIDE" not in os.environ and "--ai-side" not in sys.argv:
        ai_side = 640
    ai_size = even_size(width, height, ai_side)
    print(f"[AI] sumber {width}x{height} -> HLS {size[0]}x{size[1]} | kerja AI {ai_size[0]}x{ai_size[1]}")

    # Low-light mahal (55-90 ms GPU, 0,5 s CPU) tetapi LUT kecerahan berubah
    # lambat: 6x/detik sudah cukup di GPU, 1,5x/detik di CPU.
    try:
        enhance_hz = float(os.environ.get("AI_ENHANCE_HZ") or (6.0 if device.type == "cuda" else 1.5))
    except ValueError:
        enhance_hz = 6.0 if device.type == "cuda" else 1.5

    writer = HlsWriter(out_dir, size) if out_dir is not None else None
    if writer is not None:
        writer.start()
        print(f"[AI] HLS -> {out_dir / 'index.m3u8'}")

    # Dua thread AI: enhance (throttled) + deteksi (secepat perangkat).
    worker = AiWorker(enhancer, detector, ai_size, device, variant, model_label,
                      registry_names, yolo_active,
                      enhance_side=args.enhance_side or None,
                      enhance_hz=enhance_hz).start()
    print(f"[AI] worker: enhance {enhance_hz:g}x/dtk, deteksi tanpa batas")

    counts = {"mobil": 0, "motor": 0, "truk": 0, "bus": 0}
    latency_ms = 0.0
    enhance_ms = 0.0
    yolo_ms = 0.0
    frame_index = 0
    written = 0
    # FPS = frame tertulis / waktu nyata (jendela 2,5 dtk), definisi yang sama
    # dengan FPS playback di peramban.
    fps_meter = FpsMeter(2.5)
    server_fps = 0.0
    last_status_poll = 0.0
    last_status_file = 0.0
    last_stop_check = 0.0
    last_log = 0.0
    stopped_reason = "selesai"

    try:
        while True:
            now = time.time()
            # FPS di awal iterasi: turun sendiri saat sumber berhenti mengirim
            # frame (loop tetap berputar lewat timeout latest()).
            fps_meter.sample(now, written)
            server_fps = fps_meter.rate()
            if args.duration and now - started >= args.duration:
                stopped_reason = "durasi tercapai"
                break

            # 0. Permintaan berhenti dari engine_manager (stop.flag)
            if out_dir is not None and now - last_stop_check >= 1.0:
                last_stop_check = now
                if (out_dir / "stop.flag").exists():
                    stopped_reason = "diminta berhenti"
                    break

            # 1. Kontrol dari RTDB (ganti model / matikan modul). Isi status
            #    dibaca thread RtdbBridge, jadi tidak ada I/O jaringan di sini.
            #    Pemuatan model dikerjakan worker supaya video tidak membeku.
            if now - last_status_poll >= STATUS_POLL_INTERVAL:
                last_status_poll = now
                state = bridge.status if bridge is not None else {}
                requested = str(state.get("lowlight_model") or "")
                enabled = state.get("lowlight_enabled")
                if enabled is False and variant != "none":
                    worker.request(variant="none")
                elif enabled is True and variant == "none":
                    worker.request(variant=args.lowlight)
                elif requested in registry_names and requested != variant and enabled is not False:
                    worker.request(variant=requested)
                if "yolo_enabled" in state and not args.no_yolo:
                    worker.request(yolo=bool(state.get("yolo_enabled")))

            # 2. Ambil frame terbaru (frame lama dibuang oleh antrean)
            got = source.latest(timeout=2.0)
            if got is None:
                if source.error:
                    print(f"[WARN] {source.error}")
                    time.sleep(0.5)
                elif not source.alive:
                    stopped_reason = "pembaca frame berhenti"
                    print("[ERROR] thread pembaca frame berhenti")
                    break
                continue
            captured_at, native = got
            latency_ms = (time.time() - captured_at) * 1000

            # 2b. Titipkan frame bersih ke worker AI (enhance + YOLO di sana).
            worker.submit(native)

            # 3. Kanvas tampilan: resolusi asli sumber. Pencerahan memakai LUT
            #    dari hasil model di frame kecil — gambar tetap tajam, bukan
            #    hasil upscale 960 -> 1080.
            frame = native if (native.shape[1], native.shape[0]) == size else cv2.resize(
                native, size, interpolation=cv2.INTER_AREA)
            ai = worker.snapshot()
            if ai["lut"] is not None:
                frame = cv2.LUT(frame, ai["lut"])
            variant = ai["variant"]
            model_label = ai["model_label"]
            counts = ai["counts"]
            yolo_active = ai["yolo_active"]
            enhance_ms = ai["enhance_ms"]
            yolo_ms = ai["yolo_ms"]
            detect_fps = ai["detect_fps"]
            if ai["boxes"]:
                worker.detector.annotate(
                    frame, ai["boxes"],
                    scale=(size[0] / ai_size[0], size[1] / ai_size[1]))

            # 4. HUD: model AI yang dipakai + perangkat pemrosesnya
            hud(frame,
                lowlight="Nonaktif" if variant == "none" else model_label,
                yolo=(os.path.basename(getattr(worker.detector, "path", "") or "")
                      if yolo_active else "Nonaktif"),
                device=device_summary(device_label(device)),
                scale=size[0] / 960.0)
            if writer is not None:
                if not writer.running:
                    print("[ERROR] ffmpeg berhenti; cek engine.log")
                    stopped_reason = "ffmpeg berhenti"
                    break
                if writer.write(frame):
                    written += 1
                elif time.time() - started > 5:
                    print("[WARN] gagal menulis frame ke ffmpeg")
            frame_index += 1

            # 6. Laporan berkala
            payload = {
                "node_id": node_id,
                "channel": channel,
                "status": "ONLINE",
                "server_fps": round(server_fps, 1),
                "fps_in": round(source.read_fps, 1),
                "latency_ms": round(latency_ms, 0),
                "enhance_ms": round(enhance_ms, 1),
                "yolo_ms": round(yolo_ms, 1),
                "detect_fps": detect_fps,
                "encoder": writer.encoder if writer is not None else "",
                "device": device_label(device),
                "lowlight_model": model_label,
                "lowlight_variant": variant,
                "deteksi_aktif": yolo_active,
                "yolo_weights": os.path.basename(getattr(worker.detector, "path", "") or ""),
                "counts": counts,
                "total_kendaraan": sum(counts.values()),
                "frames": frame_index,
                "frames_web": written,
                "uptime_s": round(now - started, 1),
                "updated_at": now,
            }

            last_payload = payload

            if now - last_status_file >= STATUS_FILE_INTERVAL:
                last_status_file = now
                write_status_file(out_dir, payload)

            if bridge is not None:
                bridge.submit({
                    "timestamp": now,
                    "status": "ONLINE",
                    "jumlah_mobil": counts["mobil"],
                    "jumlah_motor": counts["motor"],
                    "jumlah_truk": counts["truk"],
                    "jumlah_bus": counts["bus"],
                    "jumlah_berat": counts["truk"] + counts["bus"],
                    "total_kendaraan": sum(counts.values()),
                    "server_fps": payload["server_fps"],
                    "fps_in": payload["fps_in"],
                    "latency_ms": payload["latency_ms"],
                    "night_vision_status": enhancer.name != "none",
                    "lowlight_model": model_label,
                    "lowlight_variant": variant,
                    "deteksi_aktif": yolo_active,
                    "yolo_weights": os.path.basename(getattr(worker.detector, "path", "") or ""),
                    "device": payload["device"],
                    "enhance_ms": payload["enhance_ms"],
                    "yolo_ms": payload["yolo_ms"],
                    "detect_fps": payload["detect_fps"],
                    "encoder": payload["encoder"],
                })

            if now - last_log >= 10:
                last_log = now
                print(f"[LIVE] frame={frame_index} web={written} "
                      f"fps_web={payload['server_fps']} fps_in={payload['fps_in']} "
                      f"enh={enhance_ms:.0f}ms yolo={yolo_ms:.0f}ms ai={detect_fps:.1f}/s "
                      f"lat={latency_ms:.0f}ms total={payload['total_kendaraan']}")

    except KeyboardInterrupt:
        stopped_reason = "dihentikan pengguna"
    finally:
        source.stop()
        worker.stop()
        if writer is not None:
            writer.close()
        if bridge is not None:
            bridge.stop()
        if db_ref is not None:
            try:
                db_ref.update({"status": "OFFLINE", "server_fps": 0})
            except Exception:  # noqa: BLE001
                pass
        summary = {
            "node_id": node_id,
            "variant": variant,
            "frames": frame_index,
            "frames_web": written,
            "uptime_s": round(time.time() - started, 1),
            "server_fps": round(written / max(0.001, time.time() - started), 2),
            "reason": stopped_reason,
            "out": str(out_dir) if out_dir else "",
        }
        write_status_file(out_dir, {**last_payload, **summary, "status": "OFFLINE",
                                    "server_fps": 0})
        print(f"[STOP] {json.dumps(summary, ensure_ascii=False)}")
        if args.print_json:
            print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
