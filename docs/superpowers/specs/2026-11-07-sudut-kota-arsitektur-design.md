# Desain: Konsolidasi Arsitektur Sudut Kota (backend lokal + Vercel + Tailscale)

Tanggal: 2026-11-07
Status: menunggu persetujuan
Pengganti: `docs/superpowers/specs/2026-11-05-sudut-kota-restructure-design.md` (tidak ada di tree; `docs/` di-ignore)

## 1. Maksud dan alasan

Repo sekarang berada di tengah restrukturisasi: file arsitektur lama sudah dihapus di
working tree tetapi belum di-commit, dan dua konfigurasi nginx yang saling bertentangan
hidup berdampingan. Tujuannya bukan menambah fitur, melainkan:

1. satu bentuk repo yang jelas — root hanya berisi `backend/`, `frontend/`, `.gitignore`, `README.md`;
2. satu jalur runtime — nginx sebagai satu-satunya pintu HTTP di sisi backend;
3. satu model otorisasi — Firebase Auth, bukan token bersama;
4. satu jalur deploy — hanya `frontend/` yang ke Vercel, hanya `backend/` yang jalan lokal.

Alasan keamanan eksplisit: URL RTSP memuat kredensial kamera, dan dashboard operator
mengubah konfigurasi perangkat lapangan. Keduanya tidak boleh bergantung pada pemeriksaan
di peramban.

## 2. Kondisi nyata hari ini (hasil pemeriksaan, bukan asumsi)

| Hal | Fakta |
|---|---|
| Root | `backend/`, `frontend/`, `logs/`, `tools/`, `README.md`, `.gitignore` |
| File lama | `app.py`, `templates/`, `static/`, `api/`, `aws_streamer/`, `requirements.txt`, `vercel.json` sudah terhapus di working tree, **belum di-commit** |
| `backend/nginx/nginx.conf` | Windows, port 8080, menyajikan `frontend/`, proxy `/api` + `/hls` ke Flask. **Ini yang berjalan.** |
| `backend/aws_streamer/nginx.conf` | Linux (`user www-data`, `/etc/nginx`, `/run/nginx.pid`), blok `rtmp`. **Tidak bisa jalan**: nginx 1.28.3 di `tools/` tidak di-compile dengan modul rtmp |
| `backend/aws_streamer/start_stream.sh` | Kredensial kamera plaintext (`Undip` / `Pekalongan12345`) + IP Tailscale `10.28.110.253` |
| `tools/nginx` | 7,4 MB, untracked, **tidak** di-ignore |
| `logs/` | Gitignored, dipakai nginx |
| Firebase Web SDK | Terisi di `backend/.env` (apiKey, authDomain, databaseURL, projectId, appId) |
| Firebase Admin SDK | **Kosong**: tidak ada `FIREBASE_PRIVATE_KEY` / `FIREBASE_CLIENT_EMAIL`; `firebase_init.py` juga membaca `DATABASE_URL`, sedangkan `.env` memakai `FIREBASE_DATABASE_URL` |
| `frontend/js/firebase-config.js` | Kosong; `FIREBASE_READY` false; belum ada kode yang memakai Firebase |
| Auth sekarang | `auth.js` demo localStorage (kata sandi plaintext, sesi bisa dipalsukan) + `X-SK-Token` bersama untuk tulis |
| HLS | Setiap `.ts` dilayani Flask (`send_file`), bukan nginx |
| `docs/` | Di-ignore `.gitignore:10` |

Konsekuensi yang sudah diukur: rantai "HLS → Vercel → HLS" tidak bisa dipakai. Vercel
tidak mem-proxy stream panjang; yang benar Vercel hanya menyajikan halaman, dan playlist +
segmen diambil peramban langsung dari backend lewat TLS.

## 3. Tujuan, non-tujuan, anti-tujuan

**Tujuan**
- Root bersih; satu config nginx; satu jalur deploy.
- Stream dapat ditonton semua peran (termasuk Visitor tanpa login) lewat HTTPS.
- Operasi tulis (CRUD node, start/stop stream, kelola akun) hanya untuk `admin` dan `teknisi`,
  ditegakkan **di backend** dengan Firebase ID token.
- Segmen HLS tidak lagi melewati Python.

**Non-tujuan (tidak dikerjakan di perubahan ini)**
- Mengganti telemetri/statistik simulasi dengan data RTDB.
- Menyambungkan `ai_engine/main_ai.py` ke endpoint backend.
- Menulis ulang UI atau tema.
- Membersihkan dependensi tak terpakai di `requirements.txt` (dicatat sebagai temuan terpisah).

**Anti-tujuan (kalau ini terjadi, perubahan dianggap gagal)**
- Menaruh nginx binary atau log di dalam `frontend/` sehingga ikut ter-deploy.
- Menyimpan service account atau private key di repo, di `frontend/`, atau di variabel `VITE_*`.
- Membiarkan pemeriksaan peran hanya di JavaScript.
- Menghapus `backend/media/` atau `backend/data/` sebagai bagian "bersih-bersih".

## 4. Batasan

- Backend berjalan di PC operator Windows; kamera dijangkau lewat Tailscale (`10.28.110.253`).
- Flask **hanya** bind `127.0.0.1:5000`.
- nginx bind `127.0.0.1:8080`.
- Ingress publik lewat Tailscale Funnel (`https://<host>.<tailnet>.ts.net` → `127.0.0.1:8080`).
  Funnel dipilih karena Visitor boleh menonton tanpa login, jadi ingress harus publik; dan
  karena Tailscale sudah dipakai sehingga tidak perlu domain/sertifikat sendiri.
- Vercel: Root Directory = `frontend`, tanpa build step.
- Bahasa kode/komentar/docstring: Indonesia, mengikuti isi repo.

## 5. Pendekatan yang dipertimbangkan

**P1 — Gateway tunggal + Firebase Auth + Tailscale Funnel** (dipilih)
nginx tetap ada dan menjadi satu-satunya edge; `/hls/` dilayani langsung dari disk; otorisasi
tulis diverifikasi Flask dengan ID token Firebase. Trade-off: butuh service account dan
project Firebase yang benar-benar aktif.

**P2 — Gateway tunggal + token peran (`ADMIN_TOKEN` / `TEKNISI_TOKEN`)** (ditolak)
Tidak menambah dependensi dan selesai lebih cepat, tetapi tetap shared secret: tidak ada
identitas per orang, tidak bisa dicabut per user, dan token di `localStorage` rentan XSS.
Tidak memenuhi syarat "hanya Administrator dan Teknisi" secara berarti.

**P3 — Tanpa nginx (Funnel → waitress)** (ditolak)
Paling sedikit komponen, tetapi setiap segmen `.ts` dilayani Python dan tidak ada tempat
untuk cache/limit/header. Juga bertentangan dengan keputusan mempertahankan nginx.

## 6. Bentuk akhir

```text
Capstone-Sudut-Kota/
├── .gitignore
├── README.md
├── backend/                         ← jalan lokal, tidak pernah di-deploy
│   ├── app.py                       Flask API
│   ├── auth.py                      BARU: verifikasi ID token + peran
│   ├── nodes.py                     SQLite (tanpa perubahan skema)
│   ├── firebase_init.py             Admin SDK (perbaiki nama variabel)
│   ├── streamer/hls.py              RTSP → HLS (tidak berubah)
│   ├── ai_engine/
│   ├── gateway/                     BARU: satu-satunya folder edge
│   │   ├── nginx.conf
│   │   ├── start-nginx.sh / .bat
│   │   ├── stop-nginx.sh / .bat
│   │   ├── tools/nginx/             distribusi nginx Windows (gitignored)
│   │   ├── logs/                    (gitignored)
│   │   └── temp/                    (gitignored)
│   ├── data/sudutkota.db            (gitignored)
│   ├── media/hls/<cam>/             (gitignored)
│   ├── scripts/sync_firebase_config.py
│   ├── scripts/seed_accounts.py     BARU: buat akun awal lewat Admin SDK
│   ├── tests/
│   ├── .env / .env.example
│   └── requirements.txt
└── frontend/                        ← satu-satunya yang ke Vercel
    ├── *.html
    ├── css/ js/ asset/
    └── vercel.json
```

Dihapus: `backend/nginx/`, `backend/aws_streamer/`, `tools/` (root), `logs/` (root),
`vercel.json` (root).

## 7. Alur runtime

```text
Kamera ──RTSP (Tailscale 10.28.110.253)──> ffmpeg (backend)
                                              │ tulis backend/media/hls/<cam>/
                                              ▼
Peramban (Vercel, HTTPS) ──HTTPS──> Tailscale Funnel ──> nginx 127.0.0.1:8080
                                                            ├── /            → frontend/ (deploy: Vercel)
                                                            ├── /api/        → Flask 127.0.0.1:5000
                                                            └── /hls/        → file di disk (bukan Flask)
```

- Dev harian tetap dua terminal seperti sekarang: `python -m http.server 8787` untuk
  `frontend/` dan `python app.py` untuk backend. `js/config.js` sudah menangani kasus ini.
- nginx + Funnel dipakai untuk jalur "live" yang dilihat dari Vercel.

## 8. Keputusan tulis (yang sudah diputuskan)

**D1 — Identitas operator = Firebase Auth email/password.**
Field login berubah dari "username atau NIP" menjadi email; `nama`, `nip`, `username` menjadi
profil di RTDB `/akun/{uid}`. Alasan: identifier native Firebase Auth adalah email, dan alur
reset kata sandi memakai `sendPasswordResetEmail` sehingga butuh mailbox nyata. Konsekuensi:
`login.html`, `register.html`, `forgot-password.html`, dan `akun.js` ikut berubah.

**D2 — Peran disimpan di RTDB `/akun/{uid}/peran`, bukan custom claim.**
Alasan: bisa diubah dari console tanpa perlu refresh token, satu sumber kebenaran, dan sudah
sesuai rencana README. Backend membaca dengan cache in-process 60 detik; nilai di luar
`admin|teknisi|visitor` diperlakukan `visitor`.

**D3 — Verifikasi di Flask, bukan di nginx.**
Request membawa `Authorization: Bearer <idToken>`. `auth.py` memverifikasi lewat Admin SDK
(`verify_id_token`), mengambil peran, lalu decorator memutuskan. nginx tidak melakukan
`auth_request` supaya tidak ada dua tempat yang tahu aturan peran.

**D4 — HLS publik.**
Semua peran (termasuk Visitor tanpa login) boleh menonton, jadi `/hls/` tidak memakai tanda
tangan URL. Header CORS `*` dipertahankan. Ini keputusan sadar: siapa pun yang tahu URL
stream dapat menontonnya.

**D5 — `/api/proxy` dihapus.**
Tidak lagi diperlukan begitu backend punya HTTPS sendiri, dan endpoint itu menggandakan
lalu lintas HLS sekaligus menambah permukaan SSRF.

**D6 — `X-SK-Token` dan `API_WRITE_TOKEN` dihapus.**
Diganti `Authorization: Bearer`. `ALLOWED_ORIGINS` tetap ada, isinya domain produksi Vercel +
localhost dev.

**D7 — Nama folder gateway = `backend/gateway/`.**
Bukan `aws_streamer`: tidak ada lagi AWS maupun RTMP di sistem ini, dan nama itu menyesatkan
orang berikutnya yang membaca repo.

**D8 — `Auth` menjadi asinkron, dengan gerbang `Auth.ready()`.**
`Auth.user()`/`isOperator()`/`isAdmin()` tetap sinkron tetapi hanya membaca snapshot cache
terakhir; setiap halaman melakukan `await Auth.ready()` sebelum render pertama. Alasan:
sesi Firebase baru diketahui lewat `onAuthStateChanged`, dan peran baru setelah baca RTDB;
memaksa semuanya sinkron berarti UI menampilkan status basi (admin terlempar ke login, atau
menu admin masih tampil setelah peran dicabut). Konsekuensi: blok init di 9 halaman HTML +
`app.js`, `dashboard.js`, `add-data.js`, `akun.js` diubah urutannya (bukan ditulis ulang).

**D9 — Admin SDK diinisialisasi lazy; backend tetap boot tanpa kunci.**
`auth.py` tidak memanggil `init_firebase()` saat import. Bila kunci belum lengkap: endpoint baca
tetap 200, endpoint tulis mengembalikan **503** dengan pesan yang menyebut variabel yang kurang
(bukan 401, supaya tidak terbaca sebagai "token salah"). Alasan: `python app.py` dan
`python -m unittest discover` harus tetap jalan sebelum pemilik menyerahkan service account,
dan tes menyuntikkan verifier palsu.

**D10 — Cutover otorisasi bersifat atomik, dengan urutan yang ditetapkan.**
Tidak ada jalur auth ganda. Urutan: (1) seed akun Firebase, (2) deploy frontend baru ke Vercel,
(3) restart backend. Jendela tulis mati beberapa menit saat (3) diterima; HTML/JS lama yang
masih di cache mengirim `X-SK-Token` dan akan menerima 401 sampai hard-refresh, jadi query
`?v=` di kesembilan halaman dinaikkan pada langkah (2).

**D11 — Alamat backend untuk halaman Vercel dihasilkan, tidak di-hardcode tangan.**
`js/config.js` sekarang hanya mendukung same-origin, `127.0.0.1:5000` (port 8787), dan
`localStorage['sudutkota.backend']` — yang tidak mungkin diisi Visitor anonim. Ditambahkan
`frontend/js/public-config.js` yang **dihasilkan** oleh `scripts/sync_public_config.py` dari
`backend/.env` (`PUBLIC_BACKEND_URL=https://<host>.<tailnet>.ts.net`), berisi
`window.SK_PUBLIC = { backendBase: "..." }`. Prioritas di `config.js`: localhost → perilaku
lama; selain itu → `SK_PUBLIC.backendBase`. Berkas ini di-commit (isinya publik) dan ikut
di-deploy, sama seperti `firebase-config.js`.

**D12 — Pendaftaran mandiri tetap dibuka, tetapi profil dibuat backend.**
`register.html` tetap ada (sesuai salinan UI yang sudah menyatakan akun baru berperan Visitor).
Setelah `createUserWithEmailAndPassword`, klien memanggil `POST /api/akun/self` dengan ID token;
backend menulis `/akun/{uid}` (`nama`, `nip`, `peran=visitor`). Klien **tidak** menulis RTDB
sama sekali, sehingga rules bisa menolak seluruh tulis dari klien. Ini menambah satu endpoint
ke matriks §9 dan menghapus kebutuhan aturan "pemilik boleh create".

## 9. Matriks otorisasi endpoint

| Endpoint | Anonim | Visitor | Teknisi | Admin |
|---|---|---|---|---|
| `GET /api/health`, `/api/config` | ✅ | ✅ | ✅ | ✅ |
| `GET /api/nodes` (tanpa RTSP) | ✅ | ✅ | ✅ | ✅ |
| `GET /hls/**` | ✅ | ✅ | ✅ | ✅ |
| `GET /api/nodes/<id>` (dengan RTSP) | ❌ | ❌ | ✅ | ✅ |
| `POST/PUT/DELETE /api/nodes` | ❌ | ❌ | ✅ | ✅ |
| `POST /api/nodes/reset` | ❌ | ❌ | ❌ | ✅ |
| `POST/DELETE /api/streams/<cam>` | ❌ | ❌ | ✅ | ✅ |
| `GET /api/status` | ❌ | ❌ | ✅ | ✅ |
| `POST /api/akun/self` (profil sendiri, peran dipaksa `visitor`) | ❌ | ✅ | ✅ | ✅ |
| `GET/POST/PUT/DELETE /api/akun` | ❌ | ❌ | ❌ | ✅ |

`GET /api/status` dipindah ke operator karena mengembalikan path database dan daftar model.
`GET /api/streams` tetap publik tetapi hanya memuat status, bukan URL sumber.

## 10. Perubahan per berkas

**Backend**
- `auth.py` (baru): `init()`, `verify_request()`, `role_of(uid)`, decorator `require_role(*roles)`,
  `current_user()` berbasis `flask.g`. Bisa di-inject verifier untuk tes.
- `app.py`: hapus `require_write_token`, `/api/proxy`, `API_WRITE_TOKEN`; pasang decorator per
  matriks §9; `CORS(allow_headers=["Authorization","Content-Type"])`; hapus route `/hls` kalau
  nginx yang menyajikan (sisakan untuk dev 8787 — lihat catatan di §13).
- `firebase_init.py`: satukan nama variabel (`DATABASE_URL` → `FIREBASE_DATABASE_URL` atau
  sebaliknya, dipilih salah satu dan dipakai konsisten di `.env.example`).
- `scripts/seed_accounts.py` (baru): buat akun awal + tulis `/akun/{uid}` dengan peran.
- `tests/test_nodes.py`: ganti `X-SK-Token` dengan token palsu yang di-inject; tambah tes 401/403
  per matriks.

**Frontend**
- `js/firebase-client.js` (baru): inisialisasi App + Auth dari `window.FIREBASE_CONFIG`.
- `js/auth.js`: implementasi ulang di balik antarmuka yang sama (`user()`, `isOperator()`,
  `isAdmin()`, `login`, `logout`, `roleLabel`). Tambah `Auth.ready()` (Promise, D8) dan
  `Auth.idToken(forceRefresh)`.
- `js/public-config.js` (baru, dihasilkan): `window.SK_PUBLIC.backendBase`, dipakai `config.js`
  saat halaman tidak dilayani dari localhost (D11).
- `js/store.js`: `Authorization: Bearer` menggantikan `X-SK-Token` + prompt token; hapus
  `askToken`/`TOKEN_KEY`.
- `login.html`, `register.html`, `forgot-password.html`: field email, alur reset Firebase,
  `await Auth.ready()` sebelum render.
- `akun.html`/`akun.js`: CRUD akun lewat `/api/akun` (Admin SDK), bukan localStorage.
- `vercel.json`: **tidak** menambah CSP. Situs memuat `cdn.tailwindcss.com` (kompiler JIT yang
  butuh `'unsafe-eval'`) dan puluhan `<script>`/`<style>` inline (butuh `'unsafe-inline'`), jadi
  CSP di sini hanya akan jadi hiasan. Tiga header yang sudah ada
  (`X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`) dipertahankan. CSP dicatat
  sebagai temuan lanjutan yang menuntut build step.

**Konfigurasi**
- `gateway/nginx.conf`: `listen 127.0.0.1:8080`; `root frontend`; `/api/` proxy ke 5000;
  `/hls/` `alias backend/media/hls/` dengan `types` + `Cache-Control` (`no-store` untuk `.m3u8`,
  `max-age=30` untuk `.ts`) + CORS; blokir `*.log`; `server_tokens off`; header keamanan;
  `limit_req` untuk `/api/`.
- `.gitignore`: tambah `tools/`, `backend/gateway/tools/`, `backend/gateway/logs/`,
  `backend/gateway/temp/`; ganti `docs/` dengan pengecualian agar `docs/superpowers/specs/` ter-track.
- `.env.example`: tambah blok Admin SDK (nama kunci saja, nilai kosong) dan
  `PUBLIC_BACKEND_URL` (dipakai `sync_public_config.py`).

## 11. Prasyarat yang harus disediakan pemilik sistem (bukan pekerjaan builder)

1. Service account Firebase (Project settings → Service accounts → Generate new private key)
   diisi ke `backend/.env`: `FIREBASE_TYPE`, `FIREBASE_PROJECT_ID`, `FIREBASE_PRIVATE_KEY_ID`,
   `FIREBASE_PRIVATE_KEY` (newline sebagai `\n`), `FIREBASE_CLIENT_EMAIL`, `FIREBASE_CLIENT_ID`,
   `FIREBASE_AUTH_URI`, `FIREBASE_TOKEN_URI`, `FIREBASE_AUTH_PROVIDER_X509_CERT_URL`,
   `FIREBASE_CLIENT_X509_CERT_URL`.
2. Email/Password provider aktif di Firebase Authentication.
3. RTDB rules: `/akun/{uid}` hanya boleh dibaca pemiliknya + admin; tulis `peran` hanya admin;
   path lain (jika ada) read-only.
4. Tailscale Funnel diaktifkan untuk host backend (`tailscale funnel --bg 8080`), dan hostname
   hasilnya dimasukkan ke `ALLOWED_ORIGINS` + `PUBLIC_BACKEND_URL`.
5. Password kamera dirotasi (kredensial lama ada di riwayat git).
6. `PUBLIC_BACKEND_URL` diisi hostname Funnel hasil langkah 4, lalu
   `python backend/scripts/sync_public_config.py` dijalankan dan hasilnya di-commit.

## 12. Verifikasi (bukti yang harus dikumpulkan)

1. `python -m unittest discover -s tests -v` hijau.
2. `gateway/tools/nginx/nginx.exe -p <root> -c backend/gateway/nginx.conf -t` → `syntax is ok`.
3. Anonim: `GET /api/health` 200, `GET /api/nodes` 200, `POST /api/nodes` 401, `GET /api/nodes/cam_29` 401.
4. Teknisi: `POST /api/nodes` 201; `POST /api/nodes/reset` 403.
5. Admin: `POST /api/nodes/reset` 200; `/api/akun` 200.
6. `ffprobe http://127.0.0.1:8080/hls/<cam>/index.m3u8` → H.264, dan
   `ffmpeg -i <playlist> -t 4 -f null -` selesai tanpa error (bukti nginx → disk → parser HLS).
7. `curl -I https://<funnel-host>/hls/<cam>/index.m3u8` → 200 + `content-type` benar (bukti TLS).
8. Halaman Vercel di HTTPS memutar stream tanpa error mixed content.
9. `git status` bersih dari `backend/.env`, `*.pt`, `media/`, `data/`, `tools/`.

## 13. Yang diserahkan ke builder

- Bentuk persis `auth.py` (dekorator vs `before_request`) dan cara meng-inject verifier di tes.
- Apakah route `/hls` di Flask dipertahankan untuk mode `http.server 8787` (backend tetap perlu
  menyajikan segmen saat dev tanpa nginx) atau dev diarahkan memakai nginx. **Rekomendasi:
  pertahankan route Flask**, hapus hanya kalau nginx terbukti dipakai di semua jalur.
- `alias` relatif vs absolut untuk `/hls/` di nginx Windows (uji dengan `nginx -t` lalu satu
  permintaan nyata; jangan mengandalkan asumsi).
- Struktur respons `/api/akun` dan validasi inputnya.
- Apakah `scripts/sync_firebase_config.py` diganti nama menjadi `sync_public_config.py` atau
  keduanya dipertahankan (isi `firebase-config.js` + `public-config.js` dalam satu skrip lebih
  sedikit berkas yang harus dijalankan).

## 14. Rollback

Working tree sekarang berisi 19 file termodifikasi dan tiga folder untracked (`backend/`,
`frontend/`, `tools/`). `git stash create` **tidak** menyelamatkan berkas untracked, jadi tidak
dipakai. Titik pulih dibuat sebagai commit baseline di branch terpisah:

```bash
git switch -c migration/baseline
git add -A           # setelah .gitignore dirapikan: tools/, .venv, media, data tidak ikut
git commit -m "chore: baseline sebelum restrukturisasi arsitektur"
git switch main
```

Restrukturisasi dikerjakan di branch `migration/arsitektur`. Rollback = `git switch main`
(baseline tetap utuh di `migration/baseline`), atau `git restore --source=migration/baseline -- .`
bila pekerjaan sudah tercampur. Tidak ada migrasi database; skema `nodes` tidak berubah.
