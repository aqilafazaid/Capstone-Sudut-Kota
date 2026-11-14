"""Inference MirNet v2 “paper” — hasil latihan ``mirnetv2-paper.ipynb``.

Implementasi mengikuti repo paper (SKFF 2-input, RCB + ContextBlock/GCB,
n_feat=80, n_RRG=4, n_MRB=2). Nama modul sengaja dipertahankan sama dengan
notebook supaya ``bert_load_state_dict`` strict cocok dengan
``../Model/mirnetv2-paper.pth``.
"""

from __future__ import annotations

import numpy as np
import torch
import torch.nn as nn

from ...common import (
    LOWLIGHT_DIR,
    count_params_million,
    enhance_image_to_image,
    load_state,
    pick_device,
)

NAME = "mirnetv2-paper"
LABEL = "MirNet v2 (paper)"
MODEL_FILE = "mirnetv2-paper.pth"
DEFAULT_WORK_SIDE = 320
MODEL_PATH = LOWLIGHT_DIR / "Mirnet" / "Model" / MODEL_FILE
DEFAULT_WEIGHTS = MODEL_PATH


# ---------------------------------------------------------------------------
# SKFF / ContextBlock / RCB
# ---------------------------------------------------------------------------
class SKFF(nn.Module):
    def __init__(self, in_channels, height=3, reduction=8, bias=False):
        super(SKFF, self).__init__()
        self.height = height
        d = max(int(in_channels / reduction), 4)

        self.avg_pool = nn.AdaptiveAvgPool2d(1)
        self.conv_du = nn.Sequential(
            nn.Conv2d(in_channels, d, 1, padding=0, bias=bias), nn.LeakyReLU(0.2)
        )

        self.fcs = nn.ModuleList([])
        for _ in range(self.height):
            self.fcs.append(nn.Conv2d(d, in_channels, kernel_size=1, stride=1, bias=bias))

        self.softmax = nn.Softmax(dim=1)

    def forward(self, inp_feats):
        batch_size = inp_feats[0].shape[0]
        n_feats = inp_feats[0].shape[1]

        inp_feats = torch.cat(inp_feats, dim=1)
        inp_feats = inp_feats.view(
            batch_size, self.height, n_feats, inp_feats.shape[2], inp_feats.shape[3]
        )

        feats_u = torch.sum(inp_feats, dim=1)
        feats_s = self.avg_pool(feats_u)
        feats_z = self.conv_du(feats_s)

        attention_vectors = [fc(feats_z) for fc in self.fcs]
        attention_vectors = torch.cat(attention_vectors, dim=1)
        attention_vectors = attention_vectors.view(batch_size, self.height, n_feats, 1, 1)
        attention_vectors = self.softmax(attention_vectors)

        return torch.sum(inp_feats * attention_vectors, dim=1)


class ContextBlock(nn.Module):
    """Global Context Block (GCB)."""

    def __init__(self, n_feat, bias=False):
        super(ContextBlock, self).__init__()
        self.conv_mask = nn.Conv2d(n_feat, 1, kernel_size=1, bias=bias)
        self.softmax = nn.Softmax(dim=2)
        self.channel_add_conv = nn.Sequential(
            nn.Conv2d(n_feat, n_feat, kernel_size=1, bias=bias),
            nn.LeakyReLU(0.2),
            nn.Conv2d(n_feat, n_feat, kernel_size=1, bias=bias),
        )

    def modeling(self, x):
        batch, channel, height, width = x.size()
        input_x = x.view(batch, channel, height * width).unsqueeze(1)

        context_mask = self.conv_mask(x)
        context_mask = context_mask.view(batch, 1, height * width)
        context_mask = self.softmax(context_mask).unsqueeze(3)

        context = torch.matmul(input_x, context_mask)
        return context.view(batch, channel, 1, 1)

    def forward(self, x):
        return x + self.channel_add_conv(self.modeling(x))


class RCB(nn.Module):
    """Residual Context Block."""

    def __init__(self, n_feat, kernel_size=3, reduction=8, bias=False, groups=1):
        super(RCB, self).__init__()
        act = nn.LeakyReLU(0.2)
        self.body = nn.Sequential(
            nn.Conv2d(n_feat, n_feat, kernel_size=3, stride=1, padding=1, bias=bias, groups=groups),
            act,
            nn.Conv2d(n_feat, n_feat, kernel_size=3, stride=1, padding=1, bias=bias, groups=groups),
        )
        self.act = act
        self.gcnet = ContextBlock(n_feat, bias=bias)

    def forward(self, x):
        res = self.body(x)
        res = self.act(self.gcnet(res))
        return res + x


# ---------------------------------------------------------------------------
# Resizing
# ---------------------------------------------------------------------------
class Down(nn.Module):
    def __init__(self, in_channels, chan_factor, bias=False):
        super(Down, self).__init__()
        self.bot = nn.Sequential(
            nn.AvgPool2d(2, ceil_mode=True, count_include_pad=False),
            nn.Conv2d(in_channels, int(in_channels * chan_factor), 1, stride=1, padding=0, bias=bias),
        )

    def forward(self, x):
        return self.bot(x)


class DownSample(nn.Module):
    def __init__(self, in_channels, scale_factor, chan_factor=2, kernel_size=3):
        super(DownSample, self).__init__()
        modules = []
        for _ in range(int(np.log2(scale_factor))):
            modules.append(Down(in_channels, chan_factor))
            in_channels = int(in_channels * chan_factor)
        self.body = nn.Sequential(*modules)

    def forward(self, x):
        return self.body(x)


class Up(nn.Module):
    def __init__(self, in_channels, chan_factor, bias=False):
        super(Up, self).__init__()
        self.bot = nn.Sequential(
            nn.Conv2d(in_channels, int(in_channels // chan_factor), 1, stride=1, padding=0, bias=bias),
            nn.Upsample(scale_factor=2, mode="bilinear", align_corners=bias),
        )

    def forward(self, x):
        return self.bot(x)


class UpSample(nn.Module):
    def __init__(self, in_channels, scale_factor, chan_factor=2, kernel_size=3):
        super(UpSample, self).__init__()
        modules = []
        for _ in range(int(np.log2(scale_factor))):
            modules.append(Up(in_channels, chan_factor))
            in_channels = int(in_channels // chan_factor)
        self.body = nn.Sequential(*modules)

    def forward(self, x):
        return self.body(x)


# ---------------------------------------------------------------------------
# MRB / RRG / MIRNet_v2
# ---------------------------------------------------------------------------
class MRB(nn.Module):
    def __init__(self, n_feat, height, width, chan_factor, bias, groups):
        super(MRB, self).__init__()
        self.n_feat, self.height, self.width = n_feat, height, width

        self.dau_top = RCB(int(n_feat * chan_factor ** 0), bias=bias, groups=groups)
        self.dau_mid = RCB(int(n_feat * chan_factor ** 1), bias=bias, groups=groups)
        self.dau_bot = RCB(int(n_feat * chan_factor ** 2), bias=bias, groups=groups)

        self.down2 = DownSample(int((chan_factor ** 0) * n_feat), 2, chan_factor)
        self.down4 = nn.Sequential(
            DownSample(int((chan_factor ** 0) * n_feat), 2, chan_factor),
            DownSample(int((chan_factor ** 1) * n_feat), 2, chan_factor),
        )

        self.up21_1 = UpSample(int((chan_factor ** 1) * n_feat), 2, chan_factor)
        self.up21_2 = UpSample(int((chan_factor ** 1) * n_feat), 2, chan_factor)
        self.up32_1 = UpSample(int((chan_factor ** 2) * n_feat), 2, chan_factor)
        self.up32_2 = UpSample(int((chan_factor ** 2) * n_feat), 2, chan_factor)

        self.conv_out = nn.Conv2d(n_feat, n_feat, kernel_size=1, padding=0, bias=bias)

        self.skff_top = SKFF(int(n_feat * chan_factor ** 0), 2)
        self.skff_mid = SKFF(int(n_feat * chan_factor ** 1), 2)

    def forward(self, x):
        x_top = x.clone()
        x_mid = self.down2(x_top)
        x_bot = self.down4(x_top)

        x_top = self.dau_top(x_top)
        x_mid = self.dau_mid(x_mid)
        x_bot = self.dau_bot(x_bot)

        x_mid = self.skff_mid([x_mid, self.up32_1(x_bot)])
        x_top = self.skff_top([x_top, self.up21_1(x_mid)])

        x_top = self.dau_top(x_top)
        x_mid = self.dau_mid(x_mid)
        x_bot = self.dau_bot(x_bot)

        x_mid = self.skff_mid([x_mid, self.up32_2(x_bot)])
        x_top = self.skff_top([x_top, self.up21_2(x_mid)])

        return self.conv_out(x_top) + x


class RRG(nn.Module):
    def __init__(self, n_feat, n_MRB, height, width, chan_factor, bias=False, groups=1):
        super(RRG, self).__init__()
        modules_body = [
            MRB(n_feat, height, width, chan_factor, bias, groups) for _ in range(n_MRB)
        ]
        modules_body.append(nn.Conv2d(n_feat, n_feat, kernel_size=3, stride=1, padding=1, bias=bias))
        self.body = nn.Sequential(*modules_body)

    def forward(self, x):
        res = self.body(x)
        return res + x


class MIRNetV2(nn.Module):
    def __init__(
        self,
        inp_channels=3,
        out_channels=3,
        n_feat=80,
        chan_factor=1.5,
        n_RRG=4,
        n_MRB=2,
        height=3,
        width=2,
        scale=1,
        bias=False,
        task=None,
    ):
        super(MIRNetV2, self).__init__()
        self.task = task
        self.conv_in = nn.Conv2d(inp_channels, n_feat, kernel_size=3, padding=1, bias=bias)

        modules_body = [RRG(n_feat, n_MRB, height, width, chan_factor, bias, groups=g)
                        for g in (1, 2, 4, 4)]

        self.body = nn.Sequential(*modules_body)
        self.conv_out = nn.Conv2d(n_feat, out_channels, kernel_size=3, padding=1, bias=bias)

    def forward(self, inp_img):
        shallow_feats = self.conv_in(inp_img)
        deep_feats = self.body(shallow_feats)

        if self.task == "defocus_deblurring":
            out_img = self.conv_out(deep_feats + shallow_feats)
        else:
            out_img = self.conv_out(deep_feats) + inp_img
        return out_img


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
        self.model = MIRNetV2(
            inp_channels=3,
            out_channels=3,
            n_feat=80,
            chan_factor=1.5,
            n_RRG=4,
            n_MRB=2,
            height=3,
            width=2,
            scale=1,
            bias=False,
            task="lowlight_enhancement",
        ).to(self.device).eval()
        self.model.load_state_dict(load_state(MODEL_PATH, self.device), strict=True)
        self.params_m = count_params_million(self.model)
        for parameter in self.model.parameters():
            parameter.requires_grad_(False)

    def close(self):
        """Lepas model dari GPU/CPU (dipakai saat ganti varian)."""
        self.model = None

    def enhance(self, frame_bgr):
        return enhance_image_to_image(self.model, frame_bgr, self.device, self.work_side)
