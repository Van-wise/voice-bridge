@echo off
chcp 65001 > nul 2>&1
title Voice Bridge - HTTP Mode
cd /d "%~dp0"

REM 备份证书（禁用HTTPS）
if exist "backend\certs\server.crt" (
    if not exist "backend\certs\server.crt.bak" (
        move "backend\certs\server.crt" "backend\certs\server.crt.bak" > nul 2>&1
        move "backend\certs\server.key" "backend\certs\server.key.bak" > nul 2>&1
    )
)

python backend\main.py
