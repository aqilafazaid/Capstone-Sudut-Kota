"""Katalog varian low-light: nama stabil + label manusiawi.

Sengaja terpisah dari ``registry.py``: backend Flask perlu menyajikan daftar
model ke frontend, sedangkan ``registry`` mengimpor torch (berat, butuh GPU
runtime). Modul ini hanya data, jadi aman diimpor proses API.
"""

from __future__ import annotations

# Urutan tampil di CLI dan di panel frontend.
ORDER = [
    "none",
    "mirnetv1",
    "mirnetv2_kaggle",
    "mirnetv2_paper",
    "mobile_mirnet",
    "zerodce",
    "cbam_unet_dce",
]

LABELS = {
    "none": "Tanpa low-light (passthrough)",
    "mirnetv1": "MirNet v1",
    "mirnetv2_kaggle": "MirNet v2 (Kaggle)",
    "mirnetv2_paper": "MirNet v2 (paper)",
    "mobile_mirnet": "Mobile-MIRNet",
    "zerodce": "Zero-DCE",
    "cbam_unet_dce": "CBAM-UNet DCE",
}

# Varian yang benar-benar mengubah gambar (bukan passthrough).
ACTIVE = [name for name in ORDER if name != "none"]
