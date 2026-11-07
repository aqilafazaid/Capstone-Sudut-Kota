@echo off
rem ============================================================
rem  Sudut Kota - backend Flask (satu terminal untuk dua mode)
rem  Pakai: start-backend.bat
rem  API:   http://127.0.0.1:5000/api/health
rem  Stop:  Ctrl+C
rem
rem  Mode lokal  : start-backend.bat + start-frontend.bat
rem                halaman 8787 memanggil http://127.0.0.1:5000
rem  Mode Vercel : start-backend.bat saja
rem                skrip ini menyalakan Tailscale Funnel sehingga halaman
rem                Vercel memanggil https://<node>.<tailnet>.ts.net
rem ============================================================
setlocal
cd /d "%~dp0backend" || exit /b 1

set "VENV_PY=%CD%\.venv\Scripts\python.exe"
if not exist "%VENV_PY%" (
    echo [!] Virtual environment belum ada: %CD%\.venv
    echo     Buat dulu:
    echo         cd /d "%~dp0backend"
    echo         python -m venv .venv
    echo         .venv\Scripts\python.exe -m pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)

rem Autostart stream (ffmpeg untuk node aktif) aktif secara default.
rem Matikan dengan menghapus "rem" di baris berikut:
rem set "STREAM_AUTOSTART=false"

set "PORT=5000"
if not "%API_PORT%"=="" set "PORT=%API_PORT%"

netstat -ano | findstr /R /C:":%PORT% .*LISTENING" >nul
if not errorlevel 1 (
    echo [!] Port %PORT% sudah dipakai proses lain. Cek dengan:
    echo         netstat -ano ^| findstr :%PORT%
    echo     Hentikan proses itu, atau jalankan dengan port lain:
    echo         set API_PORT=5001 ^&^& start-backend.bat
    echo.
    pause
    exit /b 1
)

echo [backend] http://127.0.0.1:%PORT%  (Flask, Ctrl+C untuk berhenti)
echo.

rem Siapkan Tailscale Funnel untuk halaman Vercel. Kegagalan di sini tidak
rem menghentikan backend: mode lokal (start-frontend.bat) tetap jalan.
"%VENV_PY%" scripts\funnel_serve.py --port %PORT%
if errorlevel 2 (
    echo [backend] Funnel belum siap - halaman Vercel belum bisa menghubungi backend.
    echo.
)

"%VENV_PY%" app.py
set "CODE=%ERRORLEVEL%"

rem Backend berhenti: tutup akses publik supaya port ini tidak tetap terbuka.
"%VENV_PY%" scripts\funnel_serve.py --reset >nul 2>&1

if not "%CODE%"=="0" (
    echo.
    echo [backend] berhenti dengan kode %CODE%
    pause
)
endlocal & exit /b %CODE%
