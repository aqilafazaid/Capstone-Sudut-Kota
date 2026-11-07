@echo off
setlocal
set "ROOT=%~dp0..\.."
pushd "%ROOT%" || exit /b 1
"%~dp0..\..\tools\nginx\nginx.exe" -p "%CD%" -c backend/nginx/nginx.conf -s stop
set "CODE=%ERRORLEVEL%"
popd
endlocal & exit /b %CODE%
