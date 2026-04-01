@echo off
chcp 65001 > nul
title Voice Bridge - HTTP Mode (localhost only)
cd /d "%~dp0"

echo.
echo ==================================================
echo  Voice Bridge - HTTP Mode
echo ==================================================
echo.
echo  This mode is for LOCAL PC only.
echo  Mobile access requires HTTPS and certificate.
echo.
echo  Access: http://localhost:7266
echo.
echo ==================================================
echo.

REM Backup certificates to disable HTTPS
if exist "backend\certs\server.crt" (
    if not exist "backend\certs\server.crt.bak" (
        move "backend\certs\server.crt" "backend\certs\server.crt.bak" > nul
        move "backend\certs\server.key" "backend\certs\server.key.bak" > nul
        echo [OK] Certificates backed up - starting in HTTP mode
        echo.
        echo IMPORTANT: Use http://localhost:7266 (not HTTPS)
        echo.
    )
)

echo Starting server...
echo.
python backend\main.py
