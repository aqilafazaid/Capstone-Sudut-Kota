"""Inference Zero-DCE — hasil latihan ``zerodce.ipynb``.

DCE-Net memprediksi 8 kurva (24 kanal) yang menerangkan citra. Kurva
diprediksi pada 256x256 lalu diterapkan pada frame resolusi penuh, persis
seperti sel inferensi notebook, supaya tajam dan cepat.

``BRIGHTNESS`` < 1 meredam efek terlalu terang (notebook CCTV memakai 0.3;
default di sini 0.5 supaya YOLO masih dapat kontras).
"""

from __future__ import annotations

import os

import torch
import torch.nn as nn

from ...common import (
    LOWLIGHT_DIR,
    count_params_million,
    enhance_with_curves,
    load_state,
    pick_device,
)

NAME = "zerodce"
LABEL = "Zero-DCE"
MODEL_FILE = "zerodce.pth"
DEFAULT_WORK_SIDE = 256
MODEL_PATH = LOWLIGHT_DIR / "ZeroDCE" / "Model" / MODEL_FILE
DEFAULT_WEIGHTS = MODEL_PATH


def default_brightness() -> float:
    try:
        return float(os.environ.get("ZERODCE_BRIGHTNESS", "0.5"))
    except ValueError:
        return 0.5


class DCENet(nn.Module):
    """DCE-Net asli (7 conv 3x3, output 24 kanal)."""

    def __init__(self, n_filters=32):
        super(DCENet, self).__init__()
        self.conv1 = nn.Conv2d(3, n_filters, 3, 1, 1, bias=True)
        self.conv2 = nn.Conv2d(n_filters, n_filters, 3, 1, 1, bias=True)
        self.conv3 = nn.Conv2d(n_filters, n_filters, 3, 1, 1, bias=True)
        self.conv4 = nn.Conv2d(n_filters, n_filters, 3, 1, 1, bias=True)
        self.conv5 = nn.Conv2d(n_filters * 2, n_filters, 3, 1, 1, bias=True)
        self.conv6 = nn.Conv2d(n_filters * 2, n_filters, 3, 1, 1, bias=True)
        self.conv7 = nn.Conv2d(n_filters * 2, 24, 3, 1, 1, bias=True)
        self.relu = nn.ReLU(inplace=True)

    def forward(self, x):
        x1 = self.relu(self.conv1(x))
        x2 = self.relu(self.conv2(x1))
        x3 = self.relu(self.conv3(x2))
        x4 = self.relu(self.conv4(x3))
        x5 = self.relu(self.conv5(torch.cat([x3, x4], 1)))
        x6 = self.relu(self.conv6(torch.cat([x2, x5], 1)))
        x_r = torch.tanh(self.conv7(torch.cat([x1, x6], 1)))

        r1, r2, r3, r4, r5, r6, r7, r8 = torch.split(x_r, 3, dim=1)

        x = x + r1 * (torch.pow(x, 2) - x)
        x = x + r2 * (torch.pow(x, 2) - x)
        x = x + r3 * (torch.pow(x, 2) - x)
        enhance_image_1 = x + r4 * (torch.pow(x, 2) - x)
        x = enhance_image_1 + r5 * (torch.pow(enhance_image_1, 2) - enhance_image_1)
        x = x + r6 * (torch.pow(x, 2) - x)
        x = x + r7 * (torch.pow(x, 2) - x)
        enhance_image = x + r8 * (torch.pow(x, 2) - x)
        r = torch.cat([r1, r2, r3, r4, r5, r6, r7, r8], 1)
        return enhance_image_1, enhance_image, r


class Enhancer:
    name = NAME
    label = LABEL
    model_file = MODEL_FILE

    def __init__(self, device: torch.device | None = None, work_side: int | None = None, work_size: int | None = None,
                 brightness: float | None = None):
        self.device = device or pick_device()
        self.work_side = int(work_side or work_size or DEFAULT_WORK_SIDE)
        self.brightness = default_brightness() if brightness is None else float(brightness)
        self.model = DCENet(n_filters=32).to(self.device).eval()
        self.model.load_state_dict(load_state(MODEL_PATH, self.device), strict=True)
        self.params_m = count_params_million(self.model)
        for parameter in self.model.parameters():
            parameter.requires_grad_(False)

    def close(self):
        """Lepas model dari GPU/CPU (dipakai saat ganti varian)."""
        self.model = None

    def enhance(self, frame_bgr):
        return enhance_with_curves(
            self.model, frame_bgr, self.device, self.work_side, self.brightness
        )
