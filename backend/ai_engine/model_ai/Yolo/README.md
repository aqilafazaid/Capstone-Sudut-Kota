# model_ai/Yolo

Satu model saja. Engine memakai file `.pt` **pertama** (urut nama) di folder ini:

```
Yolo/
└── yolov8n.pt      # atau yolov8s.pt — salah satu, jangan dua-duanya
```

Kalau folder kosong, `ultralytics` mengunduh `yolov8n.pt` otomatis saat pertama
kali dijalankan. Kelas yang dihitung tetap COCO: `2` mobil, `3` motor, `5` bus,
`7` truk (lihat `COCO_TARGETS` di `ai_engine/main_ai.py`).
