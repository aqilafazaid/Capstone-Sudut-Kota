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
LABEL = "Yolo v8n"
MODEL_DIR = Path(__file__).resolve().parents[1] / "Model"

# Bobot hasil training Sudut Kota memakai nama kelas bahasa Inggris. Kontrak
# statistik/API/frontend tetap bahasa Indonesia, jadi nama model dipetakan di
# sini — bukan di caller.
MODEL_CLASSES = {
    "bus": "bus",
    "car": "mobil",
    "motorcycle": "motor",
    "truck": "truk",
}
# Bobot COCO lama (2 car, 3 motorcycle, 5 bus, 7 truck) tetap dikenali lewat
# nama di atas; peta ID ini hanya fallback bila bobot tidak membawa ``names``.
COCO_TARGETS = {2: "mobil", 3: "motor", 5: "bus", 7: "truk"}
CLASS_NAMES = ("mobil", "motor", "truk", "bus")
COLORS = {
    "mobil": (255, 160, 0),
    "motor": (0, 235, 255),
    "truk": (0, 0, 255),
    "bus": (0, 140, 255),
}

DEFAULT_IMGSZ = 640
DEFAULT_CONF = 0.35
DEFAULT_IOU = 0.5


def box_iou(a, b) -> float:
    """IoU dua kotak ``[x1, y1, x2, y2]``; 0.0 bila tidak beririsan.

    Dipakai untuk membuang label ganda pada objek yang sama. Kotak tanpa luas
    (lebar/tinggi 0) tidak pernah dianggap beririsan.
    """
    ax1, ay1, ax2, ay2 = (float(v) for v in a)
    bx1, by1, bx2, by2 = (float(v) for v in b)

    lebar = min(ax2, bx2) - max(ax1, bx1)
    tinggi = min(ay2, by2) - max(ay1, by1)
    if lebar <= 0 or tinggi <= 0:
        return 0.0

    irisan = lebar * tinggi
    luas_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    luas_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    gabungan = luas_a + luas_b - irisan
    return irisan / gabungan if gabungan > 0 else 0.0


def empty_counts() -> dict[str, int]:
    return {name: 0 for name in CLASS_NAMES}


def resolve_weights(weights: str | Path | None = None) -> str:
    """File .pt pertama di ``Model/``; kalau kosong biarkan ultralytics unduh."""
    if weights:
        return str(weights)
    candidates = sorted(MODEL_DIR.glob("*.pt"))
    return str(candidates[0]) if candidates else "yolov8n.pt"


def display_label(weights: str | Path | None = None) -> str:
    """Nama model untuk UI: ``Yolo v8n`` untuk bobot bawaan, nama berkas lain."""
    name = Path(weights or resolve_weights()).name
    return LABEL if name == "yolov8n.pt" else name


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
        self.targets = self._class_targets()

    def _class_targets(self) -> dict[int, str]:
        """Peta ID kelas bobot -> label internal, dibaca dari metadata model.

        Urutan ID tidak diasumsikan: bobot hasil training ulang bisa memakai
        urutan apa pun. Nama kelas yang tidak dikenal tidak pernah dihitung.
        """
        names = getattr(self.model, "names", None)
        if not names:
            names = getattr(getattr(self.model, "model", None), "names", None)
        if not names:
            return dict(COCO_TARGETS)
        if isinstance(names, (list, tuple)):
            names = dict(enumerate(names))
        targets: dict[int, str] = {}
        for cls_id, raw in dict(names).items():
            label = MODEL_CLASSES.get(str(raw).strip().lower())
            if label:
                targets[int(cls_id)] = label
        return targets

    def detect(self, frame_bgr: np.ndarray) -> list[dict]:
        """Kotak kendaraan pada satu frame (list of dict)."""
        started = time.perf_counter()
        results = self.model.predict(
            source=frame_bgr,
            imgsz=self.imgsz,
            conf=self.conf,
            iou=self.iou,
            classes=list(self.targets),
            device=self.device,
            verbose=False,
        )
        self.ms = (time.perf_counter() - started) * 1000.0

        detections: list[dict] = []
        if results:
            result = results[0]
            for box in result.boxes:
                label = self.targets.get(int(box.cls[0]))
                if not label:
                    continue
                x1, y1, x2, y2 = (int(v) for v in box.xyxy[0].tolist())
                detections.append({
                    "label": label,
                    "conf": round(float(box.conf[0]), 3),
                    "box": [x1, y1, x2, y2],
                })
        return self.dedupe(detections, self.iou)

    @staticmethod
    def dedupe(detections: list[dict], iou_threshold: float = DEFAULT_IOU) -> list[dict]:
        """Buang label ganda: satu objek hanya boleh muncul sekali.

        NMS ultralytics berjalan **per kelas**, jadi satu kendaraan bisa lolos
        dua kali dengan label berbeda (mis. ``mobil`` 0,71 dan ``truk`` 0,62
        pada kotak yang hampir sama). Deteksi diurutkan dari confidence
        tertinggi; kotak berikutnya dibuang bila IoU dengan kotak yang sudah
        dipertahankan mencapai ``iou_threshold``. Kotak yang lolos dikembalikan
        urut kiri->kanan, atas->bawah agar label tidak melompat antar frame.
        """
        urut = sorted(detections, key=lambda item: item.get("conf", 0.0), reverse=True)
        kept: list[dict] = []
        for item in urut:
            box = item.get("box") or []
            if len(box) != 4:
                continue  # kotak rusak tidak bisa digambar maupun dihitung
            if any(box_iou(box, lain["box"]) >= iou_threshold for lain in kept):
                continue
            kept.append(item)
        kept.sort(key=lambda item: (item["box"][0], item["box"][1]))
        return kept

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
    targets: dict[int, str] = {}

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
