"""Inference Mobile-MIRNet — hasil latihan ``mobile-mirnet.ipynb``.

Versi ringan (1.5M parameter) untuk CCTV real-time: blok inverted-residual
ala MobileNetV3 + SKFF + koreksi warna global. ``channels=40``, ``num_rrg=3``,
``num_mrb=2`` mengikuti checkpoint ``../Model/mobile-mirnet.pth``.
"""

from __future__ import annotations

import torch
import torch.nn as nn
import torch.nn.functional as F

from ...common import (
    LOWLIGHT_DIR,
    count_params_million,
    enhance_image_to_image,
    load_state,
    pick_device,
)

NAME = "mobile-mirnet"
LABEL = "Mobile-MIRNet"
MODEL_FILE = "mobile-mirnet.pth"
DEFAULT_WORK_SIDE = 320
MODEL_PATH = LOWLIGHT_DIR / "Mirnet" / "Model" / MODEL_FILE
DEFAULT_WEIGHTS = MODEL_PATH


class HSwish(nn.Module):
    def forward(self, x):
        return x * F.relu6(x + 3.0, inplace=True) / 6.0


class SELayer(nn.Module):
    def __init__(self, in_channels, reduction=4):
        super(SELayer, self).__init__()
        reduced = max(in_channels // reduction, 8)
        self.avg_pool = nn.AdaptiveAvgPool2d(1)
        self.fc = nn.Sequential(
            nn.Conv2d(in_channels, reduced, 1, bias=False),
            nn.ReLU(inplace=True),
            nn.Conv2d(reduced, in_channels, 1, bias=False),
            nn.Hardsigmoid(inplace=True),
        )

    def forward(self, x):
        return x * self.fc(self.avg_pool(x))


class MobileNetV3Block(nn.Module):
    """Expansion -> Depthwise (opsional SE) -> Projection linear."""

    def __init__(self, in_channels, out_channels, kernel_size=3, expand_ratio=2,
                 stride=1, use_se=True, drop_prob=0.0):
        super(MobileNetV3Block, self).__init__()
        self.stride = stride
        self.use_residual = (self.stride == 1 and in_channels == out_channels)

        hidden_dim = int(in_channels * expand_ratio)
        layers = []
        if expand_ratio != 1:
            layers.extend([
                nn.Conv2d(in_channels, hidden_dim, 1, 1, 0, bias=False),
                nn.GroupNorm(4, hidden_dim),
                HSwish(),
            ])

        padding = (kernel_size - 1) // 2
        layers.extend([
            nn.Conv2d(hidden_dim, hidden_dim, kernel_size, stride, padding,
                      groups=hidden_dim, bias=False),
            nn.GroupNorm(4, hidden_dim),
            HSwish(),
        ])

        if use_se:
            layers.append(SELayer(hidden_dim))

        layers.extend([
            nn.Conv2d(hidden_dim, out_channels, 1, 1, 0, bias=False),
            nn.GroupNorm(4, out_channels),
        ])

        self.conv = nn.Sequential(*layers)
        self.dropout = nn.Dropout2d(p=drop_prob) if drop_prob > 0 else nn.Identity()

    def forward(self, x):
        if self.use_residual:
            return x + self.dropout(self.conv(x))
        return self.conv(x)


class SKFF(nn.Module):
    def __init__(self, channels):
        super(SKFF, self).__init__()
        reduced = max(channels // 8, 4)
        self.avg_pool = nn.AdaptiveAvgPool2d(1)
        self.conv_du = nn.Sequential(
            nn.Conv2d(channels, reduced, 1, bias=False),
            nn.ReLU(inplace=True),
        )
        self.conv_attn = nn.Conv2d(reduced, channels * 2, 1, bias=False)
        self.softmax = nn.Softmax(dim=1)

    def forward(self, f1, f2):
        batch, channels, _, _ = f1.size()
        z = self.conv_du(self.avg_pool(f1 + f2))
        attention = self.conv_attn(z).view(batch, 2, channels, 1, 1)
        attention = self.softmax(attention)
        return (f1 * attention[:, 0]) + (f2 * attention[:, 1])


class DownSample(nn.Module):
    def __init__(self, in_channels, out_channels):
        super(DownSample, self).__init__()
        self.body = nn.Sequential(
            nn.Conv2d(in_channels, in_channels, 3, stride=2, padding=1,
                      groups=in_channels, bias=False),
            nn.Conv2d(in_channels, out_channels, 1, bias=False),
            nn.GroupNorm(4, out_channels),
            HSwish(),
        )

    def forward(self, x):
        return self.body(x)


class UpSample(nn.Module):
    def __init__(self, in_channels, out_channels):
        super(UpSample, self).__init__()
        self.body = nn.Sequential(
            nn.Conv2d(in_channels, out_channels, 1, bias=False),
            nn.Upsample(scale_factor=2, mode="bilinear", align_corners=False),
            nn.GroupNorm(4, out_channels),
            HSwish(),
        )

    def forward(self, x):
        return self.body(x)


class MRB(nn.Module):
    def __init__(self, channels):
        super(MRB, self).__init__()
        c1, c2, c3 = channels, channels * 2, channels * 4

        self.dau_top = MobileNetV3Block(c1, c1, use_se=True)
        self.dau_mid = MobileNetV3Block(c2, c2, use_se=True)
        self.dau_bot = MobileNetV3Block(c3, c3, use_se=True)

        self.down1 = DownSample(c1, c2)
        self.down2 = DownSample(c2, c3)
        self.up1 = UpSample(c2, c1)
        self.up2 = UpSample(c3, c2)

        self.skff_top = SKFF(c1)
        self.skff_mid = SKFF(c2)

        self.conv_out = nn.Conv2d(c1, c1, 1, bias=False)

    def forward(self, x):
        x_top = x
        x_mid = self.down1(x_top)
        x_bot = self.down2(x_mid)

        x_top = self.dau_top(x_top)
        x_mid = self.dau_mid(x_mid)
        x_bot = self.dau_bot(x_bot)

        x_mid = self.skff_mid(x_mid, self.up2(x_bot))
        x_top = self.skff_top(x_top, self.up1(x_mid))

        return x + self.conv_out(x_top)


class RRG(nn.Module):
    def __init__(self, num_mrb, channels):
        super(RRG, self).__init__()
        self.body = nn.Sequential(*[MRB(channels) for _ in range(num_mrb)])
        self.conv = nn.Conv2d(channels, channels, 3, 1, 1, bias=False)

    def forward(self, x):
        return x + self.conv(self.body(x))


class MobileMIRNet(nn.Module):
    def __init__(self, channels=32, num_rrg=3, num_mrb=2):
        super(MobileMIRNet, self).__init__()
        self.conv_in = nn.Conv2d(3, channels, 3, 1, 1, bias=False)
        self.body = nn.Sequential(*[RRG(num_mrb, channels) for _ in range(num_rrg)])
        self.conv_out = nn.Conv2d(channels, 3, 3, 1, 1, bias=True)

        self.global_pool = nn.AdaptiveAvgPool2d(1)
        self.global_fc = nn.Sequential(
            nn.Conv2d(channels, 16, 1),
            nn.ReLU(inplace=True),
            nn.Conv2d(16, 6, 1),
        )
        self.dropout = nn.Dropout(p=0.2)

    def forward(self, x):
        feat = self.conv_in(x)
        feat = self.body(feat)
        feat = self.dropout(feat)
        local_res = self.conv_out(feat)

        params = self.global_fc(self.global_pool(feat))
        scale, shift = torch.chunk(params, 2, dim=1)

        return x * (1 + scale) + local_res + shift


class Enhancer:
    name = NAME
    label = LABEL
    model_file = MODEL_FILE

    def __init__(self, device: torch.device | None = None, work_side: int | None = None, work_size: int | None = None):
        self.device = device or pick_device()
        self.work_side = int(work_side or work_size or DEFAULT_WORK_SIDE)
        self.model = MobileMIRNet(channels=40, num_rrg=3, num_mrb=2).to(self.device).eval()
        self.model.load_state_dict(load_state(MODEL_PATH, self.device), strict=True)
        self.params_m = count_params_million(self.model)
        for parameter in self.model.parameters():
            parameter.requires_grad_(False)

    def close(self):
        """Lepas model dari GPU/CPU (dipakai saat ganti varian)."""
        self.model = None

    def enhance(self, frame_bgr):
        return enhance_image_to_image(self.model, frame_bgr, self.device, self.work_side)
