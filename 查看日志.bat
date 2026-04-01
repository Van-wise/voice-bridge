@echo off
chcp 65001 >nul
cd /d "%~dp0backend"

echo.
echo ========================================
echo   Voice Bridge 日志查看工具
echo ========================================
echo.

if not exist "logs\vb.log" (
    echo [错误] 日志文件不存在: logs\vb.log
    echo.
    echo 请先启动 Voice Bridge 服务。
    pause
    exit /b
)

echo [日志路径] %cd%\logs\vb.log
echo.
echo [最近 50 条日志]
echo ========================================

:: 显示日志文件的最后 50 行
powershell -NoProfile -Command "Get-Content 'logs\vb.log' -Tail 50 -Encoding UTF8"

echo.
echo ========================================
echo.
echo 按任意键查看完整日志...
pause

:: 用 Notepad 打开完整日志
start notepad "logs\vb.log"
