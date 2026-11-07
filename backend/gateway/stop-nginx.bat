@echo off
setlocal
set "HERE=%~dp0"
set "ROOT=%HERE%..\.."
pushd "%ROOT%" || exit /b 1
"%HERE%tools\nginx\nginx.exe" -p "%CD%" -e backend\gateway\logs\error.log -c backend/gateway/nginx.conf -s stop
set "CODE=%ERRORLEVEL%"
popd
endlocal & exit /b %CODE%
