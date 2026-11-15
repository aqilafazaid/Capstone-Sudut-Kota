# Yolo

Satu kode deteksi untuk semua bobot `.pt`.

```
Yolo/
├── Model/          yolov8n.pt (training Sudut Kota: Bus, Car, Motorcycle, Truck)
└── Inference/      yolo_inference.py
```

- Bobot yang dipakai: file `.pt` **pertama** (urut nama) di `Model/`. Kalau
  folder kosong, `ultralytics` mengunduh `yolov8n.pt` saat pertama dijalankan.
- Kelas bobot hasil training dipetakan ke kontrak backend lewat `MODEL_CLASSES`:
  `Bus` → `bus`, `Car` → `mobil`, `Motorcycle` → `motor`, `Truck` → `truk`.
  Pemetaan dibaca dari metadata `names` bobot (bukan ID hardcoded), jadi urutan
  kelas hasil training ulang tidak masalah. Bobot COCO lama tetap dikenali;
  kelas lain (orang, rambu, dll.) tidak dihitung dan tidak digambar.
- API (`yolo_inference.VehicleDetector`): `detect(frame)` → list deteksi,
  `counts(detections)` → dict per kelas, `annotate(frame, detections)` →
  gambar kotak di tempat, `close()`.
- Default `imgsz=640`, `conf=0.35`, `iou=0.5`. Turunkan `imgsz` ke 480/416 bila
  butuh FPS lebih tinggi di CPU; akurasi kendaraan kecil ikut turun.
- `CLASS_NAMES` di modul ini adalah kontrak dengan `backend/stats.py`
  (`jumlah_mobil`, `jumlah_motor`, `jumlah_truk`, `jumlah_bus`).
