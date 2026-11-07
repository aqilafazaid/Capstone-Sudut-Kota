@echo off
rem Jalankan dari mana saja: backend\gateway\start-nginx.bat
rem Menyalakan nginx di 127.0.0.1:8080 (loopback saja) tanpa memblokir konsol.
setlocal EnableExtensions
set "HERE=%~dp0"
set "ROOT=%HERE%..\.."
pushd "%ROOT%" || exit /b 1
if not exist "backend\gateway\logs" mkdir "backend\gateway\logs"
if not exist "backend\gateway\temp" mkdir "backend\gateway\temp"

if not exist "%HERE%tools\nginx\nginx.exe" (
    echo [nginx] nginx.exe tidak ditemukan di %HERE%tools\nginx\
    popd
    endlocal & exit /b 1
)

netstat -ano | findstr /R /C:":8080 .*LISTENING" >nul
if not errorlevel 1 (
    echo [nginx] port 8080 sudah dipakai; instance kedua tidak dijalankan.
    popd
    endlocal & exit /b 1
)

set "PREFIX=%CD:\=/%"
start "" /b "%HERE%tools\nginx\nginx.exe" -p "%PREFIX%" -e backend\gateway\logs\error.log -c backend/gateway/nginx.conf

set /a TRIES=0
:wait
netstat -ano | findstr /R /C:":8080 .*LISTENING" >nul
if not errorlevel 1 goto ready
set /a TRIES+=1
if %TRIES% GEQ 10 goto failed
ping -n 2 127.0.0.1 >nul
goto wait

:ready
echo [nginx] jalan di http://127.0.0.1:8080 (loopback).
popd
endlocal & exit /b 0

:failed
echo [nginx] gagal start. Cek backend\gateway\logs\error.log
popd
endlocal & exit /b 1
