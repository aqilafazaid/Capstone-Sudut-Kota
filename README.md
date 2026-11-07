# Sudut Kota — Command Center CCTV & Analitik Lalu Lintas

Frontend statis untuk Sistem Informasi Eksekutif pengawasan CCTV Dishub Kota Pekalongan.
Halaman berjalan tanpa build step dan tanpa server Python: cukup HTML, CSS, dan JavaScript.

## Status

| Bagian | Status |
|--------|--------|
| Frontend statis (`frontend/`) | **Selesai** — 8 halaman, pemutar HLS, panel kontrol AI, CRUD node, statistik + ekspor |
| Firebase Auth + Realtime Database | **Ditunda** — digantikan lapisan demo di `js/store.js` dan `js/auth.js` |
| Backend AI lokal (`ai_engine/`) | Belum dipindah/diubah pada tahap ini |
| Deployment Vercel | Siap, Root Directory diarahkan ke `frontend/` |

## Navigasi

Menu: **Dashboard · Stream · Statistik · Akun**, seluruhnya disuntikkan `js/app.js` sehingga bar-nya
identik di semua halaman. **Beranda tidak lagi jadi item menu** — logo bundar + tulisan SUDUT KOTA di
kiri navbar yang menjadi tautan ke `index.html` (dan diberi cincin biru saat halaman aktif).

- **Dashboard hanya muncul untuk Administrator dan Teknisi**, **Akun hanya untuk Administrator**.
  Visitor melihat tiga menu; tautan muncul/hilang seketika saat login atau logout tanpa memuat
  ulang halaman.
- **Teks berjalan** di bar bawah (tampil ≥1024 px) memakai marquee dua salinan identik yang
  digeser tepat satu salinan, jadi sambungannya tidak terlihat dan tidak ada jeda kosong.
  Kecepatannya tetap ~55 px/detik berapa pun panjang teksnya dan berhenti saat kursor berada di atas
  bar. Bila sistem pengguna mengaktifkan `prefers-reduced-motion`, teks **tetap berjalan** dengan
  kecepatan diturunkan (40 px/detik).
- **Kolom pencarian ada di dalam navbar** dan hanya dirender di halaman Stream, bukan di badan
  halaman. Pada layar < 768 px kolom itu turun menjadi baris kedua di dalam kartu navbar yang sama,
  lalu tautan menu dilipat ke hamburger.

## Tema

**Bawaan gelap.** Tombol tema di navbar menyimpan pilihan di `localStorage` (`color-theme`) dan
berlaku di semua halaman, termasuk Stream, Dashboard, dan Statistik — halaman console memakai
variabel CSS `--sk-*` sehingga tidak ada lagi panel gelap yang tertinggal saat mode terang.

## Struktur

```text
Capstone-Sudut-Kota/
├── frontend/              ← yang dideploy ke Vercel
│   ├── index.html         Beranda
│   ├── cctv.html          Pemutar + panel kontrol AI (menu "Stream")
│   ├── statistik.html     Statistik + ekspor PDF/CSV
│   ├── dashboard.html     Manajemen node (khusus operator)
│   ├── add-data.html      Form tambah/ubah node (satu URL RTSP)
│   ├── akun.html          Manajemen akun petugas (khusus Administrator)
│   ├── login.html / register.html / forgot-password.html
│   ├── asset/             logo, favicon, lambang kop PDF
│   ├── css/style.css
│   ├── js/
│   │   ├── config.js          alamat API/HLS (same-origin lewat nginx)
│   │   ├── store.js           klien /api/nodes + cache baca
│   │   ├── auth.js            autentikasi demo (localStorage)
│   │   ├── app.js             navbar, tema, jam, toast
│   │   ├── main.js            pemutar HLS + kontrol AI
│   │   ├── dashboard.js       tabel & filter node
│   │   ├── statistik.js       agregasi + ekspor PDF/CSV
│   │   ├── add-data.js        form node (hanya RTSP)
│   │   ├── akun.js            CRUD akun petugas
│   │   └── firebase-config.js dihasilkan dari backend/.env
│   └── vercel.json
├── backend/                    ← jalan di PC lokal, tidak dideploy
│   ├── app.py                  Flask API: node CRUD, HLS, status (port 5000)
│   ├── nodes.py                penyimpanan SQLite + validasi RTSP
│   ├── firebase_init.py        Admin SDK opsional untuk engine AI
│   ├── .env / .env.example     Firebase Web SDK + setelan backend
│   ├── requirements.txt
│   ├── scripts/
│   │   └── sync_firebase_config.py  .env → frontend/js/firebase-config.js
│   ├── nginx/
│   │   ├── nginx.conf          serve frontend/ + proxy /api,/hls
│   │   └── start/stop-nginx.*
│   ├── data/sudutkota.db       konfigurasi kamera (gitignored)
│   ├── media/hls/              keluaran ffmpeg (gitignored)
│   ├── streamer/hls.py         RTSP → HLS
│   ├── ai_engine/              loop AI + enhancer low-light
│   └── aws_streamer/           arsip konfigurasi AWS
├── tools/nginx/                distribusi nginx Windows
├── docs/superpowers/specs/
└── README.md
```

## Menjalankan lokal

Dua proses: backend Flask dan nginx. nginx menyajikan `frontend/` sekaligus
mem-proxy `/api` dan `/hls` ke Flask, jadi peramban hanya mengenal satu origin
(tidak ada CORS dan tidak ada mixed content di lokal).

**Terminal 1 — backend (Flask):**

```bash
cd backend
.venv/Scripts/activate        # Windows: venv yang sudah dibuat di backend/.venv
python app.py
# API langsung: http://127.0.0.1:5000/api/health
```

**Terminal 2 — nginx** (dari root repo):

```bash
bash backend/nginx/start-nginx.sh      # Git Bash
# atau klik dua kali backend\nginx\start-nginx.bat
# buka http://127.0.0.1:8080
```

Hentikan dengan `bash backend/nginx/stop-nginx.sh` (atau `stop-nginx.bat`).

Bila `backend/.venv` belum ada:

```bash
cd backend
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt
```

Cek cepat: `curl http://127.0.0.1:8080/api/health` → `{"status":"ok",...}`.

**Token operator.** CRUD node memakai header `X-SK-Token`. Nilainya ada di
`backend/.env` (`API_WRITE_TOKEN`); dashboard memintanya sekali saat penyimpanan
pertama lalu menyimpannya di `localStorage`. Buat token baru bila perlu:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

### Penyimpanan data

| Data | Lokasi | Catatan |
|---|---|---|
| Konfigurasi kamera (RTSP) | `backend/data/sudutkota.db` (SQLite) | sumber kebenaran; RTSP tidak pernah dikirim ke peramban |
| Akun | `localStorage` (demo) → `/akun/{uid}` di Firebase nanti | masih demo, bukan otorisasi produksi |
| Statistik | simulasi `Store.stats()` → `/statistik/...` di Firebase nanti | belum tersambung |
| Konfigurasi Firebase Web SDK | `backend/.env` → `frontend/js/firebase-config.js` | kunci publik; jalankan `sync_firebase_config.py` |

`frontend/js/firebase-config.js` **dihasilkan** dari `backend/.env`:

```bash
backend/.venv/Scripts/python.exe backend/scripts/sync_firebase_config.py
```

`FIREBASE_READY` false selama `apiKey` kosong, sehingga halaman tetap memakai lapisan
demo. Blok service account Admin SDK sudah tidak ada di `.env`; engine AI akan mencetak
`Firebase tidak aktif` dan tetap berjalan tanpa telemetri RTDB.

### Engine AI — satu folder per cara inferensi

`ai_engine/main_ai.py` mengalirkan tiap frame lewat **satu** enhancer low-light dan
**satu** model YOLO. Model low-light tidak disamakan karena arsitekturnya berbeda:

| Model | Keluaran jaringan | Perlakuan khas |
|---|---|---|
| MirNet | gambar (B, 3, H, W) | padding ke kelipatan 8, dipotong lagi setelah inferensi |
| Zero-DCE | 24 peta kurva (B, 24, H, W) | gambar akhir = iterasi `x + A(x²−x)` 8 kali pada gambar masukan |
| classical | – | CLAHE + gamma, dipakai otomatis bila bobot model belum ada |
| none | – | frame diteruskan apa adanya |

Model dipilih dari RTDB (`ai_status.lowlight_model`) dan boleh berganti saat engine
berjalan. YOLO hanya satu: file `.pt` pertama di `model_ai/Yolo/`.

```bash
cd backend
python -m ai_engine.main_ai --channel 29                              # RTSP -> HLS
python -m ai_engine.main_ai --channel 29 --no-stream --lowlight zerodce
```

## Alur stream

```text
CCTV → RTSP → backend lokal (ffmpeg) → HLS (m3u8) → Vercel → HLS → client
```

Satu jalur untuk mode AI maupun non-AI: FFmpeg menulis `index.m3u8` + segmen ke
`backend/media/hls/<cam>/`, Flask menyajikannya di `/hls/<cam>/...`, peramban memutar
m3u8 itu. RTMP/AWS sudah tidak dipakai (folder `aws_streamer/` dibiarkan sebagai arsip).

| Method | Endpoint | Fungsi |
|---|---|---|
| GET | `/api/nodes` | daftar node (tanpa RTSP) |
| GET | `/api/nodes/<id>` | detail + RTSP untuk form edit (butuh `X-SK-Token`) |
| POST | `/api/nodes` | tambah node (butuh token) |
| PUT | `/api/nodes/<id>` | ubah node (butuh token) |
| DELETE | `/api/nodes/<id>` | hapus node + hentikan stream (butuh token) |
| GET | `/api/streams` | daftar proses ffmpeg + status |
| POST | `/api/streams/<cam>` | mulai manual: `{"rtsp": "…"}` (butuh token) |
| DELETE | `/api/streams/<cam>` | hentikan (butuh token) |
| GET | `/hls/<cam>/index.m3u8` | playlist HLS (tanpa cache) |
| GET | `/hls/<cam>/seg_XXXXX.ts` | segmen HLS |

`copy: true` meneruskan video apa adanya (hemat CPU); `copy: false` men-transcode H.264
(wajib bila sumber bukan H.264). Engine AI selalu memakai jalur transcode karena frame
sudah dimodifikasi.

**Alamat server dari sisi frontend.** Lewat nginx (`http://localhost:8080`),
`js/config.js` memakai `backendBase = ''`, jadi `/api` dan `/hls` same-origin. Hanya
`python -m http.server 8787` yang memakai `http://127.0.0.1:5000` sebagai default.

Di Vercel, halaman HTTPS harus memanggil nginx HTTPS (domain + sertifikat, atau
Cloudflare Tunnel). Isi:

```js
localStorage.setItem('sudutkota.backend', 'https://<endpoint-nginx>')
```

`ALLOWED_ORIGINS` di `backend/.env` harus memuat domain Vercel; tanpa itu panggilan API
dari Vercel ditolak CORS. HLS mengirim `Access-Control-Allow-Origin: *`, tetapi endpoint
HTTPS tetap wajib agar tidak diblokir mixed content.

Halaman tidak butuh server khusus. Membuka `frontend/index.html` langsung lewat `file://`
sebagian besar berfungsi, tetapi `localStorage`, API, dan pemutaran HLS lebih andal lewat nginx.

### Akun demo

| ID | Sandi | Peran |
|----|-------|-------|
| `admin` | `admin123` | Administrator — akses penuh |
| `teknisi` | `teknisi123` | Teknisi — akses dashboard + kontrol AI |
| akun hasil registrasi | — | Peran awal **Visitor**, belum bisa membuka dashboard |

Peran yang dikenal sistem hanya tiga:

| Peran | Kode | Akses |
|-------|------|-------|
| Administrator | `admin` | Semua halaman, termasuk Kelola Akun |
| Teknisi | `teknisi` | Beranda, Stream, Statistik, Dashboard node, kontrol AI |
| Visitor | `visitor` | Beranda, Stream, Statistik, termasuk panel Kontrol Modul AI; tanpa dashboard |

Visitor (tanpa login) boleh membuka beranda dan halaman CCTV, menonton stream, dan melihat
angka telemetri; tombol kontrol AI tampil nonaktif.

> **Penting:** `js/auth.js` versi sekarang menyimpan sesi di `localStorage` dan kata sandi
> tanpa hash. Itu hanya untuk demo frontend, **bukan** otorisasi produksi — penjaga halaman
> bisa dilewati dari konsol peramban. Ganti dengan Firebase Auth sebelum dipakai sungguhan.

## Deploy ke Vercel

1. Import repo ini.
2. **Root Directory: `frontend`** (bukan root repo). Tanpa ini Vercel mencari entrypoint di root.
3. Framework preset: *Other*. Tidak ada build command, output directory = `.`.
4. `cleanUrls` aktif, jadi `/cctv` dan `/cctv.html` sama-sama bekerja.

## Data awal

Backend menyemai 3 node Pekalongan (`cam_29`, `cam_35`, `cam_43`) saat
`backend/data/sudutkota.db` masih kosong. Keempat stream uji publik hanya ikut bila
`ALLOW_TEST_SOURCES=true`; default-nya `false`.

- `localStorage['sudutkota.nodes.cache.v2']` — cache baca, bukan sumber kebenaran.
- `localStorage['sudutkota.ai.v1']` — status AI (masih demo).
- `localStorage['sudutkota.writeToken']` — token operator.
- `localStorage['sudutkota.session.v1']` — sesi login demo.

Tombol **Reset data demo** memanggil `POST /api/nodes/reset` (butuh token),
mengembalikan node ke seed backend, lalu akun ke akun demo.

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

// auth.js — masih demo; titik integrasi Firebase Auth nanti
Auth.login(identifier, password) Auth.register({...})   Auth.logout()
Auth.user()                      Auth.isOperator()      Auth.requireOperator()
```

Akun dan statistik belum dipindah. Saat Firebase Auth/RTDB diaktifkan, ganti isi
`auth.js` dan sumber `Store.stats()`; node tetap di backend.

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

Pustaka ekspor dimuat dari CDN hanya di halaman ini. Angkanya berasal dari model simulasi
deterministik (per node, per hari, per jam), jadi tidak berubah saat halaman dimuat ulang. Saat
telemetri Firebase tersambung, cukup ganti isi `Store.stats()`; halaman dan ekspor tidak berubah.

## Cache aset lokal

Semua referensi aset lokal di HTML memakai query versi, misalnya `css/style.css?v=20261106h` dan
`js/app.js?v=20261106h`. Tujuannya: server statis (nginx maupun `python -m http.server`) tidak
mengirim `Cache-Control` untuk aset, sehingga peramban bisa menyajikan versi lama setelah berkas
diubah. **Setiap kali `css/` atau `js/` diedit, naikkan angka versi itu di kesembilan halaman**
(cari `?v=`); cukup satu penggantian global.

Di Vercel tidak diperlukan karena `vercel.json` sudah memasang `max-age=0, must-revalidate` untuk
`/js/`.

## Responsif

Semua halaman diuji pada 8 halaman × 15 ukuran viewport (320×568 sampai 2560×1080, termasuk
ponsel landscape 740×360 dan 844×390): tidak ada luapan horizontal dan tidak ada konten tertutup
navbar.

Navbar memakai `position: fixed` dan barisnya bisa melipat pada rasio tertentu (mis. 320–360 px,
atau 640–767 px saat kolom pencarian turun ke baris kedua). Karena itu padding atas `<main>` tidak
lagi ditulis tetap di HTML: `app.js` mengukur tepi bawah navbar dan menaruhnya di variabel CSS
`--sk-nav-h`, lalu `main { padding-top: calc(var(--sk-nav-h) + 20px) }`. Pengukuran diulang saat
`resize`, `orientationchange`, font selesai dimuat, dan saat chip pengguna berubah setelah
login/logout. Efeknya: tidak ada lagi kartu yang tertutup navbar pada rasio mana pun.

Titik penyesuaian utama:

- **Navbar** — logo mengecil di ponsel (`text-base`), tombol 36 px, dan pada <640 px tombol Keluar
  pindah ke menu ponsel supaya satu baris tetap muat; tautan desktop baru muncul di ≥1024 px dan
  baris tidak lagi melipat di 768–1023 px (`md:flex-nowrap` + pencarian `md:min-w-0`).
- **Kontainer** — `max-w-7xl` dinaikkan bertahap pada layar lebar (1408 px ≥1536, 1600 px ≥1920,
  1760 px ≥2400) supaya konten tidak mengambang kecil di tengah monitor ultrawide.
- **Dashboard** — di bawah 768 px tabel 5 kolom diganti kartu per node: nama, id/channel, status,
  zona/jalan, badge AI, dan tombol Edit/Hapus berlabel. Tabel tetap dipakai pada layar lebar.
- **Statistik** — tombol interval menjadi grid 4 kolom di ponsel; kolom kontrol judul menumpuk
  dengan tepi kiri sejajar.
- **Layar pendek** (<520 px tinggi, mis. ponsel landscape) — padding atas `main` dan `glass-card`
  dirapatkan agar konten tidak terdorong keluar layar.
- **Media** — `img, canvas, video, svg` dibatasi `max-width: 100%`.

## Kelola akun

Halaman `akun.html` (“Kelola Akun”) khusus Administrator (`Auth.requireAdmin()`); Teknisi dialihkan ke login dengan
alasan `forbidden`, pengguna tanpa sesi dengan alasan `login`.

Fitur:

- Ringkasan jumlah akun per peran, pencarian (nama/NIP/ID), filter peran.
- Tabel 4 kolom di ≥768 px dan kartu di bawahnya — keduanya dari satu fungsi render.
- CRUD lewat modal: tambah, ubah, hapus. Peran yang tersedia hanya **Administrator, Teknisi, dan
  Visitor** — tidak ada peran lain, dan `auth.js` menolak nilai di luar ketiganya (jatuh ke Visitor).
- Aturan yang ditegakkan di `auth.js`, bukan hanya di UI: username dan NIP harus unik, kata sandi
  minimal 6 karakter, akun yang sedang dipakai tidak bisa dihapus, dan minimal satu Administrator
  harus tersisa.
- Saat mengubah akun tanpa mengisi kata sandi, kata sandi lama dipertahankan.

API yang ditambahkan ke `auth.js`: `list()`, `count()`, `create()`, `update()`, `remove()`,
`requireAdmin()`, `resetAccounts()`. Semuanya mengembalikan `{ ok, user? , error? }`. Ketika Firebase
Auth dipasang, cukup ganti implementasi tujuh fungsi itu; `akun.js` tidak perlu diubah.

## Sumber stream: satu RTSP

Setiap node menyimpan satu URL: `rtsp` (kolom `rtsp` di SQLite). Halaman Stream
memutar `hls_url` yang diturunkan backend (`/hls/<id>/index.m3u8`). Tidak ada lagi
`url_m3u8`, `url_ai`, atau `url_non_ai`.

- Form tambah/ubah hanya punya satu input RTSP; HLS dibentuk otomatis.
- `rtsp://`/`rtsps://` diterima. `http(s)://` hanya bila `ALLOW_TEST_SOURCES=true`,
  untuk stream uji lokal seperti berkas HLS publik.
- `GET /api/nodes` tidak memuat `rtsp`; `GET /api/nodes/<id>` mengembalikannya untuk
  form edit dan membutuhkan `X-SK-Token`.
- Peramban tidak pernah membuka RTSP. Label AI hanya menandai apakah modul AI aktif;
  URL HLS-nya sama.

Alasannya: URL RTSP biasanya memuat `user:password`. Menyimpannya di Firebase RTDB
(yang dibaca klien) akan membocorkan kredensial kamera ke siapa pun yang membuka
devtools. SQLite di PC operator adalah satu-satunya tempat rahasia itu berada.

## Kendala yang masih terbuka

1. **Mixed content.** Halaman Vercel berjalan di HTTPS; endpoint nginx harus HTTPS
   (domain + sertifikat, atau Cloudflare Tunnel). Tanpa itu `/api` dan `/hls` diblokir.
2. **Stream Pekalongan belum menyala.** Node `cam_29`, `cam_35`, `cam_43` masih
   `aktif: false`; ffmpeg baru dijalankan setelah node diaktifkan dan RTSP-nya dapat
   dijangkau dari PC operator.
3. **Rules RTDB.** Konfigurasi kamera tidak lagi di RTDB. Rules baru relevan saat akun
   dan statistik dipindah ke Firebase; sampai itu, auth frontend masih demo.
4. **Kredensial RTSP.** URL RTSP sekarang tersimpan di `backend/data/sudutkota.db`
   (plaintext) dan tidak pernah dikirim ke peramban. Kata sandi lama yang pernah
   tertulis di kode masih ada di riwayat git — ganti kata sandi perangkat bila repo
   pernah dibagikan. Enkripsi kolom adalah pengerasan opsional.
5. **Token operator bersama.** `X-SK-Token` melindungi tulis dari anonim, tetapi bukan
   autentikasi per pengguna. Saat Firebase Auth aktif, ganti dengan verifikasi ID token.
6. **Process list.** ffmpeg menerima URL RTSP sebagai argumen, jadi URL itu terlihat di
   daftar proses mesin. Jangan jalankan backend di mesin multi-user.
