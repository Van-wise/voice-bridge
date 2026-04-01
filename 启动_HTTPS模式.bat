@echo off
chcp 65001 > nul
title Voice Bridge - HTTPS Mode
cd /d "%~dp0"

echo.
echo ==================================================
echo  Voice Bridge - HTTPS Mode
echo ==================================================
echo.
echo  This mode supports BOTH local and mobile access.
echo.
echo  PC Access (recommended): http://localhost:7266
echo  Mobile Access:          https://YOUR_IP:7266
echo  Setup Page:              http://localhost:7266/setup
echo.
echo ==================================================
echo.

REM Restore certificates for HTTPS
if exist "backend\certs\server.crt.bak" (
    move /Y "backend\certs\server.crt.bak" "backend\certs\server.crt" > nul
    move /Y "backend\certs\server.key.bak" "backend\certs\server.key" > nul
    echo [OK] Certificates restored
    echo.
)

python backend\main.py
