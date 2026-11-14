"""Detektor YOLO Sudut Kota: satu bobot, satu kelas per jenis kendaraan.

Dipakai ``main_ai.py`` dan test. ``VehicleDetector`` sengaja memisahkan
``detect`` (data) dari ``annotate`` (menggambar) supaya statistik tidak
bergantung pada tampilan.
"""

from __future__ import annotations

import time
from pathlib import Path

import cv2
import numpy as np

NAME = "yolov8n"
LABEL = "YOLOv8n"
MODEL_DIR = Path(__file__).resolve().parents[1] / "Model"

# Kontrak statistik backend: hanya kendaraan ini yang dihitung.
COCO_TARGETS = {2: "mobil", 3: "motor", 5: "bus", 7: "truk"}
CLASS_NAMES = ("mobil", "motor", "truk", "bus")
TARGET_CLASSES = tuple(sorted(COCO_TARGETS))
COLORS = {
    "mobil": (255, 160, 0),
    "motor": (0, 235, 255),
    "truk": (0, 0, 255),
    "bus": (0, 140, 255),
}

DEFAULT_IMGSZ = 640
DEFAULT_CONF = 0.35
DEFAULT_IOU = 0.5


def empty_counts() -> dict[str, int]:
    return {name: 0 for name in CLASS_NAMES}


def resolve_weights(weights: str | Path | None = None) -> str:
    """File .pt pertama di ``Model/``; kalau kosong biarkan ultralytics unduh."""
    if weights:
        return str(weights)
    candidates = sorted(MODEL_DIR.glob("*.pt"))
    return str(candidates[0]) if candidates else "yolov8n.pt"


class VehicleDetector:
    def __init__(
        self,
        weights: str | Path | None = None,
        device: str = "cpu",
        imgsz: int = DEFAULT_IMGSZ,
        conf: float = DEFAULT_CONF,
        iou: float = DEFAULT_IOU,
    ) -> None:
        from ultralytics import YOLO

        self.path = resolve_weights(weights)
        self.imgsz = int(imgsz)
        self.conf = float(conf)
        self.iou = float(iou)
        self.device = device or "cpu"
        self.ms = 0.0

        self.model = YOLO(self.path)
        try:
            self.model.to(self.device)
        except Exception:
            self.device = "cpu"
            self.model.to("cpu")

    def detect(self, frame_bgr: np.ndarray) -> list[dict]:
        """Kotak kendaraan pada satu frame (list of dict)."""
        started = time.perf_counter()
        results = self.model.predict(
            source=frame_bgr,
            imgsz=self.imgsz,
            conf=self.conf,
            iou=self.iou,
            classes=list(TARGET_CLASSES),
            device=self.device,
            verbose=False,
        )
        self.ms = (time.perf_counter() - started) * 1000.0

        detections: list[dict] = []
        if results:
            result = results[0]
            names = result.names
            for box in result.boxes:
                cls_id = int(box.cls[0])
                label = COCO_TARGETS.get(cls_id) or names.get(cls_id, str(cls_id))
                if label not in CLASS_NAMES:
                    continue
                x1, y1, x2, y2 = (int(v) for v in box.xyxy[0].tolist())
                detections.append({
                    "label": label,
                    "conf": round(float(box.conf[0]), 3),
                    "box": [x1, y1, x2, y2],
                })
        return detections

    @staticmethod
    def counts(detections: list[dict]) -> dict[str, int]:
        counts = empty_counts()
        for item in detections:
            label = item.get("label")
            if label in counts:
                counts[label] += 1
        return counts

    def annotate(self, frame_bgr: np.ndarray, detections: list[dict],
                 scale: tuple[float, float] = (1.0, 1.0)) -> np.ndarray:
        """Gambar kotak + label di tempat (in-place), kembalikan frame.

        ``scale`` memetakan koordinat frame kerja AI ke frame tampil
        (resolusi asli), jadi kotak tetap tajam tanpa mendeteksi ulang.
        """
        sx, sy = scale
        factor = min(sx, sy)
        thickness = max(2, int(round(2 * factor)))
        font = 0.45 * max(1.0, factor)
        for item in detections:
            x1, y1, x2, y2 = item["box"]
            if factor != 1.0:
                x1, y1, x2, y2 = (int(round(x1 * sx)), int(round(y1 * sy)),
                                  int(round(x2 * sx)), int(round(y2 * sy)))
            color = COLORS.get(item.get("label"), (0, 255, 0))
            cv2.rectangle(frame_bgr, (x1, y1), (x2, y2), color, thickness)
            text = f"{item['label']} {item.get('conf', 0):.2f}"
            (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, font, thickness)
            top = max(0, y1 - th - 6)
            cv2.rectangle(frame_bgr, (x1, top), (x1 + tw + 6, top + th + 6), color, -1)
            cv2.putText(
                frame_bgr, text, (x1 + 3, top + th + 2),
                cv2.FONT_HERSHEY_SIMPLEX, font, (20, 20, 20), thickness, cv2.LINE_AA,
            )
        return frame_bgr

    def close(self) -> None:
        self.model = None  # type: ignore[assignment]


class NoopDetector:
    """Dipakai saat YOLO dimatikan (``--no-yolo``)."""

    path = "-"
    device = "cpu"
    imgsz = 0
    ms = 0.0

    def detect(self, frame_bgr: np.ndarray) -> list[dict]:  # noqa: ARG002
        return []

    @staticmethod
    def counts(detections: list[dict]) -> dict[str, int]:  # noqa: ARG004
        return empty_counts()

    def annotate(self, frame_bgr: np.ndarray, detections: list[dict],
                 scale: tuple[float, float] = (1.0, 1.0)) -> np.ndarray:  # noqa: ARG002
        return frame_bgr

    def close(self) -> None:
        return None
