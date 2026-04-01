@echo off
chcp 65001 >nul
title Voice Bridge HTTPS 测试

cd /d "%~dp0"
set "LOG_FILE=%~dp0https_test.log"

echo ============================================================
echo  Voice Bridge HTTPS 功能测试
echo ============================================================
echo.

REM 清理之前的进程
taskkill /F /IM python.exe >nul 2>&1
timeout /t 1 /nobreak >nul

REM 启动服务器
echo [1/6] 启动服务器（后台运行）...
start /B python backend\main.py > "%LOG_FILE%" 2>&1
timeout /t 3 /nobreak >nul
echo       已启动，日志: %LOG_FILE%
echo.

REM 检查服务器是否启动
echo [2/6] 检查服务器状态...
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":7266" ^| findstr "LISTENING"') do (
    echo       进程 PID: %%a
    goto :server_ok
)
:server_ok

REM 测试 HTTP 连接
echo [3/6] 测试 HTTP 连接...
curl -s -o nul -w "       HTTP /: %%{http_code} %%{time_total}s\n" http://127.0.0.1:7266/

REM 测试 HTTPS 连接（跳过证书验证）
echo [4/6] 测试 HTTPS 连接（跳过证书验证）...
curl -k -s -o nul -w "       HTTPS /: %%{http_code} %%{time_total}s\n" https://127.0.0.1:7266/
curl -k -s -o nul -w "       HTTPS /setup: %%{http_code} %%{time_total}s\n" https://127.0.0.1:7266/setup
curl -k -s -o nul -w "       HTTPS /health: %%{http_code} %%{time_total}s\n" https://127.0.0.1:7266/health
curl -k -s -o nul -w "       HTTPS /api/poll: %%{http_code} %%{time_total}s\n" https://127.0.0.1:7266/api/poll

REM 测试 setup 页面内容
echo [5/6] 检查 setup 页面内容...
curl -k -s https://127.0.0.1:7266/setup | findstr /C:"VoiceBridge" /C:"证书" >nul
if %errorlevel%==0 (
    echo       setup.html 包含正确内容
) else (
    echo       setup.html 内容可能有问题
)

REM 测试证书信息
echo [6/6] 证书信息...
curl -k -s https://127.0.0.1:7266/cert/info

echo.
echo ============================================================
echo  测试完成
echo ============================================================
echo.
echo 查看日志: type %LOG_FILE%
echo.
echo 访问地址:
echo   电脑: http://127.0.0.1:7266
echo   手机: https://192.168.1.9:7266
echo   证书: https://192.168.1.9:7266/setup
echo.

REM 询问是否关闭服务器
set /p CLOSE="关闭测试服务器? (y/n): "
if /i "%CLOSE%"=="y" (
    taskkill /F /IM python.exe >nul 2>&1
    echo 服务器已关闭
) else (
    echo 服务器继续运行中
)

pause
