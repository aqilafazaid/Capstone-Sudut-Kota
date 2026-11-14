# Sudut Kota — Command Center CCTV & Analitik Lalu Lintas

Frontend statis untuk Sistem Informasi Eksekutif pengawasan CCTV Dishub Kota Pekalongan.
Halaman berjalan tanpa build step dan tanpa server Python: cukup HTML, CSS, dan JavaScript.

> Dokumen ini **selalu diperbarui setiap ada perubahan kode** (endpoint, perilaku, struktur,
> konfigurasi). Kalau sebuah perubahan tidak tercatat di sini, perubahan itu belum selesai.

## Status

| Bagian | Status |
|--------|--------|
| Frontend statis (`frontend/`) | **Selesai** — 9 halaman, pemutar HLS, panel kontrol AI, CRUD node, statistik + ekspor, akses fitur per akun |
| Firebase Auth + Realtime Database | **Aktif** — identitas di Firebase Auth; profil/peran/`akses` dan agregat statistik di RTDB |
| Backend lokal (`backend/`) | Flask API + kolektor statistik + engine AI (ffmpeg/HLS) + scraper feed Instagram (Playwright) |
| Deployment Vercel | Siap — `vercel.json` di root, `outputDirectory: frontend`, `rewrites` `/api` + `/hls` ke Funnel (same-origin) |
| Pengujian | `test/` di root (lokal saja, diabaikan git & Vercel) |

## Navigasi

Menu: **Dashboard · Stream · Statistik · Akun**, seluruhnya disuntikkan `js/app.js` sehingga bar-nya
identik di semua halaman. **Beranda tidak lagi jadi item menu** — logo bundar + tulisan SUDUT KOTA di
kiri navbar yang menjadi tautan ke `index.html` (dan diberi cincin biru saat halaman aktif).

- **Menu mengikuti field `akses` akun**, bukan peran mentah: Dashboard, Stream, Statistik,
  Akun, dan panel Modul AI muncul/hilang seketika saat login, logout, atau saat Administrator
  mengubah sakelar di Kelola Akun. Membuka halaman yang tidak diizinkan menampilkan panel
  “Akses Fitur Dinonaktifkan” di halaman itu sendiri (bukan redirect yang bisa memantul);
  pengguna tanpa sesi diarahkan ke login.
- **Teks berjalan** di bar bawah (tampil ≥1024 px) memakai marquee dua salinan identik yang
  digeser tepat satu salinan, jadi sambungannya tidak terlihat dan tidak ada jeda kosong.
  Kecepatannya tetap ~55 px/detik berapa pun panjang teksnya dan berhenti saat kursor berada di atas
  bar. Bila sistem pengguna mengaktifkan `prefers-reduced-motion`, teks **tetap berjalan** dengan
  kecepatan diturunkan (40 px/detik).
- **Kolom pencarian ada di dalam navbar** dan hanya dirender di halaman Stream, bukan di badan
  halaman. Pada layar < 768 px kolom itu turun menjadi baris kedua di dalam kartu navbar yang sama,
  lalu tautan menu dilipat ke hamburger.
- **Judul tab seragam** — kesembilan halaman memakai pola `… | Sudut Kota Dishub Kota Pekalongan`,
  dengan awalan sesuai isi: `Beranda`, `LIVE CCTV`, `Statistik Lalin`, `Command Center`,
  `Kelola Akun`, `Otorisasi Petugas`, `Registrasi Petugas`, `Registrasi Node`, dan
  `Pemulihan Kata Sandi`. Judul ditulis di `<title>` masing-masing file HTML (bukan di `app.js`),
  jadi menambah halaman baru berarti menyalin akhiran yang sama — itu yang membuat tab tidak
  tertukar saat banyak halaman dibuka bersamaan.

## Tema

**Bawaan gelap.** Tombol tema di navbar menyimpan pilihan di `localStorage` (`color-theme`) dan
berlaku di semua halaman, termasuk Stream, Dashboard, dan Statistik — halaman console memakai
variabel CSS `--sk-*` sehingga tidak ada lagi panel gelap yang tertinggal saat mode terang.

## Struktur

```text
Capstone-Sudut-Kota/
├── frontend/                  ← satu-satunya yang dideploy ke Vercel
│   ├── *.html                 beranda, stream, statistik, dashboard, akun, auth
│   ├── css/style.css
│   ├── js/
│   │   ├── config.js          alamat API/HLS (same-origin atau public-config)
│   │   ├── public-config.js   DIHASILKAN: alamat backend untuk halaman Vercel
│   │   ├── firebase-config.js DIHASILKAN: konfigurasi Firebase Web SDK
│   │   ├── firebase-client.js inisialisasi Firebase App + Auth
│   │   ├── auth.js            sesi, peran, ID token (Firebase Auth)
│   │   ├── store.js           klien /api/nodes + /api/stats/* (tanpa simulasi)
│   │   ├── app.js             navbar, tema, jam, toast
│   │   └── …                  main.js, dashboard.js, add-data.js, akun.js, statistik.js, sosmed.js
│   ├── data/instagram.json    ringkasan kiriman Instagram resmi (bukan data contoh)
│   ├── asset/
├── backend/                   ← jalan di PC operator, tidak pernah di-deploy
│   ├── app.py                 Flask API (127.0.0.1:5000)
│   ├── auth.py                verifikasi Firebase ID token + peran
│   ├── accounts.py            CRUD akun lewat Admin SDK + RTDB
│   ├── nodes.py               penyimpanan SQLite + validasi RTSP
│   ├── social/instagram.py    scrape Instagram asli (Playwright) + cache
│   ├── firebase_init.py       Admin SDK dari backend/.env
│   ├── streamer/hls.py        fallback: RTSP → HLS (ffmpeg polos)
│   ├── ai_engine/
│   │   ├── main_ai.py         engine per kamera: low-light + YOLO → HLS
│   │   ├── engine_manager.py  pengelola proses engine (dipakai app.py)
│   │   └── model_ai/          bobot + kode inference tiap model
│   ├── gateway/               SATU-SATUNYA konfigurasi edge
│   │   ├── nginx.conf         serve frontend/ + proxy /api + /hls dari disk
│   │   ├── start/stop-nginx.*
│   │   ├── tools/nginx/       distribusi nginx Windows (gitignored)
│   │   ├── logs/              (gitignored)
│   │   └── temp/              (gitignored)
│   ├── data/sudutkota.db      konfigurasi kamera (gitignored)
│   ├── media/hls/             keluaran stream per node (gitignored)
│   ├── scripts/               sync_public_config.py, seed_accounts.py, apply_rtdb_rules.py,
│   │                          prune_stats.py (bersihkan agregat RTDB yatim)
│   ├── .env / .env.example
│   └── requirements.txt
├── test/                       ← kode uji (gitignored + vercelignored, lokal saja)
├── docs/                      catatan desain lokal (gitignored)
├── vercel.json                deploy: framework Other, output frontend/
├── .vercelignore              backend/, docs/, tools/, test/ tidak ikut upload
├── start-backend.bat          Windows: nginx + Flask + Tailscale Funnel (satu klik)
├── start-frontend.bat         Windows: server statis loopback 8787 (mode lokal)
└── README.md
```

Satu `vercel.json` di root menetapkan `framework: null` (preset *Other*), tanpa build step,
dan `outputDirectory: "frontend"`. Itu yang menentukan apa yang disajikan, jadi Vercel tidak
lagi memindai `backend/` dan tidak mencari entrypoint Python. `backend/`, `docs/`, dan
`tools/` dibuang dari upload lewat `.vercelignore`. **Root Directory proyek dibiarkan kosong**
(root repo) — mengarahkannya ke `frontend` membuat `vercel.json` di root tidak terbaca.

## Menjalankan Project

Dua mode, keduanya memakai **nginx sebagai pintu masuk** dengan Flask di loopback.

**Cara 1 — frontend di Vercel, satu terminal:**

```bat
start-backend.bat     :: nginx + Flask + Tailscale Funnel
```

`start-backend.bat` menyalakan nginx di `127.0.0.1:8080`, Flask di `127.0.0.1:5000`,
lalu `backend/scripts/funnel_serve.py` yang:

1. menulis `PUBLIC_BACKEND_URL` di `backend/.env` sesuai nama node Tailscale,
2. menjalankan `scripts/sync_public_config.py`, yang memperbarui tiga berkas:
   `frontend/js/firebase-config.js`, `frontend/js/public-config.js`, dan **rewrite
   `/api` + `/hls` di `vercel.json`** (ikuti perintah commit & push yang dicetak),
3. **menunggu `http://127.0.0.1:8080/api/health` menjawab 200** sebelum menyalakan
   `tailscale funnel --bg 8080` — tanpa urutan ini, permintaan pertama dari halaman
   Vercel (termasuk login) menerima **502** selama Flask masih impor modul,
4. menjalankan verifikasi: `/api/health` publik dan preflight CORS untuk origin Vercel,
5. mematikan Funnel lagi saat backend berhenti (hanya bila skrip inilah yang menyalakannya).

Halaman Vercel **tidak** memanggil `*.ts.net` dari peramban. `vercel.json` mem-proxy
`/api/:path*` dan `/hls/:path*` ke Funnel, jadi semua permintaan same-origin. Ini bukan
gaya-gayaan: di mesin operator, `desktop-…ts.net` ada di `hosts` (bagian MagicDNS Tailscale)
dan menunjuk ke IP tailnet `100.x`. Chrome memblokir permintaan dari origin HTTPS publik ke
alamat privat (Private Network Access), sehingga tanpa proxy halaman melaporkan
"Tidak dapat menghubungi …/api/akun/me" walaupun backend sehat. Proxy juga menghapus CORS,
mixed content, dan masalah sertifikat sekaligus.

Konsekuensinya: **cukup `start-backend.bat`** untuk memakai frontend yang sudah ter-deploy.
`start-frontend.bat` hanya untuk menyunting tampilan secara lokal.

Menjalankan `start-backend.bat` dua kali kini aman: bila port 5000 sudah dipegang backend
Sudut Kota yang sehat (`/api/health` menjawab `service: sudut-kota-backend`), instance baru
tidak dijalankan — skrip hanya memastikan Funnel menunjuk ke nginx lalu keluar. Port yang
dipakai proses lain tetap ditolak dengan pesan yang jelas.

Funnel hanya mencapai nginx: `/api` di-proxy ke Flask, `/hls` dilayani dari disk. Flask
tidak pernah dipublikasikan, sehingga `limit_req`, batas body, dan header keamanan nginx
tetap berlaku untuk trafik internet.

**Cara 2 — backend + frontend lokal, Vercel tetap jalan:**

```bat
start-backend.bat     :: terminal 1 -> nginx 8080 + Funnel untuk Vercel
start-frontend.bat    :: terminal 2 -> http://127.0.0.1:8787 (browser terbuka sendiri)
```

Halaman 8787 memanggil `http://127.0.0.1:5000` langsung (`js/config.js` memilih sendiri)
untuk siklus edit cepat; buka `http://127.0.0.1:8080` untuk menguji jalur nginx yang sama
dengan produksi. Funnel tetap menyala, jadi halaman Vercel ikut berfungsi.
`start-frontend.bat` memeriksa `/api/health` lebih dulu dan memberi peringatan bila backend
belum jalan (tanpa backend, login di 8787 akan gagal).

Server statis 8787 **hanya listen di loopback** — tidak ada akses dari LAN. Keduanya
berhenti dengan `Ctrl+C`; `start-frontend.bat` menerima port lain
(`start-frontend.bat 8788`) dan tidak membuka browser bila `SK_NO_OPEN=1`.
`start-backend.bat` memakai port tetap (5000 Flask, 8080 nginx). Set `SK_NO_FUNNEL=1` untuk
menjalankan backend tanpa membuka akses publik.

Funnel harus diaktifkan sekali per mesin di konsol admin Tailscale; bila belum, skrip
mencetak tautannya dan backend tetap jalan — halaman 8787 tidak terpengaruh.

### Hasil uji dua cara menjalankan

Diuji langsung di mesin operator (Windows, `cmd`), bukan asumsi:

| Skenario | Hasil |
|---|---|
| Cara 1 — hanya `start-backend.bat` | Flask `127.0.0.1:5000` + nginx `127.0.0.1:8080` hidup bersama, `/api/health` keduanya **200**, halaman 8080 **200**, Funnel `verifikasi: OK` |
| Cara 2 — `start-backend.bat` + `start-frontend.bat` | 5000, 8080, dan 8787 hidup bersamaan; `8787/index.html` **200**; halaman 8787 memakai `backendBase = http://127.0.0.1:5000` dan feed termuat; preflight CORS dari origin 8787 dibalas `Access-Control-Allow-Origin: http://127.0.0.1:8787` |
| `start-backend.bat` dijalankan dua kali | Instance kedua **tidak** dibuat: "Flask sudah berjalan dan sehat; instance kedua tidak dijalankan" + "nginx sudah jalan (pid …), dipakai ulang" + verifikasi Funnel; listener `:5000` tetap **1** |
| `start-frontend.bat` dijalankan dua kali | Berhenti dengan pesan "Port 8787 sudah dipakai proses lain" dan saran `start-frontend.bat 8788`; server lama tidak terganggu |
| `start-frontend.bat` tanpa backend | Memberi peringatan "Backend belum menjawab di http://127.0.0.1:5000/api/health" lalu tetap menyajikan halaman (login/statistik baru gagal) |
| Flask dimatikan paksa saat backend jalan | Skrip backend melakukan pembersihan: nginx dihentikan dan Funnel di-reset, port 5000/8080 kembali bebas |

Catatan saat memeriksa proses: satu instance Flask tampil sebagai **dua** `python.exe` — proses
induk `backend\.venv\Scripts\python.exe` dan anaknya interpreter dasar. Itu normal (venv
redirector Windows), bukan dua server; yang menentukan hanya **satu** listener di `:5000`.
nginx juga tampil dua proses: master (PID di `backend\gateway\logs\nginx.pid`) dan worker.

### Jika login dari Vercel gagal

| Gejala | Sebab | Tindakan |
|---|---|---|
| "Tidak dapat menghubungi …/api/akun/me" padahal `https://<node>.ts.net/api/health` 200 lewat `curl` | Peramban memanggil `*.ts.net` yang di `hosts` menunjuk IP tailnet `100.x`; Chrome memblokir origin HTTPS publik → alamat privat (Private Network Access) | Pastikan `vercel.json` memuat `rewrites` `/api/:path*` dan `/hls/:path*` (dibuat `sync_public_config.py`), lalu commit + push. Halaman Vercel harus memanggil `/api/...` same-origin, bukan `https://<node>.ts.net`. |
| `/api/health` lewat Vercel 404, bukan JSON backend | `vercel.json` belum punya `rewrites`, atau deployment lama masih dipakai | Jalankan `python backend/scripts/sync_public_config.py`, commit, push, tunggu build Vercel selesai. |
| Halaman Vercel memuat tetapi API 502 | Funnel menyala sebelum Flask siap, atau backend mati | `start-backend.bat` menunggu `/api/health` dulu. Cek `http://127.0.0.1:8080/api/health`; bila 502, Flask belum jalan. |
| `/api/...` lewat Vercel 502 dengan header `X-Vercel-Error: ROUTER_EXTERNAL_TARGET_HANDSHAKE_ERROR` | Funnel baru dinyalakan; edge Vercel belum berhasil handshake TLS ke ingress Tailscale | Tunggu ~1 menit lalu muat ulang. Bila menetap: `tailscale funnel reset` lalu `start-backend.bat`. |
| `auth/unauthorized-domain` atau tautan reset kata sandi ditolak | Domain Vercel belum terdaftar di Firebase → Authentication → Settings → Authorized domains | Tambahkan `capstone-sudut-kota.vercel.app` (preview tidak bisa wildcard di Firebase). |
| Login berhasil tetapi halaman menolak akses | Profil RTDB tidak punya fitur yang diminta | Administrator membuka Kelola Akun dan menyalakan sakelar fitur terkait. |

Cek cepat dari mesin operator — tiga jalur berbeda:

```bash
# 1. backend langsung (melewati Vercel)
curl -s https://<node>.ts.net/api/health

# 2. lewat proxy Vercel: harus mengembalikan JSON backend, bukan 404
curl -s https://capstone-sudut-kota.vercel.app/api/health

# 3. preflight CORS langsung ke Funnel (masih dipakai mode 8787/dev)
curl -s -o /dev/null -D - -X OPTIONS https://<node>.ts.net/api/akun/me \
     -H "Origin: https://capstone-sudut-kota.vercel.app" \
     -H "Access-Control-Request-Method: GET" | grep -i access-control-allow-origin
```

Langkah manual (setara dua skrip di atas):

**Terminal 1 — nginx + Flask:**

```bash
bash backend/gateway/start-nginx.sh      # http://127.0.0.1:8080
cd backend
.venv/Scripts/activate
python app.py                            # loopback:5000, di-proxy nginx
```

**Terminal 2 — frontend statis (opsional, mode lokal):**

```bash
cd frontend
python -m http.server --bind 127.0.0.1 8787
# buka http://127.0.0.1:8787
```

nginx menyajikan `frontend/` sekaligus `/api` dan `/hls` dari satu origin; pada jalur ini
segmen HLS dilayani langsung dari disk, tidak melewati Python. Pola yang diizinkan:
`index.m3u8`, `init.mp4`, `seg_*.m4s` (engine AI, fMP4) dan `seg_*.ts` (ffmpeg polos).
Flask tetap punya route `/hls/<path>` (allowlist yang sama) hanya untuk mode dev tanpa
nginx.

Bila `backend/.venv` belum ada:

```bash
cd backend
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt
```

Cek cepat: `curl http://127.0.0.1:8080/api/health` → `{"status":"ok",...}`.

### Penyimpanan data

| Data | Lokasi | Catatan |
|---|---|---|
| Konfigurasi kamera (RTSP) | `backend/data/sudutkota.db` (SQLite) | sumber kebenaran; RTSP tidak pernah dikirim ke peramban |
| Identitas operator | Firebase Authentication | email + kata sandi |
| Profil & peran operator | RTDB `<RTDB_ROOT>/akun/<uid>` | ditulis backend lewat Admin SDK, bukan klien |
| Statistik | RTDB `<RTDB_ROOT>/statistik/<tanggal>/<jam>/<node>` dan `<RTDB_ROOT>/statistik_harian/<tanggal>/<node>` | agregat sampel telemetri AI + agregat harian, ditulis kolektor backend. **Satu-satunya sumber angka**; tidak ada simulasi di peramban |
| Konfigurasi Firebase Web SDK | `backend/.env` → `frontend/js/firebase-config.js` | kunci publik; hasil `sync_public_config.py` |
| Alamat backend untuk Vercel | `vercel.json` → `rewrites` `/api` + `/hls`; `frontend/js/public-config.js` (`backendBase: ""`, `funnelBase`) | Halaman Vercel memakai origin sendiri; proxy Vercel yang meneruskan ke Funnel |

Tidak ada node bawaan: tabel `nodes` mulai kosong dan backend tidak pernah menanam node
sendiri. `POST /api/nodes/reset` mengosongkan direktori beserta folder HLS-nya.

### Sinkronisasi data

| Data | Pemilik (satu-satunya) | Dibaca lewat |
|---|---|---|
| Node CCTV | `backend/data/sudutkota.db` (SQLite) | `GET /api/nodes`, cache `sudutkota.nodes.cache.v3` |
| Akun | Firebase Auth (identitas) + RTDB `<RTDB_ROOT>/akun/<uid>` (profil, peran, `akses`) | `GET /api/akun/me`, `GET /api/akun` |
| Statistik | RTDB `<RTDB_ROOT>/statistik*` | `GET /api/stats/telemetry` (agregat), `GET /api/stats/live` (snapshot) |

Periksa ketiganya sekaligus (read-only):

```bash
backend/.venv/Scripts/python.exe test/check_sync.py
```

Skrip ini membandingkan isi SQLite dengan `/api/nodes`, memastikan statistik hanya berasal
dari RTDB, dan mencocokkan user Firebase Auth dengan profil RTDB. Id statistik yang tidak
punya node di SQLite dilaporkan sebagai `WARN` — arsip lama tetap tersimpan sampai dibersihkan:

```bash
cd backend
.venv/Scripts/python.exe scripts/prune_stats.py --dry-run   # lihat yang akan dibuang
.venv/Scripts/python.exe scripts/prune_stats.py             # cadangkan JSON lalu hapus
```

Cadangan ditulis ke `backend/data/backup/stats-prune-<stamp>.json` sebelum penghapusan, jadi
arsip bisa dikembalikan. **Perhatian:** bila direktori node kosong, semua arsip dianggap yatim —
purge akan mengosongkan halaman Statistik. Dalam kondisi itu skrip menghapus kedua koleksi
sekaligus (bukan per entri) beserta metadata seed `statistik_meta`, sehingga
`/api/stats/telemetry` melaporkan `has_data: false` dan halaman menampilkan
"belum ada data di Firebase".

Klien tidak pernah membaca atau menulis RTDB. Semua akses data lewat backend, sehingga
rules RTDB dapat menolak seluruh akses klien:

```bash
cd backend
python scripts/apply_rtdb_rules.py            # terapkan scripts/rtdb-rules.json
python scripts/apply_rtdb_rules.py --show     # lihat aturan aktif
```

### Engine AI — satu folder per cara inferensi

`ai_engine/main_ai.py` adalah jembatan tiga keluarga model. Satu proses per kamera,
dengan **dua laju** yang terpisah:

```text
RTSP → jalur tampilan: frame asli 1920x1080 + LUT pencerahan + kotak + HUD → ffmpeg → HLS
     ↘ jalur AI (thread sendiri): frame kecil 960x540 → low-light → YOLO → kotak + LUT
```

HUD di dalam video ditulis **dua baris di sudut kiri-bawah** — model low-light,
bobot YOLO, dan perangkat pemroses (`GPU · <nama>` / `CPU`). Kiri-bawah dipilih
karena kamera Pekalongan ini sudah membakar OSD-nya sendiri di kiri-atas (nama
dinas), kanan-atas (jam), dan kanan-bawah (lokasi); versi sebelumnya di kiri-atas
menimpa OSD kamera. Teksnya putih dengan tepi hitam tebal + bayangan 2 px, tanpa
kotak latar. Tanggal/jam dan hitungan kendaraan tidak dicetak ke video — angkanya
ada di kartu halaman CCTV dan RTDB.

Model butuh 100–250 ms/frame; menulis 1080p ke HLS hanya ~40 ms. Kalau keduanya
dijalankan berurutan, video jadi 3–5 fps. Karena itu AI berjalan di **tiga
thread** yang tidak pernah ditunggu jalur tampilan:

| Thread | Kerja | Laju |
|---|---|---|
| `ai-prep` | perkecil frame asli → `AI_AI_SIDE` | tiap frame |
| `ai-enhance` | model low-light → LUT kecerahan | `AI_ENHANCE_HZ` (default 6x/dtk) |
| `ai-detect` | YOLO pada frame kecil + LUT | secepat perangkat (±laju sumber) |

Kuncinya: LUT kecerahan berubah lambat, jadi model termahal tidak perlu
dijalankan tiap frame — yang perlu tiap frame hanya YOLO (18 ms). Dengan
pemisahan ini deteksi ikut laju sumber (terukur **24,9 deteksi/dtk** pada
sumber 25 fps), bukan 9/dtk seperti saat enhance + YOLO berurutan.

Yang tampil tetap frame asli yang tajam, bukan hasil upscale 960 → 1080; efek
low-light-nya mendekati model (kurva gamma per kanal yang menyamakan rata-rata
tiap kanal dengan keluaran model), bukan identik.

**Pemakaian perangkat** (RTX 3050 Laptop, kanvas 1920x1080, kerja AI 960x540):

| | sebelum | sesudah |
|---|---|---|
| deteksi | 9/dtk (serial) | **24,9/dtk** |
| enhance Mobile-MIRNet | 89 ms (FP32) | **68 ms (FP16)** |
| encoder | libx264 (CPU) | **NVENC (GPU)**, CPU 37% → 31% |
| fps tampil (sumber stabil) | 24,4 | 24,5 |

FP16 memotong waktu model ~1,4x (`AI_FP16=0` untuk mematikan). NVENC
memindahkan encoding dari CPU ke GPU; `AI_ENCODER=libx264` memaksa software.

Satu file kode per arsitektur, seperti isi notebook pelatihannya:

| Folder | Bobot | Kode inference |
|---|---|---|
| `LowLightEnhancement/Mirnet/Model` | `mirnetv1.pth`, `mirnetv2-kaggle.pth`, `mirnetv2-paper.pth`, `mobile-mirnet.pth` | `Inference/mirnetv1.py`, `mirnetv2_kaggle.py`, `mirnetv2_paper.py`, `mobile_mirnet.py` |
| `LowLightEnhancement/ZeroDCE/Model` | `zerodce.pth`, `cbam-unet-dce.pth` | `Inference/zerodce.py`, `cbam_unet_dce.py` |
| `Yolo/Model` | `yolov8n.pt` (file `.pt` pertama) | `Inference/yolo_inference.py` (satu untuk semua `.pt`) |

`LowLightEnhancement/registry.py` menyatukan nama model yang dipakai CLI dan RTDB:
`none`, `mirnetv1`, `mirnetv2_kaggle`, `mirnetv2_paper`, `mobile_mirnet`,
`zerodce`, `cbam_unet_dce`. Varian MirNet memakai inferensi image-to-image (resolusi
kerja dibatasi `DEFAULT_WORK_SIDE`); Zero-DCE family memprediksi kurva di 256² lalu
menerapkannya pada resolusi penuh, jadi detail tidak hilang.

Kapasitas jalur tampilan terukur di RTX 3050, kanvas **1920x1080** (resolusi
asli), kerja AI **960x540**, YOLOv8n @ imgsz 640. Angka ini FPS video yang
tampil — tidak lagi dipotong waktu model, karena AI berjalan di thread sendiri:

| Varian | fps tampil | enhance (ms, di worker) |
|---|---|---|
| `zerodce` | 24,1 | ~50 |
| `cbam_unet_dce` | 24 | ~105 |
| `mobile_mirnet` | 24,3 | ~166 |
| tanpa low-light | 24,3 | – |

Pembanding: sebelum dipisah, `mobile_mirnet` hanya 4,3 fps pada kanvas yang
sama. `AI_MAX_SIDE=960` masih bisa dipakai kalau CPU/GPU sangat terbatas, tapi
tayangan jadi lebih lunak. Menurunkan `AI_AI_SIDE` (mis. 640) mempercepat worker
(lebih banyak frame AI per detik), bukan fps tampilan.

Encoder memakai `-crf 20` (sebelumnya 23) supaya teks HUD dan tepi objek tidak
"meleleh" di bitrate rendah; selisih ukuran segmen masih kecil untuk kanal ini.

Catatan teknis worker: `torch.backends.cudnn.benchmark` dimatikan di dalam
`AiWorker` karena autotune cudnn bisa **macet** kalau dipanggil dari thread
non-utama saat pertama melihat ukuran input baru (terbukti hang pada
Mobile-MIRNet 960x540).

FPS yang tampil tidak bisa melebihi laju sumber RTSP. Pada tautan uji Tailscale
laju kamera berayun 2,7–26 fps (p99 jeda antar-frame 0,6–7 dtk), jadi
`server_fps` ikut turun walaupun kapasitas pipeline masih tersisa. Kamera yang
mengirim beberapa frame sekaligus lalu diam juga membuat antrean 1-frame
membuang burst; `AI_SOURCE_BUFFER=3` (default) menahan tiga frame sehingga
output mengikuti `fps_in` selama tautan sehat (terukur 20,4 fps tampil pada
`fps_in` 21,5), dengan tambahan latensi ~0,12 dtk. Isi 1 kalau tautannya stabil
dan latensi paling penting. Default produksi `AI_LOWLIGHT_MODEL=mobile_mirnet`;
pakai `zerodce`/`cbam_unet_dce` bila tautan sanggup mengirim di atas 5 fps.

### Mesin tanpa GPU (CPU + RAM saja)

`AI_DEVICE=auto` (default) memakai GPU NVIDIA bila ada; kalau tidak, seluruh
model berjalan di CPU tanpa perubahan kode. Mode CPU menyesuaikan diri:

- frame kerja AI otomatis **640 px** (bukan 960) dan `AI_ENHANCE_HZ` turun ke
  1,5x/dtk, karena Mobile-MIRNet di CPU ±1 dtk/frame;
- `torch.set_num_threads()` dan `cv2.setNumThreads()` diisi jumlah core
  (`AI_CPU_THREADS` untuk membatasi);
- video tetap **~real-time**: terukur 24,1 fps tampil dengan deteksi 6,9/dtk
  pada sumber 25 fps — jalur tampilan tidak menunggu model.

`AI_DEVICE=cpu` memaksa CPU meski GPU ada (untuk menguji/membandingkan).
Encoder tetap memilih NVENC bila GPU ada, karena encoding tidak memakai
device AI; `AI_ENCODER=libx264` memaksa software total.

Statistik:

- **FPS** punya satu definisi di server dan di peramban: **jumlah frame dibagi
  waktu nyata pada titik decode**. Engine menghitung `server_fps` = frame yang
  ditulis ke encoder ÷ detik nyata (jendela 2,5 dtk, `FpsMeter`); halaman CCTV
  menghitung angka yang sama dari `video.getVideoPlaybackQuality().totalVideoFrames`
  dan menampilkannya di kartu **FPS**. `fps_in`, `enhance_ms`, `yolo_ms`,
  `latency_ms` tetap dikirim terpisah ke RTDB `cam_<channel>` dan
  `media/hls/<node>/ai_stats.json`. Sejak jalur AI dipisah, `enhance_ms`/`yolo_ms`
  adalah waktu per frame **AI** (worker), bukan per frame tampilan.
- Kedua angka bisa berbeda sesaat: pemutar berada beberapa detik di belakang dan
  membuang frame saat menyusul live edge (terukur 1–2 frame/dtk saat tautan
  goyah). Pada jendela panjang keduanya bertemu — terukur 7,63 fps (server) vs
  7,86 fps (peramban) pada jendela 26 dtk.
- Semua I/O Firebase berjalan di thread `RtdbBridge`: loop frame hanya menitipkan
  payload terbaru, jadi satu panggilan jaringan yang lambat tidak lagi menahan
  video (dulu terbaca 6,6 fps tanpa RTDB vs 2,6 fps dengan RTDB).
- Hitungan YOLO (`mobil`, `motor`, `truk`, `bus`) mengikuti kelas COCO 2/3/7/5;
  `jumlah_*`, `total_kendaraan`, `timestamp`, `status` ditulis tiap 2 detik dan
  dibaca kolektor `backend/stats.py` untuk halaman Statistik.
- Kontrol tanpa restart lewat RTDB `cam_<channel>/ai_status`:
  `lowlight_enabled`, `lowlight_model`, `yolo_enabled`. Panel **Kontrol Modul AI**
  di halaman CCTV menulisnya lewat `POST /api/nodes/<id>/ai`.
- Playlist membawa `EXT-X-PROGRAM-DATE-TIME`, sehingga hls.js tahu waktu rekam
  frame yang sedang diputar (`playingDate`). Badge "Latensi" di halaman CCTV
  menampilkan `Date.now() - playingDate` — latensi hasil akhir di peramban,
  termasuk buffer pemutar, bukan hanya waktu proses. Tanpa nilai itu (mis.
  pemutar native), badge jatuh ke `latency_ms` engine.
- Latensi itu ditentukan dua hal: panjang segmen dan seberapa jauh pemutar
  duduk di belakang live edge. `AI_HLS_GOP` (default 12) memotong keyframe tiap
  12 frame — pada output belasan fps berarti segmen ~1–3 dtk, bukan 6–10 dtk
  seperti saat GOP 30. hls.js menyinkronkan `liveSyncDuration: 2.5` dtk.
  Terukur di peramban: **3,5 dtk** dengan tautan kamera sedang goyah; pada
  tautan yang lebih buruk angkanya naik mengikuti panjang segmen.

`app.py` memakai engine ini saat `AI_ENGINE` aktif (default: otomatis bila
`main_ai.py` + bobot YOLO ada). Bila tidak, ia jatuh ke `streamer/hls.py` (ffmpeg
polos) supaya backend tetap hidup. Hentikan proses lewat `stop.flag` sehingga engine
menutup ffmpeg dan menulis status OFFLINE, bukan dibunuh paksa.

```bash
cd backend
.venv/Scripts/python.exe ai_engine/main_ai.py --benchmark          # semua varian
.venv/Scripts/python.exe ai_engine/main_ai.py --channel 48 --lowlight zerodce
.venv/Scripts/python.exe ai_engine/main_ai.py --channel 48 --no-rtdb --duration 10
```

## Alur stream

```text
CCTV → RTSP (Tailscale) → engine AI (low-light + YOLO) → HLS di disk
                                   ↓
Peramban (Vercel, HTTPS) → Tailscale Funnel → nginx:8080 → /hls (file) + /api (Flask)
```

Vercel hanya menyajikan HTML/CSS/JS. Playlist dan segmen diambil peramban langsung dari
backend lewat Funnel, bukan lewat Vercel — Vercel tidak mem-proxy stream panjang.

| Method | Endpoint | Akses | Fungsi |
|---|---|---|---|
| GET | `/api/health`, `/api/config` | publik | status runtime & konfigurasi publik |
| GET | `/api/nodes` | publik | daftar node (tanpa RTSP) |
| GET | `/hls/<cam>/index.m3u8`, `init.mp4`, `seg_*.m4s` | publik | playlist & segmen fMP4 |
| GET | `/api/streams` | publik | status proses ffmpeg |
| GET | `/api/stats/telemetry` | publik | agregat statistik per jam/hari dari RTDB (`?days=N`) |
| GET | `/api/stats/live` | publik | snapshot terakhir tiap node dari RTDB (`cam_<channel>`) |
| GET | `/api/ai` | publik | katalog varian low-light + bobot YOLO untuk panel kontrol |
| GET | `/api/nodes/<id>` | teknisi, admin | detail + RTSP untuk form edit |
| POST/PUT/DELETE | `/api/nodes[/<id>]` | teknisi, admin | CRUD node |
| POST | `/api/nodes/<id>/ai` | teknisi, admin | tulis `cam_<channel>/ai_status` (low-light on/off, model, YOLO) |
| POST/DELETE | `/api/streams/<cam>` | teknisi, admin | start/stop ffmpeg |
| GET | `/api/status` | teknisi, admin | path database, daftar model |
| POST | `/api/nodes/reset` | teknisi, admin | kosongkan direktori node + folder HLS |
| GET | `/api/sosmed/instagram?page=N&per_page=6` | publik | kiriman Instagram asli (scrape + cache), berhalaman |
| GET | `/api/sosmed/instagram/image/<code>.jpg` | publik | gambar kiriman yang disimpan backend |
| POST | `/api/stats/collect` | teknisi, admin | paksa satu sampel statistik |
| GET/PUT/DELETE | `/api/akun[/<uid>]` | admin | kelola akun petugas |
| GET | `/api/akun/me` | login | profil sendiri |
| POST | `/api/akun/self` | login | buat profil saat pendaftaran (peran visitor) |

Otorisasi memakai header `Authorization: Bearer <idToken>` (Firebase). Peran dan `akses`
diambil dari RTDB dan di-cache 60 detik di backend; pemeriksaan wewenang **tidak** terjadi
di peramban. Halaman tetap memanggil `Auth.can()`/`Auth.guard(feature)` untuk menu dan pagar
tampilan, tetapi itu hanya kosmetik — endpoint tetap menolak sendiri. Endpoint tulis
memakai `@auth.require_feature("dashboard"|"akun")`, yang hanya membaca field `akses`
akun (bawaan peran dipakai bila kunci tidak diset).

`copy: true` meneruskan video apa adanya (hemat CPU); `copy: false` men-transcode H.264
(wajib bila sumber bukan H.264). Engine AI selalu memakai jalur transcode.

**Alamat server dari sisi frontend.** Tiga kasus, ditangani `js/config.js`:

| Halaman dibuka dari | backendBase |
|---|---|
| `http://localhost:8080` (nginx) | `''` — same-origin |
| `http://localhost:8787` (`http.server`) | `http://127.0.0.1:5000` |
| domain Vercel | `window.SK_PUBLIC.backendBase` (dari `PUBLIC_BACKEND_URL`) |

Tanpa `PUBLIC_BACKEND_URL` terisi, halaman Vercel tidak tahu harus memanggil ke mana.

### Akun dan peran

Akun tidak lagi disimpan di peramban. Semua akun adalah user Firebase Authentication
dengan profil di RTDB `/akun/<uid>`:

| Peran | Kode | Akses |
|---|---|---|
| Administrator | `admin` | semua halaman, termasuk Kelola Akun |
| Teknisi | `teknisi` | semua halaman kecuali Kelola Akun; setara Administrator untuk node, stream, AI, dan reset |
| Visitor | `visitor` | hanya Stream dan Statistik; tanpa Dashboard, Tambah Data, Kelola Akun, atau Beranda |

**Akses fitur per akun.** Selain peran, setiap profil punya field
`akses: { cctv, statistik, dashboard, ai, akun }`. Administrator mengaturnya lewat sakelar
di `akun.html` (kolom *Akses Fitur* dan bagian yang sama di modal Tambah/Ubah Akun).
Peran hanya mengisi **nilai bawaan** (Administrator semua, Teknisi tanpa Kelola Akun,
Visitor hanya CCTV + Statistik); kelima sakelar tetap bisa diubah untuk akun mana pun,
jadi Administrator bisa memberi fitur di luar kebiasaan perannya maupun mencabutnya.
Fitur `ai` mengatur panel **Kontrol Modul AI** di halaman CCTV: sakelar low-light dan
YOLO, serta pilihan varian low-light dari katalog engine (`GET /api/ai`). Perubahan
dikirim ke `POST /api/nodes/<id>/ai`, backend menulis `cam_<channel>/ai_status`, dan
engine menerapkannya dalam ~2 detik tanpa restart — panel baru berubah setelah
telemetri menunjukkan engine benar-benar sudah berganti. Bila fitur dicabut, panelnya
disembunyikan dan tayangan tetap berjalan.
Nilai yang tidak ada memakai bawaan peran, sehingga akun lama (tanpa field `akses`)
berperilaku seperti sebelumnya. `PUT /api/akun/<uid>` menggabungkan kiriman parsial
(`{"akses":{"cctv":false}}` hanya mengubah satu fitur), dan mengubah `peran` tanpa
`akses` eksplisit mengembalikan sakelar ke bawaan peran baru. Administrator tidak bisa
mencabut `akun` dari akunnya sendiri (ditolak backend dengan 409) agar tidak terkunci
dari satu-satunya halaman untuk memperbaikinya. Fitur yang tertutup memunculkan panel
"Akses Fitur Dinonaktifkan" di halaman terkait, dan endpoint tulisnya membalas 403.

> Memberi fitur `akun` ke peran non-Administrator berarti memberi wewenang penuh atas
> manajemen akun — termasuk membuat akun Administrator baru. Berikan hanya bila memang
> itu yang diinginkan.

Pendaftaran mandiri (`register.html`) selalu membuat akun Visitor: Firebase Auth membuat
user, lalu `POST /api/akun/self` menulis profilnya. Body `peran` maupun `nip` dari peramban
diabaikan. Akun `admin`/`teknisi` hanya bisa dibuat Administrator lewat `akun.html`
(`POST /api/akun`, role-gated).

NIP dibuat otomatis dan unik saat akun dibuat — juga untuk akun Visitor dari pendaftaran
mandiri: nomor urut per awalan, `ADM-001` (Administrator), `TKS-001` (Teknisi),
`VST-001` (Visitor). NIP tidak bisa diisi dari UI maupun dari body API, dan dibuat ulang
mengikuti peran baru saat peran diubah.

**Akun pertama harus dibuat dari terminal**, karena belum ada admin yang bisa membuka
halaman Kelola Akun:

```bash
cd backend
python scripts/seed_accounts.py --email admin@contoh.go.id --nama "Admin Dishub" --peran admin
```

Kata sandi diminta lewat prompt, tidak masuk riwayat shell.

## Deploy ke Vercel

1. Import repo ini dengan **Root Directory kosong** (root repo, bukan `frontend`).
   `.vercelignore` mengecualikan `backend/`, `docs/`, `tools/`, seluruh launcher
   `*.bat`/`*.sh` (termasuk `start-backend.bat` dan `start-frontend.bat`), serta berkas
   rahasia lokal — jadi hanya isi `frontend/` yang bisa disajikan.
2. Jangan isi Framework Preset / Build Command / Output Directory di dashboard: `vercel.json`
   di root sudah mengunci `framework: null`, `buildCommand: null`, dan
   `outputDirectory: "frontend"`. Framework preset yang tersimpan sebagai Flask akan
   ditimpa, sehingga `backend/app.py` tidak lagi dicari sebagai entrypoint.
3. `start-backend.bat` mengisi `PUBLIC_BACKEND_URL` di `backend/.env` dari nama node
   Tailscale lalu menjalankan `scripts/sync_public_config.py`. Skrip itu menulis tiga berkas:
   `frontend/js/firebase-config.js`, `frontend/js/public-config.js` (backendBase kosong), dan
   `vercel.json` (`rewrites` `/api/:path*` + `/hls/:path*` ke Funnel). Commit ketiganya bila
   berubah — tanpa `rewrites` di build Vercel, `/api/health` di domain Vercel menjawab 404.
4. Tambahkan domain Vercel ke `ALLOWED_ORIGINS` di `backend/.env`, lalu restart Flask. Ini
   hanya dipakai mode lintas-origin (halaman 8787 dan `*.vercel.app` saat proxy dimatikan);
   jalur produksi memakai proxy same-origin.
5. `cleanUrls` aktif, jadi `/cctv` dan `/cctv.html` sama-sama bekerja.

Setelah deploy, uji dari luar mesin operator:

```bash
curl -s https://capstone-sudut-kota.vercel.app/api/health   # harus JSON backend
```

`/api` dan `/hls` melewati edge Vercel (traffic ikut terhitung). Untuk demo capstone ini
wajar; bila kuota jadi masalah, buka halaman lewat `http://127.0.0.1:8080` (nginx lokal).

## Data node (tanpa seed)

**Tidak ada node bawaan.** Database baru selalu kosong, dan backend tidak pernah menanam node
sendiri saat start. Direktori kamera diisi operator lewat **Dashboard → Tambah Data**.

Tombol **Kosongkan direktori** (`POST /api/nodes/reset`, fitur `dashboard`) menghapus seluruh
node beserta folder HLS-nya. Akun Firebase **tidak** ikut terhapus.

- `localStorage['sudutkota.nodes.cache.v3']` — cache baca, bukan sumber kebenaran.
- `localStorage['sudutkota.ai.v1']` — status AI lokal (belum tersinkron ke RTDB).
- `localStorage['sudutkota.backend']` — override alamat backend; kosongkan bila halaman
  Vercel harus memakai proxy `/api` (`localStorage.removeItem('sudutkota.backend')`).

## Kabar terbaru (Instagram)

Seksi **Kabar Terbaru** di beranda menampilkan kiriman asli dari
`@dishub_kotapekalongan` dan `@pjukotapekalongan`, **berhalaman** dan diperbarui backend —
tidak ada input manual, tidak ada kartu contoh.

- **Ambil data**: `backend/social/instagram.py` menjalankan Chromium headless (Playwright)
  sekali per kedaluwarsa cache: buka profil → kumpulkan tautan `/p/` dan `/reel/` → buka
  halaman embed resmi tiap post → ambil caption, tanggal, jumlah suka, dan URL gambar.
  Instagram menutup semua endpoint anonim (429), jadi DOM yang dirender adalah sumbernya.
- **Gambar**: diunduh ke `backend/media/instagram/<code>.jpg` dan disajikan lewat
  `/api/sosmed/instagram/image/<code>.jpg`. Tidak ada hotlink CDN yang bisa kedaluwarsa.
- **Foto profil**: diambil dari `img[alt="Foto profil <handle>"]` di halaman profil, disimpan di
  `backend/media/instagram/avatars/<handle>.jpg` (150 px, tidak diubah ukurannya di URL karena
  URL bertanda tangan jadi 403), dan disajikan lewat
  `/api/sosmed/instagram/avatar/<handle>.jpg`. Setiap scrape menimpanya, jadi avatar ikut berubah
  saat akun mengganti foto profil; browser memvalidasi ulang tiap 10 menit (ETag).
- **Cache**: `backend/data/instagram-cache.json`, umur `IG_CACHE_SECONDS` (default **300 detik** =
  5 menit). Scrape hanya dipicu permintaan pertama setelah cache basi; `IG_HANDLES` mengganti
  daftar akun (default kedua akun di atas). Scrape yang berhenti di tengah menulis cache
  `partial` dengan `fetched_at` lama, dan cache parsial **tidak** dianggap segar — pengunjung
  tidak pernah menerima setengah feed.
- **Refresh di halaman**: `sosmed.js` melakukan refresh senyap tiap **5 menit** hanya untuk area
  feed (`#instagram-feed`, pager, teks "Diperbarui"), tanpa reload halaman dan tanpa skeleton.
  Status **Selengkapnya** yang sedang terbuka dan halaman pager yang aktif dipertahankan; timer
  berhenti saat tab tidak aktif dan menyusul sekali ketika tab kembali terlihat.
- **API**: `GET /api/sosmed/instagram?page=N&per_page=6` → `posts[]` (`handle`, `kind`, `code`,
  `permalink`, `caption`, `date`, `taken_at`, `likes`, `image_ok`), `page`, `pages`, `total`,
  `fetched_at`, `errors[]`.
- **Tanggal unggah**: diturunkan dari shortcode post (41 bit pertama media id = milidetik epoch
  yang digeser `1314220021721` ms), jadi tersedia untuk semua post tanpa API. Setiap kartu
  menampilkan **jumlah suka dan tanggal** sekaligus, mis. `18 suka · 12 Maret 2026`.
- **UI**: kartu berisi gambar, chip akun, caption ringkas, tombol **Selengkapnya/Ringkas**,
  **Lihat di Instagram**, dan pager Sebelumnya/Berikutnya. Bila scrape gagal, yang tampil
  hanya tautan akun — bukan teks karangan.
- **Prasyarat**: `pip install -r requirements.txt` lalu `python -m playwright install chromium`
  (sekali per mesin, ±150 MB). Tanpa Chromium, endpoint mengembalikan `ok:false` dan halaman
  menampilkan tautan akun.

Tombol **Kosongkan direktori** memanggil `POST /api/nodes/reset` (fitur `dashboard`);
direktori node dan folder HLS-nya dihapus. Akun Firebase **tidak** ikut dihapus.

## Titik integrasi backend dan Firebase

Konfigurasi kamera sudah berbicara dengan backend, bukan Firebase. Halaman menunggu
`Store.ready()` sebelum render; `Store.upsert()` dan `Store.remove()` mengembalikan
Promise dan memanggil `/api/nodes`.

```js
// store.js — klien backend + cache
Store.ready()                    Store.isOnline()       Store.config()
Store.list()                     Store.get(id)          Store.byZone()
Store.upsert(camera)             Store.remove(id)       Store.fetchDetail(id)
Store.getAi(id)                  Store.setAi(id, patch)
Store.subscribeTelemetry(id, cb) Store.onChange(cb)
Store.loadStats(force)           Store.statsInfo()      Store.stats(period)

// auth.js — Firebase Auth + peran/akses dari /api/akun/me
Auth.login(identifier, password) Auth.register({...})   Auth.logout()
Auth.user()                      Auth.isOperator()      Auth.isAdmin()
Auth.can(feature)                Auth.guard(feature)    Auth.features()
Auth.featureLabel(feature)       Auth.roleFeatures()    Auth.homeFor(role)
```

Akun sudah sepenuhnya di Firebase Authentication + RTDB, dan statistik dibaca dari
agregat RTDB lewat `Store.loadStats()`. Kartu kendaraan di halaman Stream memakai
`GET /api/stats/live` (snapshot `cam_<channel>` di RTDB) lewat
`Store.subscribeTelemetry()`. Tidak ada angka simulasi di peramban; yang masih lokal
hanya status toggle AI (`localStorage['sudutkota.ai.v1']`).

## Halaman Statistik & Ekspor

`statistik.html` meringkas volume kendaraan dari `Store.stats(period)` dengan tujuh rentang:

| Periode | Bucket | Contoh label |
|---------|--------|--------------|
| 1 Hari | 24 jam | `08:00` |
| 1 Minggu | 7 hari | `Sen 2/11` |
| 1 Bulan | 30 hari | `24/10` |
| 3 Bulan | mingguan | `3/8` |
| 1 Tahun | bulanan | `Mar 26` |
| 5 Tahun | kuartalan | `Q4 2023` |
| Seluruhnya | tahunan (sejak 1 Jan 2019) | `2020` |

Semua periode memakai satu sumber angka per jam, sehingga totalnya konsisten: 1 Hari selalu sama
dengan hari itu di dalam 1 Minggu, dan seterusnya. Isi halaman: KPI (total, mobil, motor, truk, bus,
rata-rata per bucket, bucket tersibuk), grafik batang bertumpuk, donat komposisi, dan tabel rekap
per node yang diurutkan dari volume tertinggi.

**Ringkasan AI untuk Masyarakat** (`#ai-insight-panel`) ada di atas grafik: satu paragraf narasi
plus tiga kartu sorotan (komposisi, titik/jam terpadat, saran perjalanan) dan tombol *Salin
Ringkasan*. Panel ini **tidak** memanggil model — ia membaca angka yang sudah dirender
`statistik.js` (KPI, label rentang, baris tabel) lewat `MutationObserver`, lalu menyusun kalimat.
Karena itu ia otomatis ikut berubah saat periode diganti dan tidak menambah permintaan jaringan.
Halaman CCTV punya padanan `#public-ai-info-panel` yang membaca kartu statistik live dengan pola
yang sama.

Ekspor mengikuti **interval yang sedang dipilih**. Unduhan berisi satu interval saja (mis. `1 Hari`),
kecuali bila yang dipilih **Seluruhnya** — berkasnya tetap memuat ketujuh interval plus tabel
perbandingan, seperti sebelumnya. Nama berkas memakai kunci periode (`statistik-sudut-kota-1d-…`,
`…-lengkap-…` untuk Seluruhnya).

- **PDF** — jsPDF + AutoTable, **ukuran F4/Folio 215 × 330 mm** (≈6 halaman). Halaman 1 dibuka
  **kop surat**: `asset/logo-pemkot.svg` di kiri, `asset/logo-dishub.svg` di kanan, blok teks
  instansi di tengah (nama pemerintah kota, nama dinas, alamat, email/Instagram), lalu garis tebal
  pemisah. Sesudahnya judul laporan, lalu — bila periode = Seluruhnya — tabel *Ringkasan Semua
  Interval* (7 baris), grafik volume dan komposisi, dan satu bagian per interval. Untuk periode
  tunggal hanya ada satu bagian (ringkasan, rekap per node, tabel per bucket + TOTAL) sehingga
  dokumennya 2 halaman, bukan 6. Kaki halaman memuat judul laporan dan nomor halaman.

  jsPDF tidak bisa menanam SVG, jadi tiap logo digambar ke `<canvas>` lebih dulu lalu dikirim sebagai
  PNG. Canvas dibuat **setinggi 512 px dan selebar rasio asli SVG** (bukan persegi), dan kotak di PDF
  memakai rasio gambar yang sama — jadi lambang tidak pernah gepeng. Kedua logo dicetak 20 mm tinggi,
  rata ke margin kiri/kanan.

  Identitas kop ada di satu objek `KOP` di `js/statistik.js` — saat ini PEMERINTAH KOTA PEKALONGAN /
  DINAS PERHUBUNGAN, Jl. Seruni No. 66, dengan baris kontak
  `Email: dishub.pekalongankota@gmail.com   Instagram: @dishub_kotapekalongan   Telp. (0285) 421600`.
  Ubah di situ dan seluruh kop mengikuti.
  Bila logo gagal dimuat, PDF tetap dibuat tanpa logo (ada peringatan di konsol).
- **CSV** — satu berkas teks (`;` sebagai pemisah, UTF-8 + BOM, CRLF) berisi blok *Ringkasan
  Semua Interval* lalu satu blok per interval: ringkasan, `PER NODE` dengan kontribusi %, dan
  `PER <satuan>` + TOTAL. Angka ditulis polos (tanpa titik ribuan) supaya bisa langsung dihitung
  di Excel/Sheets. Tidak ada lagi dependensi SheetJS.

Tombol PDF/CSV selalu berada **di bawah** kelompok interval, di semua lebar layar.

Tata letak kartu judul:

- **≥1280 px** — judul di kiri; di kanan satu kolom berisi baris interval lalu baris tombol ekspor.
- **<1280 px** — judul di atas, kolom kontrol di bawahnya dengan tepi kiri sejajar teks judul.
- **<640 px** — tombol interval menjadi grid 4 kolom (dua baris), tanpa bar geser.

Pustaka ekspor dimuat dari CDN hanya di halaman ini. Angka diambil dari agregat
telemetri AI di RTDB: `<RTDB_ROOT>/statistik/<tanggal>/<jam>/<node>` untuk periode
**1 Hari** dan `<RTDB_ROOT>/statistik_harian/<tanggal>/<node>` untuk periode lain.
Kolektor backend mengambil sampel tiap `STATS_SAMPLE_SECONDS` detik dan mengakumulasi
keduanya sekaligus, sehingga total "1 Hari" selalu sama dengan kontribusi hari itu di
"1 Minggu". Agregat harian dibaca dengan `start_at`/`end_at` pada kunci tanggal, jadi
satu muat halaman tidak pernah menarik seluruh arsip jam (yang berarti ±26.000 record
untuk satu tahun). Sampel yang lebih tua dari `STATS_STALE_SECONDS` dilewati agar stream
mati tidak menambah angka.

Selama belum ada satu pun sampel (mis. AI belum berjalan), halaman menampilkan nol dan
menandainya **belum ada data di Firebase**. **Tidak ada data contoh dan tidak ada endpoint
penyemai statistik**: satu-satunya penulis koleksi ini adalah kolektor backend dari snapshot
AI sungguhan. Bila butuh mengosongkan arsip, pakai `backend/scripts/prune_stats.py`
(lihat *Sinkronisasi data*).

Rentang baca dibatasi `STATS_MAX_DAYS` hari (default 4000, cukup untuk periode
"Seluruhnya").

## Pengujian

Seluruh kode uji, audit, dan diagnosa berada di `test/` di root repo. Direktori itu
**diabaikan git dan Vercel** (`.gitignore` + `.vercelignore` memuat `test/`), jadi tidak
pernah ikut commit atau deploy — hanya ada di mesin operator.

```bash
# dari root repo (semua skrip berdiri sendiri)
backend/.venv/Scripts/python.exe test/test_node_no_seed.py     # tidak ada seed node
backend/.venv/Scripts/python.exe test/test_stats_live.py       # normalisasi /api/stats/live
backend/.venv/Scripts/python.exe test/test_akses_backend.py    # matriks peran x fitur
backend/.venv/Scripts/python.exe test/test_akses_routes.py     # dekorator fitur di route
backend/.venv/Scripts/python.exe test/test_hls_stream.py       # argumen ffmpeg + purge/prune
backend/.venv/Scripts/python.exe test/test_hls_crud.py         # CRUD node membersihkan media/
backend/.venv/Scripts/python.exe test/test_hls_ffmpeg_e2e.py   # HLS ffmpeg polos: segmen ~2 dtk
backend/.venv/Scripts/python.exe test/test_ai_models.py        # 6 enhancer + YOLO: strict load, FPS
backend/.venv/Scripts/python.exe test/test_ai_engine_e2e.py    # file gelap -> HLS AI + ai_stats
backend/.venv/Scripts/python.exe test/test_ai_control.py       # katalog AI + POST ai_status (mock RTDB)

# diagnosa read-only (butuh backend/.env berisi kredensial)
backend/.venv/Scripts/python.exe test/check_auth_cfg.py        # authorized domains + provider
backend/.venv/Scripts/python.exe test/check_accounts.py       # Auth <-> RTDB konsisten
backend/.venv/Scripts/python.exe test/check_sync.py           # node/statistik/akun sinkron
```

Aturan yang dipakai:

- Skrip uji, audit, cek, dan diagnosa baru **wajib** dibuat di `test/`, bukan di `backend/`
  atau root. Pengecualian: `backend/scripts/audit_accounts.py` adalah **tool operator**
  yang dikirim bersama aplikasi dan dirujuk dokumentasi, bukan kode uji.
- Tiap skrip berdiri sendiri: mencetak `PASS`/`FAIL` per cek, ringkasan `HASIL: n/n lulus`
  (atau `gagal: tidak ada`), dan keluar dengan kode 1 bila ada yang gagal.
- Path diturunkan dari `Path(__file__).resolve().parent.parent`, bukan hardcode —
  repo boleh dipindah tanpa menyunting skrip.
- Tanpa kredensial untuk suite uji: klien RTDB di-stub, database memakai `NODE_DB` ke folder
  sementara sehingga `backend/data/sudutkota.db` dan `backend/media/hls` tidak tersentuh.

## Cache aset lokal

Semua referensi aset lokal di HTML memakai query versi, misalnya `css/style.css?v=20261113f` dan
`js/app.js?v=20261113f`. Tujuannya: server statis (nginx maupun `python -m http.server`) tidak
mengirim `Cache-Control` untuk aset, sehingga peramban bisa menyajikan versi lama setelah berkas
diubah. **Setiap kali `css/` atau `js/` diedit, naikkan angka versi itu di kesembilan halaman**
(cari `?v=`); cukup satu penggantian global.

Di Vercel tidak diperlukan karena `vercel.json` (root) sudah memasang `max-age=0, must-revalidate`
untuk `/js/`.

## Responsif

Semua halaman diuji pada 9 halaman × 17 ukuran viewport (320×568 sampai 3440×1440, termasuk
ponsel landscape 740×360, 844×390, layar pendek 1920×600 dan 1024×600, serta ultrawide 21:9):
tidak ada luapan horizontal dan tidak ada konten tertutup navbar.

Navbar memakai `position: fixed` dengan tinggi tetap yang ditetapkan di CSS — `--sk-nav-h: 64px`
dan `80px` pada ≥768 px — sehingga `main { padding-top: calc(var(--sk-nav-h) + 20px) !important }`
selalu tepat sejak render pertama. Dulu tinggi navbar diukur `app.js` saat runtime, tetapi nilai
itu tertinggal satu frame (64 px saat navbar sudah 80 px) dan membuat kartu pertama tertutup.

Titik penyesuaian utama:

- **Navbar** — logo mengecil di ponsel (`text-base`), tombol 36 px, dan pada <640 px tombol Keluar
  pindah ke menu ponsel supaya satu baris tetap muat; tautan desktop baru muncul di ≥1024 px dan
  baris tidak lagi melipat di 768–1023 px (`md:flex-nowrap` + pencarian `md:min-w-0`).
- **Kontainer** — `.sk-shell` (`max-width: 1400px`) naik ke 1600 px pada ≥1920 px dan 1760 px pada
  ≥2400 px, jadi konten tidak mengambang kecil di tengah monitor ultrawide.
- **Jarak antar-bagian** — section beranda `py-6 md:py-8` (24/32 px tiap sisi → 48/64 px antar
  bagian), `main` atas `84/100 px` mengikuti tinggi navbar, dan padding bawah halaman `pb-24`
  agar bar bawah tidak menutup baris terakhir. Sebelumnya `py-10 md:py-16` menghasilkan 128 px
  ruang kosong antar bagian.
- **CCTV Live** — dua kolom (pemutar + daftar node 340 px) baru aktif di ≥1280 px; di bawahnya
  panel ditumpuk dan daftar node memakai lebar penuh. Pada 1024–1279 px sebelumnya sidebar hanya
  ~230 px sehingga judul dan nama node terlipat.
- **Baris ikon layanan beranda** — grid 5 kolom (bukan baris yang bisa digeser), ikon 50–76 px
  mengikuti lebar, jadi kelima layanan utuh sejak 320 px dan tidak ada yang terpotong.
- **Statistik** — di <640 px filter periode menjadi satu baris yang bisa digeser (tidak lagi
  pecah 4+3 dengan lubang di kanan); pada ≥640 px kontainer selebar isinya (`w-fit`) dan tombol
  PDF/CSV berdampingan selebar konten. Tombol ekspor memakai kelas warna yang benar
  (`sk-btn-soft-danger`/`sk-btn-soft-success`).
- **Label field** — form login, registrasi, dan lupa sandi memakai `<label class="sk-label">`
  permanen di atas field, jadi konteks tidak hilang saat placeholder terisi.
- **Target sentuh** — `.tap-link`, `.period-tab`, `.sk-btn` minimal 40 px; tautan menu/footer
  40–44 px; field 16 px di ponsel (mencegah auto-zoom iOS).
- **Streaming** — `maxBufferLength` 8 dtk, `liveSyncDurationCount` 2, `liveMaxLatencyDurationCount` 4:
  jeda terhadap siaran langsung turun dari ~6 dtk menjadi ~4 dtk tanpa stall (uji 20 dtk: 18,4–20 dtk
  maju, 0 stall).
- **Dashboard** — di bawah 768 px tabel 5 kolom diganti kartu per node: nama, id/channel, status,
  zona/jalan, badge AI, dan tombol Edit/Hapus berlabel. Tabel tetap dipakai pada layar lebar.
- **Statistik** — kolom kontrol judul menumpuk dengan tepi kiri sejajar di bawah 1280 px.
- **Layar pendek** (<520 px tinggi, mis. ponsel landscape) — padding atas `main` dan `glass-card`
  dirapatkan agar konten tidak terdorong keluar layar.
- **Media** — `img, canvas, video, svg` dibatasi `max-width: 100%`.

Pengukuran ulang — tiga skrip di `test/` (lokal, tidak ikut deploy):

- `audit_responsive.py` — luapan horizontal, jarak antar-bagian >80 px, padding section ≥96 px,
  footer tertutup bar tetap. 9 halaman × 17 viewport (320×568 … 3440×1440).
- `audit_ux.py` — target sentuh <40 px, field tanpa label, ukuran field <16 px, teks <10 px,
  jumlah permintaan/berat halaman. 9 halaman × 2 viewport ponsel.
- `measure_hls_start.py` — waktu sampai frame pertama HLS (browser baru tiap run supaya cold).

## Kelola akun

Halaman `akun.html` (“Kelola Akun”) khusus pemilik fitur `akun` (`Auth.guard('akun')`); pengguna
tanpa fitur itu melihat panel penolakan, pengguna tanpa sesi diarahkan ke login.

Fitur:

- Ringkasan jumlah akun per peran, pencarian (nama/NIP/ID), filter peran.
- Tabel di ≥768 px dan kartu di bawahnya — keduanya dari satu fungsi render.
- **Kolom “Akses Fitur”**: lima sakelar per akun — CCTV, Statistik, Dashboard, Modul AI, Akun.
  Peran hanya mengisi nilai bawaan (`ROLE_FEATURES`); `akses` per akun adalah sumber kebenaran,
  jadi Administrator boleh memberi fitur di luar bawaan peran. Nilai yang tidak ada dianggap
  `true`, hanya boolean `false` yang mencabut.
- CRUD lewat modal: tambah, ubah, hapus. Peran yang tersedia hanya **Administrator, Teknisi, dan
  Visitor** — tidak ada peran lain, dan `auth.js` menolak nilai di luar ketiganya (jatuh ke Visitor).
- Aturan yang ditegakkan di backend, bukan hanya di UI: username dan NIP harus unik, kata sandi
  minimal 6 karakter, akun yang sedang dipakai tidak bisa dihapus, minimal satu Administrator
  harus tersisa, dan Administrator tidak bisa mencabut fitur `akun` dari akunnya sendiri
  (backend membalas 409 supaya tidak terkunci).
- Saat mengubah akun tanpa mengisi kata sandi, kata sandi lama dipertahankan.
- `PUT /api/akun/<uid>` menggabungkan kiriman parsial; `{"akses":{"cctv":false}}` hanya mematikan
  CCTV. Perubahan peran tanpa `akses` eksplisit mengembalikan ke bawaan peran baru.

API di `auth.js`: `list()`, `count()`, `create()`, `update()`, `remove()`, `can(feature)`,
`guard(feature)`, `features()`, `featureLabel()`, `roleFeatures()`, `resetAccounts()`. Semuanya
mengembalikan `{ ok, user?, error? }` untuk operasi tulis.

## Sumber stream: satu RTSP

Setiap node menyimpan satu URL: `rtsp` (kolom `rtsp` di SQLite). Halaman Stream
memutar `hls_url` yang diturunkan backend (`/hls/<id>/index.m3u8`). Tidak ada lagi
`url_m3u8`, `url_ai`, atau `url_non_ai`.

- Form tambah/ubah hanya punya satu input RTSP; HLS dibentuk otomatis.
- `rtsp://`/`rtsps://` diterima. `http(s)://` hanya bila `ALLOW_TEST_SOURCES=true`,
  untuk stream uji lokal seperti berkas HLS publik.
- `GET /api/nodes` tidak memuat `rtsp`; `GET /api/nodes/<id>` mengembalikannya untuk
  form edit dan membutuhkan ID token Firebase (`Authorization: Bearer`) plus fitur `dashboard`.
- Peramban tidak pernah membuka RTSP. URL HLS satu: `/hls/<id>/index.m3u8`; engine AI
  menulis ke folder node yang sama, jadi tidak ada dua URL yang harus dipilih

Alasannya: URL RTSP biasanya memuat `user:password`. Menyimpannya di Firebase RTDB
(yang dibaca klien) akan membocorkan kredensial kamera ke siapa pun yang membuka
devtools. SQLite di PC operator adalah satu-satunya tempat rahasia itu berada.

## Kendala yang masih terbuka

1. **Provider Email/Password harus diaktifkan** di Firebase Console → Authentication →
   Sign-in method. Tanpa itu login membalas `auth/operation-not-allowed`.
2. **Ingress publik.** Halaman Vercel berjalan di HTTPS; backend dijangkau lewat HTTPS
   juga. Jalur aktif: `tailscale funnel --bg 8080` → nginx:8080, dinyalakan dan dimatikan
   oleh `start-backend.bat`. Flask tetap di loopback dan tidak pernah dipublikasikan.
3. **Direktori node kosong.** Tidak ada seed; tambahkan kamera lewat Dashboard
   (`Tambah Data`). `POST /api/nodes/reset` justru mengosongkan direktori.
4. **Kredensial RTSP.** URL RTSP tersimpan plaintext di `backend/data/sudutkota.db` dan
   tidak pernah dikirim ke peramban. Kata sandi lama yang pernah tertulis di kode masih
   ada di riwayat git — ganti kata sandi perangkat bila repo pernah dibagikan. Enkripsi
   kolom adalah pengerasan opsional.
5. **Process list.** ffmpeg dan engine AI menerima URL RTSP sebagai argumen, jadi URL itu
   terlihat di daftar proses mesin. Jangan jalankan backend di mesin multi-user.
6. **Dependensi `requirements.txt`.** `Flask-Mail`, `google-generativeai`, `feedparser`,
   dan `pytz` tidak dipakai kode saat ini; `firebase-admin` sudah dipakai. Merapikannya
   belum termasuk pekerjaan ini.
7. **CSP belum dipasang.** Situs memuat `cdn.tailwindcss.com` (JIT, butuh `unsafe-eval`)
   dan banyak script inline; CSP yang benar menuntut build step lebih dulu.
8. **Kredensial awal.** Halaman login tidak lagi menampilkan akun demo. Kata sandi akun
   bootstrap harus diganti setelah serah terima, tidak boleh ditulis di repo, dan akun
   yatim dapat diperiksa dengan `python scripts/audit_accounts.py`.