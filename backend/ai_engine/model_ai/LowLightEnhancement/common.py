"""Helper bersama untuk semua enhancer low-light (MirNet & Zero-DCE family).

Semua modul inference memakai API yang sama supaya ``main_ai.py`` bisa
memilih varian lewat nama:

    enhancer = Enhancer(device)      # memuat bobot dari ../Model/
    frame_bgr = enhancer.enhance(frame_bgr)

Kebijakan device mengikuti permintaan proyek: GPU NVIDIA bila terdeteksi,
kalau tidak CPU.
"""

from __future__ import annotations

import os
from pathlib import Path

import cv2
import numpy as np
import torch
import torch.nn.functional as F

LOWLIGHT_DIR = Path(__file__).resolve().parent

# Ukuran input tetap per frame -> cudnn boleh memilih algoritma tercepat.
if torch.cuda.is_available():
    torch.backends.cudnn.benchmark = True


# ---------------------------------------------------------------------------
# Device
# ---------------------------------------------------------------------------
def pick_device(preference: str | None = None) -> torch.device:
    """Perangkat komputasi: ``cuda`` bila tersedia, selain itu ``cpu``.

    ``auto``/kosong = GPU kalau ada, kalau tidak CPU. ``cpu`` memaksa CPU
    (dipakai mesin tanpa GPU NVIDIA, atau untuk membandingkan throughput).
    """
    pref = (preference or "").strip().lower()
    if pref in ("cpu", "cpu:0"):
        return torch.device("cpu")
    if pref in ("", "auto", "gpu", "default"):
        return torch.device("cuda") if torch.cuda.is_available() else torch.device("cpu")
    if torch.cuda.is_available():
        if pref.startswith("cuda") and pref != "cuda":
            try:
                return torch.device(pref)
            except (RuntimeError, ValueError):
                pass
        return torch.device("cuda")
    return torch.device("cpu")


def device_label(device: torch.device) -> str:
    if device.type == "cuda":
        try:
            return f"cuda ({torch.cuda.get_device_name(device)})"
        except Exception:  # pragma: no cover - driver aneh
            return "cuda"
    return "cpu"


# ---------------------------------------------------------------------------
# Bobot
# ---------------------------------------------------------------------------
def strip_metadata(state: dict) -> dict:
    """Buang key thop (``total_ops``/``total_params``) yang bukan parameter."""
    return {
        key: value
        for key, value in state.items()
        if "total_ops" not in key and "total_params" not in key
    }


def load_state(model_file: str | Path, device: torch.device | str = "cpu") -> dict:
    """Muat state_dict dari file .pth, termasuk checkpoint yang dibungkus."""
    raw = torch.load(str(model_file), map_location=device, weights_only=True)
    if isinstance(raw, dict):
        for wrapper in ("state_dict", "model_state_dict", "params", "model"):
            inner = raw.get(wrapper)
            if isinstance(inner, dict):
                raw = inner
                break
    return strip_metadata(raw)


# ---------------------------------------------------------------------------
# Konversi frame <-> tensor
# ---------------------------------------------------------------------------
def to_tensor(frame_bgr: np.ndarray, dtype: torch.dtype = torch.float32) -> torch.Tensor:
    rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
    arr = np.ascontiguousarray(rgb)
    tensor = torch.from_numpy(arr).permute(2, 0, 1).to(dtype).div_(255.0)
    return tensor.unsqueeze(0)


def fp16_enabled(device: torch.device | str) -> bool:
    """FP16 hanya di GPU dan bisa dimatikan lewat ``AI_FP16=0``.

    Model MirNet 1,5M parameter di 320x180 menghabiskan ~85 ms di FP32 dan
    ~55 ms di FP16 pada RTX 3050 — konversi bobot sekali di awal, bukan per
    frame. Di CPU FP16 justru lebih lambat, jadi selalu FP32.
    """
    kind = getattr(device, "type", str(device))
    if kind != "cuda":
        return False
    flag = (os.environ.get("AI_FP16", "1") or "1").strip().lower()
    return flag not in ("0", "false", "no", "off")


def infer_dtype(model: torch.nn.Module, device: torch.device) -> torch.dtype:
    """Konversi bobot ke FP16 sekali saja; dikembalikan dtype untuk input."""
    if not fp16_enabled(device) or getattr(model, "_sk_fp16_failed", False):
        return torch.float32
    if getattr(model, "_sk_fp16", False):
        return torch.float16
    try:
        model.half()
    except (RuntimeError, ValueError):
        model._sk_fp16_failed = True
        return torch.float32
    model._sk_fp16 = True
    return torch.float16


def disable_fp16(model: torch.nn.Module) -> None:
    """Kembali ke FP32 setelah satu model terbukti tidak tahan FP16."""
    try:
        model.float()
    finally:
        model._sk_fp16 = False
        model._sk_fp16_failed = True


def to_bgr(tensor: torch.Tensor) -> np.ndarray:
    tensor = tensor.detach().clamp(0, 1).squeeze(0).permute(1, 2, 0)
    array = tensor.mul(255).round().byte().cpu().numpy()
    return cv2.cvtColor(array, cv2.COLOR_RGB2BGR)


def resize_max_side(frame_bgr: np.ndarray, max_side: int) -> tuple[np.ndarray, float]:
    """Perkecil frame sehingga sisi terpanjang <= ``max_side`` (tidak memperbesar)."""
    height, width = frame_bgr.shape[:2]
    longest = max(height, width)
    if max_side <= 0 or longest <= max_side:
        return frame_bgr, 1.0
    scale = max_side / float(longest)
    size = (max(8, int(round(width * scale))), max(8, int(round(height * scale))))
    resized = cv2.resize(frame_bgr, size, interpolation=cv2.INTER_AREA)
    return resized, scale


def pad_to(tensor: torch.Tensor, factor: int = 8) -> torch.Tensor:
    """Padding reflect agar H/W kelipatan ``factor``."""
    height, width = tensor.shape[2], tensor.shape[3]
    pad_h = (factor - height % factor) % factor
    pad_w = (factor - width % factor) % factor
    if pad_h == 0 and pad_w == 0:
        return tensor
    return F.pad(tensor, (0, pad_w, 0, pad_h), mode="reflect")


# ---------------------------------------------------------------------------
# Strategi inference
# ---------------------------------------------------------------------------
def enhance_image_to_image(
    model: torch.nn.Module,
    frame_bgr: np.ndarray,
    device: torch.device,
    work_side: int,
    factor: int = 8,
) -> np.ndarray:
    """MirNet: perkecil -> model di resolusi kerja -> perbesar kembali.

    Bobot MirNet dilatih pada resolusi tetap, jadi resolusi kerja harus
    dijaga; menjalankan model pada 1080p hanya menghabiskan waktu tanpa
    menambah detail.
    """
    height, width = frame_bgr.shape[:2]
    small, _ = resize_max_side(frame_bgr, work_side)
    dtype = infer_dtype(model, device)
    tensor = pad_to(to_tensor(small, dtype).to(device), factor)
    try:
        with torch.inference_mode():
            output = model(tensor)
    except RuntimeError:
        # Model ini tidak tahan FP16: kembali ke FP32 untuk seterusnya.
        disable_fp16(model)
        tensor = tensor.float()
        with torch.inference_mode():
            output = model(tensor)
    output = output[:, :, : small.shape[0], : small.shape[1]]
    result = to_bgr(output.float())
    if result.shape[1] != width or result.shape[0] != height:
        result = cv2.resize(result, (width, height), interpolation=cv2.INTER_LINEAR)
    return result


def enhance_with_curves(
    model: torch.nn.Module,
    frame_bgr: np.ndarray,
    device: torch.device,
    work_side: int = 256,
    brightness: float = 1.0,
) -> np.ndarray:
    """Zero-DCE family: kurva diprediksi di resolusi kecil, diterapkan penuh.

    Kurva hanya 24 kanal per piksel, jadi menerapkannya pada resolusi asli
    hampir gratis dan tidak menghilangkan detail seperti image-to-image.
    """
    height, width = frame_bgr.shape[:2]
    small, _ = resize_max_side(frame_bgr, work_side)
    small = cv2.resize(small, (work_side, work_side), interpolation=cv2.INTER_AREA)

    dtype = infer_dtype(model, device)
    try:
        with torch.inference_mode():
            predicted = model(to_tensor(small, dtype).to(device))
    except RuntimeError:
        disable_fp16(model)
        with torch.inference_mode():
            predicted = model(to_tensor(small).to(device))

    with torch.inference_mode():
        curves = predicted[-1] if isinstance(predicted, (tuple, list)) else predicted
        curves = curves.float()
        if brightness != 1.0:
            curves = curves * float(brightness)
        if curves.shape[2] != height or curves.shape[3] != width:
            curves = F.interpolate(curves, size=(height, width), mode="bicubic", align_corners=False)

        result = to_tensor(frame_bgr).to(device)
        for curve in torch.split(curves, 3, dim=1):
            result = result + curve * (torch.pow(result, 2) - result)
    return to_bgr(result)


def read_frame_or_raise(capture: cv2.VideoCapture) -> np.ndarray | None:
    ok, frame = capture.read()
    return frame if ok else None


def count_params_million(model: torch.nn.Module) -> float:
    return sum(p.numel() for p in model.parameters()) / 1e6
