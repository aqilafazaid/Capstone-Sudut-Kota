"""Registry model low-light: satu nama -> satu modul inference.

Nama registry dipakai CLI ``--lowlight`` dan RTDB ``ai_status.lowlight_model``,
jadi sengaja stabil (underscore) meski nama file/folder memakai tanda hubung.
"""

from __future__ import annotations

import importlib

import numpy as np
import torch

from . import catalog
from .common import device_label, pick_device

_MODULES = {
    "mirnetv1": "model_ai.LowLightEnhancement.Mirnet.Inference.mirnetv1",
    "mirnetv2_kaggle": "model_ai.LowLightEnhancement.Mirnet.Inference.mirnetv2_kaggle",
    "mirnetv2_paper": "model_ai.LowLightEnhancement.Mirnet.Inference.mirnetv2_paper",
    "mobile_mirnet": "model_ai.LowLightEnhancement.Mirnet.Inference.mobile_mirnet",
    "zerodce": "model_ai.LowLightEnhancement.ZeroDCE.Inference.zerodce",
    "cbam_unet_dce": "model_ai.LowLightEnhancement.ZeroDCE.Inference.cbam_unet_dce",
}
# Daftar & label hidup di catalog.py supaya Flask bisa membacanya tanpa torch.
_LABELS = catalog.LABELS
_ORDER = catalog.ORDER


class Passthrough:
    """Low-light dimatikan: frame diteruskan tanpa diubah."""

    name = "none"
    label = _LABELS["none"]
    params_m = 0.0
    work_side = 0

    def __init__(self, device: torch.device) -> None:
        self.device = device

    def enhance(self, frame_bgr: np.ndarray) -> np.ndarray:
        return frame_bgr

    def close(self) -> None:
        return None


def available() -> list[str]:
    return list(_ORDER)


def label(name: str) -> str:
    if name in _LABELS:
        return _LABELS[name]
    return str(getattr(_load(name), "LABEL", name))


def device_for(name: str) -> str:  # pragma: no cover - informasi
    return device_label(pick_device())


def _load(name: str):
    if name not in _MODULES:
        raise KeyError(f"model low-light tidak dikenal: {name!r} (pilih {', '.join(_ORDER)}")
    return importlib.import_module(_MODULES[name])


def create(name: str, device: torch.device | str | None = None, work_size: int | None = None):
    dev = device if isinstance(device, torch.device) else pick_device(device)
    if name == "none":
        return Passthrough(dev)
    module = _load(name)
    kwargs = {}
    if work_size:
        kwargs["work_size"] = int(work_size)
    return module.Enhancer(device=dev, **kwargs)
