@echo off
rem ============================================================
rem  Sudut Kota - backend: nginx (pintu masuk) + Flask (API)
rem
rem  Pakai: start-backend.bat
rem  Buka : http://127.0.0.1:8080   (nginx: frontend + /api + /hls)
rem  Stop : Ctrl+C
rem
rem  Cara 1 - Vercel saja: cukup terminal ini. Tailscale Funnel
rem  menunjuk ke nginx:8080; Flask tetap di loopback:5000 dan tidak
rem  pernah diekspos langsung ke internet.
rem
rem  Cara 2 - lokal + Vercel: terminal ini + start-frontend.bat.
rem  Halaman 8787 memanggil Flask lewat loopback; Vercel tetap
rem  memakai Funnel yang sama ke nginx.
rem
rem  Variabel:
rem    SK_NO_FUNNEL=1   lewati Tailscale Funnel (uji lokal saja)
rem ============================================================
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0backend" || exit /b 1

set "ROOT=%~dp0"
if "%ROOT:~-1%"=="\" set "ROOT=%ROOT:~0,-1%"
set "VENV_PY=%CD%\.venv\Scripts\python.exe"
set "NGINX_EXE=%ROOT%\backend\gateway\tools\nginx\nginx.exe"
set "GATEWAY=8080"

rem Flask selalu loopback di port tetap: nginx.conf mem-proxy ke 5000.
rem Nilai lain di .env diabaikan supaya tidak ada dua port berbeda.
set "API_HOST=127.0.0.1"
set "API_PORT=5000"
set "PORT=5000"

if not exist "%VENV_PY%" (
    echo [backend] GAGAL: virtual environment belum ada: %CD%\.venv
    echo           Buat dulu:
    echo               cd /d "%~dp0backend"
    echo               python -m venv .venv
    echo               .venv\Scripts\python.exe -m pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)

if not exist "%NGINX_EXE%" (
    echo [backend] GAGAL: nginx tidak ditemukan: %NGINX_EXE%
    echo           Unduh distribusi nginx untuk Windows lalu ekstrak isinya
    echo           ke folder backend\gateway\tools\nginx\.
    echo           Tanpa nginx backend tidak dijalankan: Flask tidak boleh
    echo           menjadi pintu masuk publik.
    echo.
    pause
    exit /b 1
)

set "FLASK_ADOPTED=0"
netstat -ano | findstr /R /C:":%PORT% .*LISTENING" >nul
if not errorlevel 1 (
    rem Port terpakai: boleh dilanjutkan HANYA bila itu backend Sudut Kota yang sehat.
    "%VENV_PY%" -c "import json,urllib.request;print(json.load(urllib.request.urlopen('http://127.0.0.1:%PORT%/api/health',timeout=3)).get('service',''))" 2>nul | findstr /C:"sudut-kota-backend" >nul
    if not errorlevel 1 (
        set "FLASK_ADOPTED=1"
        echo [backend] Flask sudah berjalan dan sehat; instance kedua tidak dijalankan.
    ) else (
        echo [backend] GAGAL: port %PORT% dipakai proses lain ^(bukan Sudut Kota^). Cek dengan:
        echo               netstat -ano ^| findstr :%PORT%
        echo           Hentikan proses itu dulu - Flask hanya boleh satu instance.
        echo.
        pause
        exit /b 1
    )
)

set "NGINX_STARTED=0"
set "NGINX_ADOPTED=0"
set "NGINX_PID="
if exist "%ROOT%\backend\gateway\logs\nginx.pid" set /p NGINX_PID=<"%ROOT%\backend\gateway\logs\nginx.pid"

netstat -ano | findstr /R /C:":%GATEWAY% .*LISTENING" >nul
if errorlevel 1 (
    echo [backend] menyalakan nginx di 127.0.0.1:%GATEWAY% ...
    call "%ROOT%\backend\gateway\start-nginx.bat"
    if errorlevel 1 (
        echo [backend] GAGAL: nginx tidak mau start. Log: backend\gateway\logs\error.log
        echo.
        pause
        exit /b 1
    )
    set "NGINX_STARTED=1"
) else (
    rem Port 8080 hanya boleh dipakai nginx milik repo ini. PID di nginx.pid
    rem adalah master, sedangkan socket dipegang worker - jadi cocokkan nama
    rem prosesnya, bukan PID yang listen.
    set "PID_OK="
    if not "!NGINX_PID!"=="" (
        tasklist /FI "PID eq !NGINX_PID!" | findstr /C:"nginx.exe" >nul
        if not errorlevel 1 set "PID_OK=1"
    )
    if not defined PID_OK (
        echo [backend] GAGAL: port %GATEWAY% dipakai proses lain, bukan nginx Sudut Kota.
        echo               Cek: netstat -ano ^| findstr :%GATEWAY%
        echo           Bila itu nginx sisa sesi lama: backend\gateway\stop-nginx.bat
        echo.
        pause
        exit /b 1
    )
    set "NGINX_ADOPTED=1"
    echo [backend] nginx sudah jalan ^(pid !NGINX_PID!^), dipakai ulang.
)

rem nginx harus loopback saja; 0.0.0.0 atau [::] berarti ikut terekspos ke LAN.
netstat -ano | findstr ":%GATEWAY%" | findstr /C:"0.0.0.0:%GATEWAY%" >nul
if not errorlevel 1 set "GATEWAY_EXPOSED=1"
netstat -ano | findstr ":%GATEWAY%" | findstr /C:"[::]:%GATEWAY%" >nul
if not errorlevel 1 set "GATEWAY_EXPOSED=1"
if defined GATEWAY_EXPOSED (
    echo [backend] GAGAL: nginx listen di semua antarmuka, bukan 127.0.0.1. Dihentikan.
    call "%ROOT%\backend\gateway\stop-nginx.bat" >nul 2>&1
    echo.
    pause
    exit /b 1
)

set "FUNNEL_STARTED=0"

rem Flask sudah jalan sebelumnya: cukup pastikan Funnel menunjuk ke nginx, lalu keluar.
if "!FLASK_ADOPTED!"=="1" (
    if not "%SK_NO_FUNNEL%"=="1" (
        "%VENV_PY%" scripts\funnel_serve.py --port %GATEWAY% --wait-health 20 --verify
    )
    echo.
    echo [backend] nginx : http://127.0.0.1:%GATEWAY%
    echo [backend] Flask : http://%API_HOST%:%PORT%  ^(sudah berjalan, tidak ada proses baru^)
    echo [backend] Untuk berhenti, tekan Ctrl+C di jendela backend yang lama.
    echo.
    exit /b 0
)

echo.
echo [backend] nginx : http://127.0.0.1:%GATEWAY%  (frontend + /api + /hls)
echo [backend] Flask : http://%API_HOST%:%PORT%   (loopback, bukan akses publik)
echo [backend] Ctrl+C untuk berhenti.
echo.
echo [backend] Bila Ctrl+C melewati pembersihan, tutup manual:
echo           backend\gateway\stop-nginx.bat
echo.

if "%SK_NO_FUNNEL%"=="1" (
    echo [backend] SK_NO_FUNNEL=1 - Funnel dilewati, hanya loopback.
) else (
    rem Funnel dibuka di latar belakang SETELAH /api/health menjawab. Sebelumnya
    rem Funnel menyala lebih dulu, jadi permintaan pertama dari halaman Vercel
    rem (termasuk login) sempat menerima 502 selama Flask masih impor modul.
    echo [backend] Funnel disiapkan di latar belakang ^(menunggu backend siap^)...
    start "" /b "%VENV_PY%" scripts\funnel_serve.py --port %GATEWAY% --wait-health 90 --verify
    set "FUNNEL_STARTED=1"
)

"%VENV_PY%" app.py
set "CODE=!ERRORLEVEL!"

if "!FUNNEL_STARTED!"=="1" (
    "%VENV_PY%" scripts\funnel_serve.py --reset >nul 2>&1
    echo [backend] Funnel dimatikan.
)
if "!NGINX_STARTED!"=="1" (
    call "%ROOT%\backend\gateway\stop-nginx.bat" >nul 2>&1
    echo [backend] nginx dihentikan.
)
if "!NGINX_ADOPTED!"=="1" echo [backend] nginx tetap jalan (bukan proses sesi ini).
if not "!CODE!"=="0" (
    echo.
    echo [backend] berhenti dengan kode !CODE!
    pause
)
exit /b !CODE!
