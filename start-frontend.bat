@echo off
rem ============================================================
rem  Sudut Kota - frontend statis (terminal 2 dari 2, mode lokal)
rem
rem  Pakai: start-frontend.bat [port]     default 8787
rem  Buka : http://127.0.0.1:8787
rem  Stop : Ctrl+C
rem
rem  Server ini hanya mendengarkan di loopback, jadi tidak ada akses
rem  dari LAN. Untuk menguji jalur produksi (nginx) buka:
rem  http://127.0.0.1:8080
rem
rem  Halaman Vercel tetap memakai Tailscale Funnel yang dinyalakan
rem  start-backend.bat selama backend berjalan.
rem
rem  Set SK_NO_OPEN=1 untuk tidak membuka browser otomatis.
rem ============================================================
setlocal EnableExtensions
cd /d "%~dp0frontend" || exit /b 1

set "PORT=%~1"
if "%PORT%"=="" set "PORT=8787"

set "PY="
rem Uji interpreter-nya benar-benar jalan: stub Microsoft Store lolos "where"
rem tetapi gagal saat dipakai.
python -c "import sys" >nul 2>&1 && set "PY=python"
if not defined PY (
    py -3 -c "import sys" >nul 2>&1 && set "PY=py -3"
)
if not defined PY (
    echo [!] Python tidak ditemukan di PATH.
    echo     Install Python 3, atau tambahkan foldernya ke PATH.
    echo.
    pause
    exit /b 1
)

netstat -ano | findstr /R /C:":%PORT% .*LISTENING" >nul
if not errorlevel 1 (
    echo [!] Port %PORT% sudah dipakai proses lain - mungkin server lain sudah jalan.
    echo     Buka saja http://127.0.0.1:%PORT%/, atau jalankan dengan port lain:
    echo         start-frontend.bat 8788
    echo.
    pause
    exit /b 1
)

if not defined SK_NO_OPEN start "" /min powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 2; Start-Process 'http://127.0.0.1:%PORT%/'"

echo [frontend] http://127.0.0.1:%PORT%/  (loopback saja, Ctrl+C untuk berhenti)
netstat -ano | findstr /R /C:":8080 .*LISTENING" >nul
if not errorlevel 1 echo [frontend] jalur nginx juga aktif: http://127.0.0.1:8080
echo.
%PY% -m http.server --bind 127.0.0.1 %PORT%
set "CODE=%ERRORLEVEL%"
if not "%CODE%"=="0" (
    echo.
    echo [frontend] berhenti dengan kode %CODE%
    pause
)
endlocal & exit /b %CODE%
