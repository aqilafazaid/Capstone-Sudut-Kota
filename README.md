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
├── frontend/                  ← satu-satunya yang dideploy ke Vercel
│   ├── *.html                 beranda, stream, statistik, dashboard, akun, auth
│   ├── css/style.css
│   ├── js/
│   │   ├── config.js          alamat API/HLS (same-origin atau public-config)
│   │   ├── public-config.js   DIHASILKAN: alamat backend untuk halaman Vercel
│   │   ├── firebase-config.js DIHASILKAN: konfigurasi Firebase Web SDK
│   │   ├── firebase-client.js inisialisasi Firebase App + Auth
│   │   ├── auth.js            sesi, peran, ID token (Firebase Auth)
│   │   ├── store.js           klien /api/nodes + cache baca
│   │   ├── app.js             navbar, tema, jam, toast
│   │   └── …                  main.js, dashboard.js, add-data.js, akun.js, statistik.js
│   ├── asset/
│   └── vercel.json
├── backend/                   ← jalan di PC operator, tidak pernah di-deploy
│   ├── app.py                 Flask API (127.0.0.1:5000)
│   ├── auth.py                verifikasi Firebase ID token + peran
│   ├── accounts.py            CRUD akun lewat Admin SDK + RTDB
│   ├── nodes.py               penyimpanan SQLite + validasi RTSP
│   ├── firebase_init.py       Admin SDK dari backend/.env
│   ├── streamer/hls.py        RTSP → HLS (ffmpeg)
│   ├── ai_engine/
│   ├── gateway/               SATU-SATUNYA konfigurasi edge
│   │   ├── nginx.conf         serve frontend/ + proxy /api + /hls dari disk
│   │   ├── start/stop-nginx.*
│   │   ├── tools/nginx/       distribusi nginx Windows (gitignored)
│   │   ├── logs/              (gitignored)
│   │   └── temp/              (gitignored)
│   ├── data/sudutkota.db      konfigurasi kamera (gitignored)
│   ├── media/hls/             keluaran ffmpeg (gitignored)
│   ├── scripts/               sync_public_config.py, seed_accounts.py, apply_rtdb_rules.py
│   ├── tests/
│   ├── .env / .env.example
│   └── requirements.txt
├── docs/superpowers/specs/    dokumen desain
└── README.md
```

Tidak ada `vercel.json` di root. Proyek Vercel memakai **Root Directory = `frontend`**,
jadi yang di-upload hanya isi folder itu — bukan `backend/.venv`, model AI, atau nginx.

## Menjalankan lokal

**Terminal 1 — backend (Flask):**

```bash
cd backend
.venv/Scripts/activate
python app.py
# API langsung: http://127.0.0.1:5000/api/health
```

**Terminal 2 — frontend statis:**

```bash
cd frontend
python -m http.server 8787
# buka http://127.0.0.1:8787
```

`js/config.js` mengarahkan halaman 8787 ke `http://127.0.0.1:5000`, dan Flask ikut
menyajikan `/hls`, jadi stream tetap bisa diputar tanpa nginx.

**nginx (opsional, meniru jalur produksi):**

```bash
bash backend/gateway/start-nginx.sh      # http://127.0.0.1:8080
bash backend/gateway/stop-nginx.sh
```

nginx menyajikan `frontend/` sekaligus `/api` dan `/hls` dari satu origin; pada jalur ini
segmen `.ts` dilayani langsung dari disk, tidak melewati Python.

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
| Statistik | simulasi `Store.stats()` | belum tersambung ke RTDB |
| Konfigurasi Firebase Web SDK | `backend/.env` → `frontend/js/firebase-config.js` | kunci publik; hasil `sync_public_config.py` |
| Alamat backend untuk Vercel | `backend/.env` (`PUBLIC_BACKEND_URL`) → `frontend/js/public-config.js` | hasil skrip yang sama |

Klien tidak pernah membaca atau menulis RTDB. Semua akses data lewat backend, sehingga
rules RTDB dapat menolak seluruh akses klien:

```bash
cd backend
python scripts/apply_rtdb_rules.py            # terapkan scripts/rtdb-rules.json
python scripts/apply_rtdb_rules.py --show     # lihat aturan aktif
```

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
CCTV → RTSP (Tailscale) → backend lokal (ffmpeg) → HLS di disk
                                   ↓
Peramban (Vercel, HTTPS) → Tailscale Funnel → nginx:8080 → /hls (file) + /api (Flask)
```

Vercel hanya menyajikan HTML/CSS/JS. Playlist dan segmen diambil peramban langsung dari
backend lewat Funnel, bukan lewat Vercel — Vercel tidak mem-proxy stream panjang.

| Method | Endpoint | Akses | Fungsi |
|---|---|---|---|
| GET | `/api/health`, `/api/config` | publik | status runtime & konfigurasi publik |
| GET | `/api/nodes` | publik | daftar node (tanpa RTSP) |
| GET | `/hls/<cam>/index.m3u8`, `/hls/<cam>/seg_*.ts` | publik | playlist & segmen |
| GET | `/api/streams` | publik | status proses ffmpeg |
| GET | `/api/nodes/<id>` | teknisi, admin | detail + RTSP untuk form edit |
| POST/PUT/DELETE | `/api/nodes[/<id>]` | teknisi, admin | CRUD node |
| POST/DELETE | `/api/streams/<cam>` | teknisi, admin | start/stop ffmpeg |
| GET | `/api/status` | teknisi, admin | path database, daftar model |
| POST | `/api/nodes/reset` | admin | reset node ke seed |
| GET/PUT/DELETE | `/api/akun[/<uid>]` | admin | kelola akun petugas |
| GET | `/api/akun/me` | login | profil sendiri |
| POST | `/api/akun/self` | login | buat profil saat pendaftaran (peran visitor) |

Otorisasi memakai header `Authorization: Bearer <idToken>` (Firebase). Peran diambil dari
RTDB dan di-cache 60 detik di backend; pemeriksaan peran **tidak** terjadi di peramban.
Halaman yang butuh peran tetap memanggil `Auth.requireOperator()`/`requireAdmin()`, tetapi
itu hanya untuk tampilan — endpoint tetap menolak sendiri.

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
| Administrator | `admin` | semua halaman, termasuk Kelola Akun dan reset node |
| Teknisi | `teknisi` | beranda, stream, statistik, dashboard node, kontrol AI |
| Visitor | `visitor` | beranda, stream, statistik; tanpa dashboard |

Pendaftaran mandiri (`register.html`) membuat akun Visitor: Firebase Auth membuat user,
lalu `POST /api/akun/self` menulis profilnya. Administrator menaikkan peran lewat
`akun.html`.

**Akun pertama harus dibuat dari terminal**, karena belum ada admin yang bisa membuka
halaman Kelola Akun:

```bash
cd backend
python scripts/seed_accounts.py --email admin@contoh.go.id --nama "Admin Dishub" --peran admin
```

Kata sandi diminta lewat prompt, tidak masuk riwayat shell.

## Deploy ke Vercel

1. Import repo ini.
2. **Root Directory: `frontend`** — bukan root repo. Tanpa ini Vercel mencari entrypoint
   di root dan ikut meng-upload `backend/`.
3. Framework preset: *Other*. Tidak ada build command, output directory = `.`.
4. Isi `PUBLIC_BACKEND_URL` di `backend/.env` dengan hostname Tailscale Funnel, lalu
   jalankan `python backend/scripts/sync_public_config.py` dan commit hasilnya.
5. Tambahkan domain Vercel ke `ALLOWED_ORIGINS` di `backend/.env`, lalu restart Flask.
6. `cleanUrls` aktif, jadi `/cctv` dan `/cctv.html` sama-sama bekerja.

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

1. **Provider Email/Password harus diaktifkan** di Firebase Console → Authentication →
   Sign-in method. Tanpa itu login membalas `auth/operation-not-allowed`.
2. **Ingress publik.** Halaman Vercel berjalan di HTTPS; backend harus dijangkau lewat
   HTTPS juga. Rencana: Tailscale Funnel (`tailscale funnel --bg 8080`) → nginx:8080.
3. **Stream Pekalongan belum menyala.** Node `cam_29`, `cam_35`, `cam_43` masih
   `aktif: false`; ffmpeg baru dijalankan setelah node diaktifkan dan RTSP-nya terjangkau.
4. **Kredensial RTSP.** URL RTSP tersimpan plaintext di `backend/data/sudutkota.db` dan
   tidak pernah dikirim ke peramban. Kata sandi lama yang pernah tertulis di kode masih
   ada di riwayat git — ganti kata sandi perangkat bila repo pernah dibagikan. Enkripsi
   kolom adalah pengerasan opsional.
5. **Process list.** ffmpeg menerima URL RTSP sebagai argumen, jadi URL itu terlihat di
   daftar proses mesin. Jangan jalankan backend di mesin multi-user.
6. **Dependensi `requirements.txt`.** `Flask-Mail`, `google-generativeai`, `feedparser`,
   dan `pytz` tidak dipakai kode saat ini; `firebase-admin` sudah dipakai. Merapikannya
   belum termasuk pekerjaan ini.
7. **CSP belum dipasang.** Situs memuat `cdn.tailwindcss.com` (JIT, butuh `unsafe-eval`)
   dan banyak script inline; CSP yang benar menuntut build step lebih dulu.
