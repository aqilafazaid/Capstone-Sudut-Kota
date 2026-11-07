@echo off
setlocal
set "HERE=%~dp0"
set "ROOT=%HERE%..\.."
pushd "%ROOT%" || exit /b 1
if not exist "backend\gateway\logs" mkdir "backend\gateway\logs"
if not exist "backend\gateway\temp" mkdir "backend\gateway\temp"
"%HERE%tools\nginx\nginx.exe" -p "%CD%" -e backend\gateway\logs\error.log -c backend/gateway/nginx.conf
set "CODE=%ERRORLEVEL%"
popd
endlocal & exit /b %CODE%
