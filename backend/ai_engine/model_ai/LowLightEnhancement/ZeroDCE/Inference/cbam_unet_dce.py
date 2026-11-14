"""Inference CBAM-UNet DCE — hasil latihan ``cbam-unet-dce.ipynb``.

Varian Zero-DCE dengan attention (CBAM) dan depthwise-separable conv.
Kurva tetap diprediksi di 256x256 lalu diterapkan ke resolusi penuh.
"""

from __future__ import annotations

import os

import torch
import torch.nn as nn
import torch.nn.functional as F

from ...common import (
    LOWLIGHT_DIR,
    count_params_million,
    enhance_with_curves,
    load_state,
    pick_device,
)

NAME = "cbam-unet-dce"
LABEL = "CBAM-UNet DCE"
MODEL_FILE = "cbam-unet-dce.pth"
DEFAULT_WORK_SIDE = 256
MODEL_PATH = LOWLIGHT_DIR / "ZeroDCE" / "Model" / MODEL_FILE
DEFAULT_WEIGHTS = MODEL_PATH


def default_brightness() -> float:
    try:
        return float(os.environ.get("CBAM_DCE_BRIGHTNESS", "0.5"))
    except ValueError:
        return 0.5


class ChannelAttention(nn.Module):
    def __init__(self, in_planes, ratio=16):
        super(ChannelAttention, self).__init__()
        self.avg_pool = nn.AdaptiveAvgPool2d(1)
        self.max_pool = nn.AdaptiveMaxPool2d(1)

        self.fc1 = nn.Conv2d(in_planes, in_planes // ratio, 1, bias=False)
        self.relu1 = nn.ReLU()
        self.fc2 = nn.Conv2d(in_planes // ratio, in_planes, 1, bias=False)
        self.sigmoid = nn.Sigmoid()

    def forward(self, x):
        avg_out = self.fc2(self.relu1(self.fc1(self.avg_pool(x))))
        max_out = self.fc2(self.relu1(self.fc1(self.max_pool(x))))
        return x * self.sigmoid(avg_out + max_out)


class SpatialAttention(nn.Module):
    def __init__(self, kernel_size=7):
        super(SpatialAttention, self).__init__()
        self.conv1 = nn.Conv2d(2, 1, kernel_size, padding=kernel_size // 2, bias=False)
        self.sigmoid = nn.Sigmoid()

    def forward(self, x):
        avg_out = torch.mean(x, dim=1, keepdim=True)
        max_out, _ = torch.max(x, dim=1, keepdim=True)
        out = self.conv1(torch.cat([avg_out, max_out], dim=1))
        return x * self.sigmoid(out)


class CBAMBlock(nn.Module):
    def __init__(self, channels):
        super(CBAMBlock, self).__init__()
        self.ca = ChannelAttention(channels)
        self.sa = SpatialAttention()

    def forward(self, x):
        return self.sa(self.ca(x))


class DSConv(nn.Module):
    def __init__(self, in_ch, out_ch):
        super(DSConv, self).__init__()
        self.depthwise = nn.Conv2d(in_ch, in_ch, 3, 1, 1, groups=in_ch, bias=False)
        self.pointwise = nn.Conv2d(in_ch, out_ch, 1, bias=True)
        self.bn = nn.BatchNorm2d(out_ch)
        self.act = nn.LeakyReLU(0.2, inplace=True)

    def forward(self, x):
        return self.act(self.bn(self.pointwise(self.depthwise(x))))


class DCENet(nn.Module):
    def __init__(self, n_filters=32):
        super(DCENet, self).__init__()

        self.conv1 = DSConv(3, n_filters)
        self.conv2 = DSConv(n_filters, n_filters)
        self.cbam1 = CBAMBlock(n_filters)

        self.down1 = nn.MaxPool2d(2)
        self.conv3 = DSConv(n_filters, n_filters * 2)
        self.cbam2 = CBAMBlock(n_filters * 2)

        self.down2 = nn.MaxPool2d(2)
        self.conv4 = DSConv(n_filters * 2, n_filters * 4)

        self.conv5 = DSConv(n_filters * 4, n_filters * 4)
        self.cbam_mid = CBAMBlock(n_filters * 4)

        self.up1 = nn.Upsample(scale_factor=2, mode="bilinear", align_corners=True)
        self.conv6 = DSConv(n_filters * 4 + n_filters * 2, n_filters * 2)

        self.up2 = nn.Upsample(scale_factor=2, mode="bilinear", align_corners=True)
        self.conv7 = DSConv(n_filters * 2 + n_filters, n_filters)
        self.cbam_out = CBAMBlock(n_filters)

        self.out_conv = nn.Conv2d(n_filters, 24, 3, 1, 1, bias=True)
        self.tanh = nn.Tanh()

    def forward(self, x):
        x1 = self.conv1(x)
        x2 = self.cbam1(self.conv2(x1))

        x3 = self.cbam2(self.conv3(self.down1(x2)))

        x4 = self.conv4(self.down2(x3))

        x5 = self.cbam_mid(self.conv5(x4))

        x6 = self.up1(x5)
        if x6.size(2) != x3.size(2):
            x6 = F.interpolate(x6, size=x3.shape[2:])
        x6 = self.conv6(torch.cat([x6, x3], dim=1))

        x7 = self.up2(x6)
        if x7.size(2) != x2.size(2):
            x7 = F.interpolate(x7, size=x2.shape[2:])
        x7 = self.cbam_out(self.conv7(torch.cat([x7, x2], dim=1)))

        curves = self.tanh(self.out_conv(x7))
        r_list = torch.split(curves, 3, dim=1)
        output = x
        for r in r_list:
            output = output + r * (torch.pow(output, 2) - output)

        return output, curves


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
