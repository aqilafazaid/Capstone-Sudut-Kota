@echo off
rem Jalankan dari mana saja: backend\gateway\stop-nginx.bat
rem Urutan: quit (graceful) -> stop -> matikan PID nginx yang masih memegang port.
setlocal EnableExtensions
set "HERE=%~dp0"
set "ROOT=%HERE%..\.."
pushd "%ROOT%" || exit /b 1

netstat -ano | findstr /R /C:":8080 .*LISTENING" >nul
if errorlevel 1 goto already_free

if not exist "backend\gateway\logs\nginx.pid" goto foreign
set /p NGINX_PID=<"backend\gateway\logs\nginx.pid"

set "PREFIX=%CD:\=/%"
"%HERE%tools\nginx\nginx.exe" -p "%PREFIX%" -e backend\gateway\logs\error.log -c backend/gateway/nginx.conf -s quit >nul 2>&1

set /a I=0
:wait_quit
netstat -ano | findstr /R /C:":8080 .*LISTENING" >nul
if errorlevel 1 goto stopped
set /a I+=1
if %I% GEQ 3 goto try_stop
ping -n 2 127.0.0.1 >nul
goto wait_quit

:try_stop
"%HERE%tools\nginx\nginx.exe" -p "%PREFIX%" -e backend\gateway\logs\error.log -c backend/gateway/nginx.conf -s stop >nul 2>&1

set /a I=0
:wait_stop
netstat -ano | findstr /R /C:":8080 .*LISTENING" >nul
if errorlevel 1 goto stopped
set /a I+=1
if %I% GEQ 2 goto hard_kill
ping -n 2 127.0.0.1 >nul
goto wait_stop

:hard_kill
rem Master sudah mati tetapi worker masih memegang socket: matikan worker
rem hanya kalau prosesnya memang nginx.exe.
set "LISTEN_PID="
for /f "tokens=5" %%p in ('netstat -ano ^| findstr /R /C:":8080 .*LISTENING"') do set "LISTEN_PID=%%p"
if "%LISTEN_PID%"=="" goto stopped
tasklist /FI "PID eq %LISTEN_PID%" | findstr /C:"nginx.exe" >nul
if errorlevel 1 goto foreign_listener
taskkill /F /PID %LISTEN_PID% >nul 2>&1
tasklist /FI "PID eq %NGINX_PID%" | findstr /C:"nginx.exe" >nul
if not errorlevel 1 taskkill /F /PID %NGINX_PID% >nul 2>&1
ping -n 2 127.0.0.1 >nul
netstat -ano | findstr /R /C:":8080 .*LISTENING" >nul
if errorlevel 1 goto stopped
echo [nginx] GAGAL menghentikan nginx. Hentikan manual:
netstat -ano | findstr /R /C:":8080 .*LISTENING"
popd
endlocal & exit /b 1

:foreign_listener
echo [nginx] port 8080 dipegang proses non-nginx; tidak dihentikan.
netstat -ano | findstr /R /C:":8080 .*LISTENING"
popd
endlocal & exit /b 1

:foreign
echo [nginx] port 8080 dipakai proses lain ^(nginx.pid tidak ada^).
netstat -ano | findstr /R /C:":8080 .*LISTENING"
popd
endlocal & exit /b 1

:already_free
echo [nginx] tidak ada listener di 8080.
popd
endlocal & exit /b 0

:stopped
echo [nginx] dihentikan.
popd
endlocal & exit /b 0
