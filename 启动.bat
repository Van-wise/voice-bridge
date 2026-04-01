@echo off
chcp 65001 >nul 2>&1
title Voice Bridge Server
cd /d "%~dp0"

REM 检查 Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python 未安装
    pause
    exit /b 1
)

REM 检查后端目录
if not exist "backend\main.py" (
    echo [ERROR] 未找到 backend\main.py
    pause
    exit /b 1
)

REM 启动服务（输出全部由 Python 处理）
python backend\main.py

pause
