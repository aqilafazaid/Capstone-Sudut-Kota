"""Inference MirNet v1 (44M parameter) — hasil latihan ``mirnetv1.ipynb``.

Arsitektur di bawah ini disalin dari notebook tersebut (bukan disederhanakan)
supaya nama & bentuk parameter cocok dengan ``../Model/mirnetv1.pth``.
"""

from __future__ import annotations

from pathlib import Path

import torch
import torch.nn as nn

from ...common import (
    LOWLIGHT_DIR,
    count_params_million,
    enhance_image_to_image,
    load_state,
    pick_device,
)

NAME = "mirnetv1"
LABEL = "MirNet v1"
MODEL_FILE = "mirnetv1.pth"
DEFAULT_WORK_SIDE = 320
MODEL_PATH = LOWLIGHT_DIR / "Mirnet" / "Model" / MODEL_FILE
DEFAULT_WEIGHTS = MODEL_PATH


# ---------------------------------------------------------------------------
# Building blocks (verbatim dari notebook)
# ---------------------------------------------------------------------------
class DownSample(nn.Module):
    def __init__(self, in_channels):
        super(DownSample, self).__init__()
        self.conv1 = nn.Conv2d(in_channels, in_channels, kernel_size=1)
        self.relu = nn.ReLU()

        self.conv2 = nn.Conv2d(in_channels, in_channels, kernel_size=3, padding=1)

        self.pool = nn.MaxPool2d(2)
        self.conv3 = nn.Conv2d(in_channels, in_channels * 2, kernel_size=1)

        self.skip_pool = nn.MaxPool2d(2)
        self.skip_conv = nn.Conv2d(in_channels, in_channels * 2, kernel_size=1)

    def forward(self, x):
        main = self.relu(self.conv1(x))
        main = self.relu(self.conv2(main))
        main = self.pool(main)
        main = self.conv3(main)

        skip = self.skip_pool(self.skip_conv(x))
        return main + skip


class UpSample(nn.Module):
    def __init__(self, in_channels):
        super(UpSample, self).__init__()
        self.conv1 = nn.Conv2d(in_channels, in_channels, kernel_size=1)
        self.relu = nn.ReLU()

        self.conv2 = nn.Conv2d(in_channels, in_channels, kernel_size=3, padding=1)

        self.upsample = nn.Upsample(scale_factor=2, mode="nearest")

        self.conv3 = nn.Conv2d(in_channels, in_channels // 2, kernel_size=1)

        self.skip_upsample = nn.Upsample(scale_factor=2, mode="nearest")
        self.skip_conv = nn.Conv2d(in_channels, in_channels // 2, kernel_size=1)

    def forward(self, x):
        main = self.relu(self.conv1(x))
        main = self.relu(self.conv2(main))
        main = self.upsample(main)
        main = self.conv3(main)

        skip = self.skip_upsample(self.skip_conv(x))
        return main + skip


class SKFF(nn.Module):
    def __init__(self, channels):
        super(SKFF, self).__init__()
        self.conv_compact = nn.Conv2d(channels, channels // 8, kernel_size=1)
        self.relu = nn.ReLU()

        self.conv_desc1 = nn.Conv2d(channels // 8, channels, kernel_size=1)
        self.conv_desc2 = nn.Conv2d(channels // 8, channels, kernel_size=1)
        self.conv_desc3 = nn.Conv2d(channels // 8, channels, kernel_size=1)

    def forward(self, f1, f2, f3):
        combined = f1 + f2 + f3
        gap = nn.functional.adaptive_avg_pool2d(combined, 1)
        compact = self.relu(self.conv_compact(gap))

        desc1 = nn.functional.softmax(self.conv_desc1(compact), dim=1)
        desc2 = nn.functional.softmax(self.conv_desc2(compact), dim=1)
        desc3 = nn.functional.softmax(self.conv_desc3(compact), dim=1)

        return f1 * desc1 + f2 * desc2 + f3 * desc3


class DAU(nn.Module):
    def __init__(self, channels):
        super(DAU, self).__init__()
        self.conv1 = nn.Conv2d(channels, channels, kernel_size=3, padding=1)
        self.relu = nn.ReLU()
        self.conv2 = nn.Conv2d(channels, channels, kernel_size=3, padding=1)

        self.ca_gap = nn.AdaptiveAvgPool2d(1)
        self.ca_conv1 = nn.Conv2d(channels, channels // 8, kernel_size=1)
        self.ca_conv2 = nn.Conv2d(channels // 8, channels, kernel_size=1)

        self.sa_conv = nn.Conv2d(2, 1, kernel_size=1)
        self.final_conv = nn.Conv2d(channels * 2, channels, kernel_size=1)

    def forward(self, x):
        residual = x
        out = self.relu(self.conv1(x))
        out = self.conv2(out)

        ca = self.ca_gap(out)
        ca = self.relu(self.ca_conv1(ca))
        ca = torch.sigmoid(self.ca_conv2(ca))
        out_ca = out * ca

        avg_out = torch.mean(out, dim=1, keepdim=True)
        max_out, _ = torch.max(out, dim=1, keepdim=True)
        sa_in = torch.cat([avg_out, max_out], dim=1)
        sa = torch.sigmoid(self.sa_conv(sa_in))
        out_sa = out * sa

        concat = torch.cat([out_ca, out_sa], dim=1)
        out = self.final_conv(concat)

        return residual + out


class MRB(nn.Module):
    def __init__(self, channels):
        super(MRB, self).__init__()
        self.dau1 = DAU(channels)
        self.down1_2 = DownSample(channels)
        self.dau2 = DAU(channels * 2)
        self.down2_3 = DownSample(channels * 2)
        self.dau3 = DAU(channels * 4)

        self.up2_1_s1 = UpSample(channels * 2)
        self.up3_2_s1 = UpSample(channels * 4)
        self.up2_1_s1_aux = UpSample(channels * 2)
        self.skff1 = SKFF(channels)

        self.down1_2_s1 = DownSample(channels)
        self.up3_2_s1_direct = UpSample(channels * 4)
        self.skff2 = SKFF(channels * 2)

        self.down1_2_s1_aux = DownSample(channels)
        self.down2_3_s1 = DownSample(channels * 2)
        self.down2_3_s1_direct = DownSample(channels * 2)
        self.skff3 = SKFF(channels * 4)

        self.dau1_2 = DAU(channels)
        self.dau2_2 = DAU(channels * 2)
        self.dau3_2 = DAU(channels * 4)

        self.up2_1_final = UpSample(channels * 2)
        self.up3_2_final = UpSample(channels * 4)
        self.up2_1_final_aux = UpSample(channels * 2)

        self.skff_final = SKFF(channels)

        self.conv_final = nn.Conv2d(channels, channels, kernel_size=3, padding=1)

    def forward(self, x):
        lvl1 = x
        lvl2 = self.down1_2(lvl1)
        lvl3 = self.down2_3(lvl2)

        d1 = self.dau1(lvl1)
        d2 = self.dau2(lvl2)
        d3 = self.dau3(lvl3)

        sk1_out = self.skff1(d1, self.up2_1_s1(d2), self.up2_1_s1_aux(self.up3_2_s1(d3)))
        sk2_out = self.skff2(self.down1_2_s1(d1), d2, self.up3_2_s1_direct(d3))
        sk3_out = self.skff3(self.down2_3_s1(self.down1_2_s1_aux(d1)), self.down2_3_s1_direct(d2), d3)

        d1_2 = self.dau1_2(sk1_out)
        d2_2 = self.dau2_2(sk2_out)
        d3_2 = self.dau3_2(sk3_out)

        out = self.skff_final(d1_2, self.up2_1_final(d2_2), self.up2_1_final_aux(self.up3_2_final(d3_2)))
        return x + self.conv_final(out)


class RRG(nn.Module):
    def __init__(self, num_mrb, channels):
        super(RRG, self).__init__()
        self.layers = nn.ModuleList([MRB(channels) for _ in range(num_mrb)])
        self.conv = nn.Conv2d(channels, channels, kernel_size=3, padding=1)

    def forward(self, x):
        out = x
        for layer in self.layers:
            out = layer(out)
        return x + self.conv(out)


class MIRNet(nn.Module):
    def __init__(self, num_rrg=3, num_mrb=2, channels=64):
        super(MIRNet, self).__init__()
        self.conv_in = nn.Conv2d(3, channels, kernel_size=3, padding=1)
        self.rrgs = nn.ModuleList([RRG(num_mrb, channels) for _ in range(num_rrg)])
        self.conv_out = nn.Conv2d(channels, 3, kernel_size=3, padding=1)

    def forward(self, x):
        x_first = self.conv_in(x)
        out = x_first
        for rrg in self.rrgs:
            out = rrg(out)
        out = self.conv_out(out)
        return x + out


# ---------------------------------------------------------------------------
# Enhancer
# ---------------------------------------------------------------------------
class Enhancer:
    name = NAME
    label = LABEL
    model_file = MODEL_FILE

    def __init__(self, device: torch.device | None = None, work_side: int | None = None, work_size: int | None = None):
        self.device = device or pick_device()
        self.work_side = int(work_side or work_size or DEFAULT_WORK_SIDE)
        self.model = MIRNet(num_rrg=3, num_mrb=2, channels=64).to(self.device).eval()
        self.model.load_state_dict(load_state(MODEL_PATH, self.device), strict=True)
        self.params_m = count_params_million(self.model)
        for parameter in self.model.parameters():
            parameter.requires_grad_(False)

    def close(self):
        """Lepas model dari GPU/CPU (dipakai saat ganti varian)."""
        self.model = None

    def enhance(self, frame_bgr):
        return enhance_image_to_image(self.model, frame_bgr, self.device, self.work_side)
