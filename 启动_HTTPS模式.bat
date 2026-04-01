@echo off
chcp 65001 > nul 2>&1
title Voice Bridge - HTTPS Mode
cd /d "%~dp0"

REM 恢复证书（启用HTTPS）
if exist "backend\certs\server.crt.bak" (
    move /Y "backend\certs\server.crt.bak" "backend\certs\server.crt" > nul 2>&1
    move /Y "backend\certs\server.key.bak" "backend\certs\server.key" > nul 2>&1
)

python backend\main.py
