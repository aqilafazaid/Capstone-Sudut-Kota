# Yolo

Satu kode deteksi untuk semua bobot `.pt`.

```
Yolo/
├── Model/          yolov8n.pt (Ultralytics COCO)
└── Inference/      yolo_inference.py
```

- Bobot yang dipakai: file `.pt` **pertama** (urut nama) di `Model/`. Kalau
  folder kosong, `ultralytics` mengunduh `yolov8n.pt` saat pertama dijalankan.
- Kelas yang dihitung hanya kendaraan yang dipakai statistik backend:
  `2` mobil, `3` motor, `5` bus, `7` truk (`COCO_TARGETS`). Kelas lain
  (orang, rambu, dll.) tidak dihitung dan tidak digambar.
- API (`yolo_inference.VehicleDetector`): `detect(frame)` → list deteksi,
  `counts(detections)` → dict per kelas, `annotate(frame, detections)` →
  gambar kotak di tempat, `close()`.
- Default `imgsz=640`, `conf=0.35`, `iou=0.5`. Turunkan `imgsz` ke 480/416 bila
  butuh FPS lebih tinggi di CPU; akurasi kendaraan kecil ikut turun.
- `CLASS_NAMES` di modul ini adalah kontrak dengan `backend/stats.py`
  (`jumlah_mobil`, `jumlah_motor`, `jumlah_truk`, `jumlah_bus`).
