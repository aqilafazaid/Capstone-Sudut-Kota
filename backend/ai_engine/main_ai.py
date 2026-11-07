from __future__ import annotations

import argparse
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Optional

import cv2
import numpy as np

AI_DIR = Path(__file__).resolve().parent
BACKEND_DIR = AI_DIR.parent
for path in (AI_DIR, BACKEND_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from enhancers import available as available_enhancers  # noqa: E402
from enhancers import create as create_enhancer  # noqa: E402

MODELS_DIR = AI_DIR / "model_ai"
LOWLIGHT_DIR = MODELS_DIR / "LowLight"
YOLO_DIR = MODELS_DIR / "Yolo"

AI_STATUS_POLL = 2.0
FIREBASE_PUSH_INTERVAL = 2.0
COCO_TARGETS = {2: "mobil", 3: "motor", 5: "bus", 7: "truk"}


# --------------------------------------------------------------------------
# Konfigurasi
# --------------------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Engine AI Sudut Kota")
    parser.add_argument("--channel", required=True, help="Nomor channel CCTV, contoh 29")
    parser.add_argument("--root", default=os.getenv("RTDB_ROOT", "cctv_data"),
                        help="Prefix node di RTDB (default: cctv_data)")
    parser.add_argument("--rtsp", default=os.getenv("RTSP_URL", ""),
                        help="URL RTSP penuh; bila kosong dipakai RTSP_URL_TEMPLATE + channel")
    parser.add_argument("--lowlight", default=os.getenv("LOWLIGHT_MODEL", "classical"),
                        choices=available_enhancers(),
                        help="Model low-light awal (bisa diganti dari RTDB saat berjalan)")
    parser.add_argument("--device", default=os.getenv("AI_DEVICE", "cpu"), help="cpu atau cuda")
    parser.add_argument("--no-detect", action="store_true", help="Matikan YOLO, hanya enhancement")
    parser.add_argument("--no-stream", action="store_true", help="Jangan push ke ffmpeg (uji lokal)")
    parser.add_argument("--skip", type=int, default=2, help="Deteksi tiap N frame (default 2)")
    return parser.parse_args()


def resolve_rtsp(args: argparse.Namespace) -> str:
    if args.rtsp:
        return args.rtsp
    template = os.getenv("RTSP_URL_TEMPLATE", "")
    if not template:
        raise SystemExit(
            "RTSP belum dikonfigurasi. Isi RTSP_URL atau RTSP_URL_TEMPLATE di backend/.env "
            "(lihat .env.example)."
        )
    return template.format(channel=args.channel)


def resolve_hls_dir(args: argparse.Namespace) -> Optional[Path]:
    """Folder keluaran HLS. None berarti stream keluar dimatikan."""
    if args.no_stream:
        return None
    root = Path(os.getenv("HLS_OUT_DIR", str(BACKEND_DIR / "media" / "hls")))
    out_dir = root / f"cam_{args.channel}"
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("*"):
        old.unlink(missing_ok=True)
    return out_dir


# --------------------------------------------------------------------------
# Firebase
# --------------------------------------------------------------------------
def connect_firebase(root: str, channel: str):
    """Kembalikan reference RTDB, atau None bila `.env` belum lengkap."""
    try:
        from firebase_init import init_firebase

        init_firebase()
        from firebase_admin import db

        return db.reference(f"{root}/cam_{channel}")
    except Exception as exc:
        print(f"[WARN] Firebase tidak aktif: {exc}")
        print("[WARN] Angka deteksi hanya tampil di log sampai backend/.env diisi.")
        return None


# --------------------------------------------------------------------------
# Model
# --------------------------------------------------------------------------
def load_yolo(device: str):
    """Satu model YOLO saja: file .pt pertama di model_ai/Yolo/."""
    from ultralytics import YOLO

    candidates = sorted(YOLO_DIR.glob("*.pt"))
    if candidates:
        weights = candidates[0]
        if len(candidates) > 1:
            print(f"[INFO] Lebih dari satu .pt di {YOLO_DIR}; memakai {weights.name}")
    else:
        weights = "yolov8n.pt"  # diunduh otomatis oleh ultralytics
        print("[WARN] model_ai/Yolo/ kosong — memakai yolov8n.pt bawaan ultralytics.")

    model = YOLO(str(weights))
    model.to(device)
    print(f"[INFO] YOLO: {weights}")
    return model


class EnhancerHolder:
    """Menyimpan enhancer aktif dan menggantinya saat RTDB meminta model lain."""

    def __init__(self, name: str, device: str) -> None:
        self.device = device
        self._lock = threading.Lock()
        self.requested = name
        self._instance = self._build(name)
        self._fallback_reason: Optional[str] = None

    def _build(self, name: str):
        try:
            return create_enhancer(name, LOWLIGHT_DIR, device=self.device)
        except KeyError as exc:
            print(f"[WARN] {exc}")
            return create_enhancer("classical", LOWLIGHT_DIR, device=self.device)

    def switch(self, name: str) -> None:
        if name == self.requested:
            return
        with self._lock:
            self.requested = name
            self._instance = self._build(name)
            self._fallback_reason = None
        print(f"[INFO] Low-light diganti ke: {name}")

    def enhance(self, frame: np.ndarray):
        with self._lock:
            enhancer = self._instance
            output, processed = enhancer.enhance(frame)

            if processed or enhancer.name in ("none", "classical"):
                return output, processed, enhancer.name, None

            # Bobot belum ada / arsitektur tidak cocok: pakai CLAHE sekali,
            # catat alasannya untuk dilaporkan ke RTDB.
            self._fallback_reason = enhancer.error
            print(f"[WARN] {enhancer.label} tidak siap: {enhancer.error}")
            print("[WARN] Memakai CLAHE sampai bobot model tersedia.")
            self._instance = create_enhancer("classical", LOWLIGHT_DIR, device=self.device)
            output, processed = self._instance.enhance(frame)
            return output, processed, self._instance.name, self._fallback_reason


def read_ai_status(db_ref) -> dict:
    if db_ref is None:
        return {}
    try:
        return db_ref.child("ai_status").get() or {}
    except Exception as exc:
        print(f"[WARN] Gagal membaca ai_status: {exc}")
        return {}


# --------------------------------------------------------------------------
# Video
# --------------------------------------------------------------------------
def open_capture(rtsp: str, retries: int = 5) -> cv2.VideoCapture:
    for attempt in range(1, retries + 1):
        cap = cv2.VideoCapture(rtsp, cv2.CAP_FFMPEG)
        if cap.isOpened():
            return cap
        cap.release()
        print(f"[WARN] RTSP gagal dibuka ({attempt}/{retries}) — coba lagi 3 detik.")
        time.sleep(3)
    raise SystemExit("Tidak bisa membuka RTSP. Periksa RTSP_URL / jaringan Tailscale.")


def start_ffmpeg(out_dir: Path, width: int, height: int, fps: int) -> subprocess.Popen:
    """Frame hasil AI (mentah) -> HLS di folder yang sama dengan stream non-AI."""
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-f", "rawvideo", "-pix_fmt", "bgr24",
        "-s", f"{width}x{height}", "-r", str(fps), "-i", "-",
        "-c:v", "libx264", "-preset", "veryfast", "-tune", "zerolatency",
        "-pix_fmt", "yuv420p", "-g", str(fps * 2), "-b:v", "2500k",
        "-f", "hls",
        "-hls_time", "2", "-hls_list_size", "6",
        "-hls_flags", "delete_segments+independent_segments+omit_endlist",
        "-hls_segment_filename", str(out_dir / "seg_%05d.ts"),
        str(out_dir / "index.m3u8"),
    ]
    return subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)


def draw_hud(frame: np.ndarray, counts: dict, fps: float, model_label: str, detect: bool) -> None:
    cv2.rectangle(frame, (8, 8), (330, 92), (10, 15, 35), -1)
    cv2.putText(frame, f"{model_label} | YOLO {'ON' if detect else 'OFF'} | {fps:.1f} fps",
                (18, 34), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (90, 220, 120), 1)
    cv2.putText(frame, f"Mobil {counts['mobil']}  Motor {counts['motor']}  "
                       f"Truk {counts['truk']}  Bus {counts['bus']}",
                (18, 62), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (235, 235, 235), 1)
    cv2.putText(frame, time.strftime("%d/%m/%Y %H:%M:%S"),
                (18, 84), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (160, 170, 190), 1)


# --------------------------------------------------------------------------
# Loop utama
# --------------------------------------------------------------------------
def main() -> int:
    args = parse_args()
    rtsp_url = resolve_rtsp(args)
    hls_dir = resolve_hls_dir(args)

    print(f"[START] channel={args.channel} root={args.root} lowlight={args.lowlight}")
    if hls_dir is not None:
        print(f"[HLS] http://{HOST_API}:{PORT_API}/hls/cam_{args.channel}/index.m3u8")
    db_ref = connect_firebase(args.root, args.channel)

    detector = None if args.no_detect else load_yolo(args.device)
    enhancer = EnhancerHolder(args.lowlight, args.device)

    cap = open_capture(rtsp_url)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or 1280
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 720
    fps_in = cap.get(cv2.CAP_PROP_FPS) or 25
    if fps_in <= 0 or fps_in > 30:
        fps_in = 25
    print(f"[INFO] Sumber {width}x{height} @ {fps_in:g} fps")

    ffmpeg = start_ffmpeg(hls_dir, width, height, int(fps_in)) if hls_dir else None

    counts = {"mobil": 0, "motor": 0, "truk": 0, "bus": 0}
    frame_index = 0
    frames_in_window = 0
    window_start = time.time()
    measured_fps = 0.0
    last_push = 0.0
    last_status_poll = 0.0
    active_model = args.lowlight
    detect_enabled = not args.no_detect

    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                print("[WARN] Frame hilang — menyambung ulang RTSP.")
                cap.release()
                cap = open_capture(rtsp_url)
                continue

            # 1. Status AI dari RTDB (ganti model / nyalakan-matikan YOLO)
            if db_ref is not None and time.time() - last_status_poll > AI_STATUS_POLL:
                state = read_ai_status(db_ref)
                last_status_poll = time.time()
                requested = state.get("lowlight_model")
                if state.get("lowlight_enabled") is False:
                    enhancer.switch("none")
                elif requested:
                    enhancer.switch(requested)
                elif state.get("lowlight_enabled") is True and enhancer.requested == "none":
                    enhancer.switch(args.lowlight)
                if "yolo_enabled" in state:
                    detect_enabled = bool(state["yolo_enabled"])
                elif "deteksi_aktif" in state:
                    detect_enabled = bool(state["deteksi_aktif"])

            # 2. Enhancement
            frame, processed, active_model, fallback = enhancer.enhance(frame)

            # 3. Deteksi (tiap N frame, hasil digambar ulang di frame berikutnya)
            if detector is not None and detect_enabled and frame_index % max(1, args.skip) == 0:
                counts = {"mobil": 0, "motor": 0, "truk": 0, "bus": 0}
                result = detector(frame, verbose=False, conf=0.35, classes=list(COCO_TARGETS))[0]
                for box in result.boxes:
                    cls_id = int(box.cls[0])
                    label = COCO_TARGETS.get(cls_id)
                    if label is None:
                        continue
                    counts[label] += 1
                    x1, y1, x2, y2 = map(int, box.xyxy[0])
                    colors = {"mobil": (255, 160, 0), "motor": (0, 235, 255),
                              "truk": (0, 0, 255), "bus": (0, 140, 255)}
                    cv2.rectangle(frame, (x1, y1), (x2, y2), colors[label], 2)
                    cv2.putText(frame, f"{label} {float(box.conf[0]):.2f}", (x1, max(12, y1 - 6)),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, colors[label], 2)

            # 4. FPS
            frame_index += 1
            frames_in_window += 1
            elapsed = time.time() - window_start
            if elapsed >= 5:
                measured_fps = frames_in_window / elapsed
                frames_in_window = 0
                window_start = time.time()

            draw_hud(frame, counts, measured_fps, active_model, detect_enabled)

            # 5. Kirim ke ffmpeg
            if ffmpeg is not None:
                try:
                    ffmpeg.stdin.write(frame.tobytes())
                except Exception as exc:
                    print(f"[ERROR] Pipa ffmpeg putus: {exc}")
                    break

            # 6. Sinkronisasi RTDB tiap 2 detik
            if db_ref is not None and time.time() - last_push > FIREBASE_PUSH_INTERVAL:
                total = sum(counts.values())
                payload = {
                    "timestamp": time.time(),
                    "jumlah_mobil": counts["mobil"],
                    "jumlah_motor": counts["motor"],
                    "jumlah_truk": counts["truk"],
                    "jumlah_bus": counts["bus"],
                    "jumlah_berat": counts["truk"] + counts["bus"],  # kompatibilitas
                    "total_kendaraan": total,
                    "server_fps": round(measured_fps, 1),
                    "night_vision_status": processed,
                    "lowlight_model": active_model,
                    "lowlight_error": fallback,
                    "deteksi_aktif": detect_enabled,
                    "status": "ONLINE",
                }
                try:
                    db_ref.update(payload)
                except Exception as exc:
                    print(f"[WARN] Gagal update RTDB: {exc}")
                last_push = time.time()

            if frame_index % 60 == 0:
                print(f"[LIVE] frame={frame_index} fps={measured_fps:.1f} "
                      f"model={active_model} total={sum(counts.values())}")

    except KeyboardInterrupt:
        print("\n[STOP] Dihentikan pengguna.")
    finally:
        cap.release()
        if ffmpeg is not None:
            try:
                ffmpeg.stdin.close()
                ffmpeg.wait(timeout=5)
            except Exception:
                ffmpeg.kill()
        if db_ref is not None:
            try:
                db_ref.update({"status": "OFFLINE"})
            except Exception:
                pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
