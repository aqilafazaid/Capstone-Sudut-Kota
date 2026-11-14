"""Inference MirNet v2 “Kaggle” — hasil latihan ``mirnetv2-kaggle.ipynb``.

Arsitektur berbeda dari versi paper: memakai MobileNet-style block + SKFF
dua-input, ``channels=80``, ``channel_factor=1.5``, dan koneksi residual
global. Salinan nama kelas/atribut dipertahankan agar cocok dengan
``../Model/mirnetv2-kaggle.pth``.
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

NAME = "mirnetv2-kaggle"
LABEL = "MirNet v2 (Kaggle)"
MODEL_FILE = "mirnetv2-kaggle.pth"
DEFAULT_WORK_SIDE = 320
MODEL_PATH = LOWLIGHT_DIR / "Mirnet" / "Model" / MODEL_FILE
DEFAULT_WEIGHTS = MODEL_PATH


class SelectiveKernelFeatureFusion(nn.Module):
    def __init__(self, channels: int):
        super(SelectiveKernelFeatureFusion, self).__init__()
        self.hidden_channels = max(int(channels / 8), 4)
        self.average_pooling = nn.AdaptiveAvgPool2d(1)

        self.conv_channel_downscale = nn.Conv2d(channels, self.hidden_channels, kernel_size=1, padding=0)
        self.conv_attention_1 = nn.Conv2d(self.hidden_channels, channels, kernel_size=1, padding=0)
        self.conv_attention_2 = nn.Conv2d(self.hidden_channels, channels, kernel_size=1, padding=0)

        self.leaky_relu = nn.LeakyReLU(negative_slope=0.2)
        self.softmax = nn.Softmax(dim=1)

    def forward(self, inputs):
        combined_input_features = inputs[0] + inputs[1]
        channel_wise_statistics = self.average_pooling(combined_input_features)
        downscaled = self.conv_channel_downscale(channel_wise_statistics)

        attention_vector_1 = self.softmax(self.conv_attention_1(downscaled))
        attention_vector_2 = self.softmax(self.conv_attention_2(downscaled))

        return inputs[0] * attention_vector_1 + inputs[1] * attention_vector_2


class ContextBlock(nn.Module):
    def __init__(self, channels: int):
        super(ContextBlock, self).__init__()
        self.mask_conv = nn.Conv2d(channels, 1, kernel_size=1, padding=0)
        self.channel_add_conv_1 = nn.Conv2d(channels, channels, kernel_size=1, padding=0)
        self.channel_add_conv_2 = nn.Conv2d(channels, channels, kernel_size=1, padding=0)
        self.leaky_relu = nn.LeakyReLU(negative_slope=0.2)

    def modeling(self, inputs):
        b, c, h, w = inputs.shape
        context_mask = self.mask_conv(inputs)
        context_mask = context_mask.view(b, 1, h * w)
        context_mask = nn.functional.softmax(context_mask, dim=-1)
        context_mask = context_mask.permute(0, 2, 1)

        reshaped_inputs = inputs.view(b, c, h * w)
        context = torch.bmm(reshaped_inputs, context_mask)
        return context.view(b, c, 1, 1)

    def forward(self, inputs):
        context = self.modeling(inputs)
        channel_add_term = self.channel_add_conv_1(context)
        channel_add_term = self.leaky_relu(channel_add_term)
        channel_add_term = self.channel_add_conv_2(channel_add_term)
        return inputs + channel_add_term


class ResidualContextBlock(nn.Module):
    def __init__(self, channels: int, groups: int):
        super(ResidualContextBlock, self).__init__()
        self.conv_1 = nn.Conv2d(channels, channels, kernel_size=3, padding=1, groups=groups)
        self.conv_2 = nn.Conv2d(channels, channels, kernel_size=3, padding=1, groups=groups)
        self.leaky_relu = nn.LeakyReLU(negative_slope=0.2)
        self.context_block = ContextBlock(channels=channels)

    def forward(self, inputs):
        x = self.conv_1(inputs)
        x = self.leaky_relu(x)
        x = self.conv_2(x)
        x = self.context_block(x)
        x = self.leaky_relu(x)
        return x + inputs


class DownBlock(nn.Module):
    def __init__(self, channels: int, channel_factor: float):
        super(DownBlock, self).__init__()
        self.average_pool = nn.AvgPool2d(kernel_size=2, stride=2)
        self.conv = nn.Conv2d(channels, int(channels * channel_factor), kernel_size=1, stride=1, padding=0)

    def forward(self, inputs):
        return self.conv(self.average_pool(inputs))


class DownSampleBlock(nn.Module):
    def __init__(self, channels: int, scale_factor: int, channel_factor: float):
        super(DownSampleBlock, self).__init__()
        self.layers = nn.ModuleList()
        current = channels
        for _ in range(int(np.log2(scale_factor))):
            self.layers.append(DownBlock(current, channel_factor))
            current = int(current * channel_factor)

    def forward(self, x):
        for layer in self.layers:
            x = layer(x)
        return x


class UpBlock(nn.Module):
    def __init__(self, channels: int, channel_factor: float):
        super(UpBlock, self).__init__()
        self.conv = nn.Conv2d(channels, int(channels // channel_factor), kernel_size=1, stride=1, padding=0)
        self.upsample = nn.Upsample(scale_factor=2, mode="bilinear", align_corners=False)

    def forward(self, inputs):
        return self.upsample(self.conv(inputs))


class UpSampleBlock(nn.Module):
    def __init__(self, channels: int, scale_factor: int, channel_factor: float):
        super(UpSampleBlock, self).__init__()
        self.layers = nn.ModuleList()
        current = channels
        for _ in range(int(np.log2(scale_factor))):
            self.layers.append(UpBlock(current, channel_factor))
            current = int(current // channel_factor)

    def forward(self, x):
        for layer in self.layers:
            x = layer(x)
        return x


class MultiScaleResidualBlock(nn.Module):
    def __init__(self, channels: int, channel_factor: float, groups: int):
        super(MultiScaleResidualBlock, self).__init__()

        self.rcb_top = ResidualContextBlock(int(channels * channel_factor ** 0), groups=groups)
        self.rcb_middle = ResidualContextBlock(int(channels * channel_factor ** 1), groups=groups)
        self.rcb_bottom = ResidualContextBlock(int(channels * channel_factor ** 2), groups=groups)

        self.down_2 = DownSampleBlock(
            channels=int((channel_factor ** 0) * channels), scale_factor=2, channel_factor=channel_factor
        )
        self.down_4_1 = DownSampleBlock(
            channels=int((channel_factor ** 0) * channels), scale_factor=2, channel_factor=channel_factor
        )
        self.down_4_2 = DownSampleBlock(
            channels=int((channel_factor ** 1) * channels), scale_factor=2, channel_factor=channel_factor
        )

        self.up21_1 = UpSampleBlock(
            channels=int((channel_factor ** 1) * channels), scale_factor=2, channel_factor=channel_factor
        )
        self.up21_2 = UpSampleBlock(
            channels=int((channel_factor ** 1) * channels), scale_factor=2, channel_factor=channel_factor
        )
        self.up32_1 = UpSampleBlock(
            channels=int((channel_factor ** 2) * channels), scale_factor=2, channel_factor=channel_factor
        )
        self.up32_2 = UpSampleBlock(
            channels=int((channel_factor ** 2) * channels), scale_factor=2, channel_factor=channel_factor
        )

        self.skff_top = SelectiveKernelFeatureFusion(int(channels * channel_factor ** 0))
        self.skff_middle = SelectiveKernelFeatureFusion(int(channels * channel_factor ** 1))

        self.conv_out = nn.Conv2d(channels, channels, kernel_size=1, padding=0)

    def forward(self, inputs):
        x_top = inputs
        x_middle = self.down_2(x_top)
        x_bottom = self.down_4_2(self.down_4_1(x_top))

        x_top = self.rcb_top(x_top)
        x_middle = self.rcb_middle(x_middle)
        x_bottom = self.rcb_bottom(x_bottom)

        x_middle = self.skff_middle([x_middle, self.up32_1(x_bottom)])
        x_top = self.skff_top([x_top, self.up21_1(x_middle)])

        x_top = self.rcb_top(x_top)
        x_middle = self.rcb_middle(x_middle)
        x_bottom = self.rcb_bottom(x_bottom)

        x_middle = self.skff_middle([x_middle, self.up32_2(x_bottom)])
        x_top = self.skff_top([x_top, self.up21_2(x_middle)])

        return self.conv_out(x_top) + inputs


class RecursiveResidualGroup(nn.Module):
    def __init__(self, channels: int, num_mrb_blocks: int, channel_factor: float, groups: int):
        super(RecursiveResidualGroup, self).__init__()
        self.layers = nn.ModuleList(
            [
                MultiScaleResidualBlock(channels, channel_factor, groups)
                for _ in range(num_mrb_blocks)
            ]
        )
        self.conv_out = nn.Conv2d(channels, channels, kernel_size=3, stride=1, padding=1)

    def forward(self, inputs):
        residual = inputs
        for layer in self.layers:
            residual = layer(residual)
        residual = self.conv_out(residual)
        return residual + inputs


class MirNetv2(nn.Module):
    def __init__(
        self,
        channels: int = 64,
        channel_factor: float = 1.5,
        num_mrb_blocks: int = 2,
        add_residual_connection: bool = False,
    ):
        super(MirNetv2, self).__init__()
        self.add_residual_connection = add_residual_connection
        self.conv_in = nn.Conv2d(3, channels, kernel_size=3, padding=1)

        self.rrg_block_1 = RecursiveResidualGroup(channels, num_mrb_blocks, channel_factor, groups=1)
        self.rrg_block_2 = RecursiveResidualGroup(channels, num_mrb_blocks, channel_factor, groups=2)
        self.rrg_block_3 = RecursiveResidualGroup(channels, num_mrb_blocks, channel_factor, groups=4)
        self.rrg_block_4 = RecursiveResidualGroup(channels, num_mrb_blocks, channel_factor, groups=4)

        self.conv_out = nn.Conv2d(channels, 3, kernel_size=3, padding=1)

    def forward(self, inputs):
        features = self.conv_in(inputs)
        features = self.rrg_block_1(features)
        features = self.rrg_block_2(features)
        features = self.rrg_block_3(features)
        features = self.rrg_block_4(features)
        output = self.conv_out(features)
        if self.add_residual_connection:
            output = output + inputs
        return output


class Enhancer:
    name = NAME
    label = LABEL
    model_file = MODEL_FILE

    def __init__(self, device: torch.device | None = None, work_side: int | None = None, work_size: int | None = None):
        self.device = device or pick_device()
        self.work_side = int(work_side or work_size or DEFAULT_WORK_SIDE)
        self.model = MirNetv2(
            channels=80,
            channel_factor=1.5,
            num_mrb_blocks=2,
            add_residual_connection=True,
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
