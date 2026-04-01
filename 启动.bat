@echo off
chcp 65001 >nul
title Voice Bridge Server
cd /d "%~dp0"
echo ============================================================
echo  Voice Bridge 启动器
echo ============================================================
python backend\launcher.py
pause
