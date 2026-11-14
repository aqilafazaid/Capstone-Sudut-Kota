# LowLightEnhancement

Dua keluarga model peningkatan cahaya rendah, masing-masing dengan kode
inference sendiri. Satu varian = satu file Python; tidak ada logika model
yang dicampur antar arsitektur.

```
LowLightEnhancement/
├── common.py              konversi frame/tensor, padding, kurva, kebijakan device
├── catalog.py             nama + label varian (tanpa torch; dibaca Flask)
├── registry.py            nama model -> modul (dipakai main_ai.py & test)
├── Mirnet/
│   ├── Model/             mirnetv1.pth, mirnetv2-kaggle.pth,
│   │                      mirnetv2-paper.pth, mobile-mirnet.pth
│   └── Inference/         mirnetv1.py, mirnetv2_kaggle.py,
│                          mirnetv2_paper.py, mobile_mirnet.py
└── ZeroDCE/
    ├── Model/             zerodce.pth, cbam-unet-dce.pth
    └── Inference/         zerodce.py, cbam_unet_dce.py
```

## Varian

| Nama registry | File kode | Bobot | Notebook asal | Keluaran | Resolusi kerja |
|---|---|---|---|---|---|
| `mirnetv1` | `Mirnet/Inference/mirnetv1.py` | `mirnetv1.pth` | `mirnetv1.ipynb` | gambar | 320 |
| `mirnetv2_kaggle` | `Mirnet/Inference/mirnetv2_kaggle.py` | `mirnetv2-kaggle.pth` | `mirnetv2-kaggle.ipynb` | gambar | 320 |
| `mirnetv2_paper` | `Mirnet/Inference/mirnetv2_paper.py` | `mirnetv2-paper.pth` | `mirnetv2-paper.ipynb` | gambar | 320 |
| `mobile_mirnet` | `Mirnet/Inference/mobile_mirnet.py` | `mobile-mirnet.pth` | `mobile-mirnet.ipynb` | gambar | 320 |
| `zerodce` | `ZeroDCE/Inference/zerodce.py` | `zerodce.pth` | `zerodce.ipynb` | 24 peta kurva | 256 (prediksi) |
| `cbam_unet_dce` | `ZeroDCE/Inference/cbam_unet_dce.py` | `cbam-unet-dce.pth` | `cbam-unet-dce.ipynb` | 24 peta kurva | 256 (prediksi) |

Parameter: MirNet v1 44.05M · MirNet v2 Kaggle 5.88M · MirNet v2 paper 5.86M ·
Mobile-MIRNet 1.53M · Zero-DCE 0.08M · CBAM-UNet DCE 0.06M.

MirNet adalah image-to-image: frame diperkecil ke resolusi kerja, diproses,
lalu diperbesar kembali. Zero-DCE family hanya memprediksi kurva pada 256×256,
lalu kurva itu diterapkan pada frame resolusi penuh sehingga ketajaman asli
tidak hilang.

Di engine (`ai_engine/main_ai.py`) hasil ini **tidak** langsung ditampilkan:
frame kerja AI hanya 960×540, dan hasil model dipakai sebagai pembanding untuk
membentuk LUT pencerahan yang diterapkan ke frame 1920×1080 yang tajam.

## Cara pakai

```python
from model_ai.LowLightEnhancement import registry

enhancer = registry.create("mobile_mirnet", device="cuda", work_size=320)
frame_bgr = enhancer.enhance(frame_bgr)   # uint8, ukuran sama dengan masukan
enhancer.close()
```

Tanpa GPU, `registry.create()` otomatis memakai CPU. `registry.available()`
mengembalikan urutan nama untuk CLI/RTDB, `registry.label()` label manusiawinya.

## Catatan teknis

- Bobot MirNet v1 / v2-Kaggle / Mobile-MIRNet menyimpan key thop
  (`total_ops`, `total_params`). `common.load_state()` membuangnya otomatis;
  pemuatan memakai `strict=True` supaya arsitektur yang tidak cocok langsung
  terlihat.
- Padding refleksi ke kelipatan 8 dilakukan sebelum inferensi MirNet, lalu
  hasilnya dipotong kembali ke ukuran asli.
- Redaman kecerahan Zero-DCE family lewat env: `ZERODCE_BRIGHTNESS` (default
  0.5) dan `CBAM_DCE_BRIGHTNESS` (default 0.5). Nilai 1.0 = efek penuh model.
- Notebook pelatihan tidak disalin ke repo ini; notebook tetap menjadi sumber
  arsitektur dan tiap file inference menyebut notebook asalnya di docstring.
