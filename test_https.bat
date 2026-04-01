@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo === 测试 Voice Bridge HTTPS ===
echo.

REM 启动服务器（后台）
echo [1] 启动服务器...
start /B python backend\main.py > server_test.log 2>&1

REM 等待启动
echo [2] 等待服务器启动 (3秒)...
timeout /t 3 /nobreak >nul

REM 测试 HTTPS
echo [3] 测试 HTTPS 连接...
curl -k -s -o nul -w "   / 响应码: %%{http_code}\n" https://127.0.0.1:7266/
curl -k -s -o nul -w "   /setup 响应码: %%{http_code}\n" https://127.0.0.1:7266/setup
curl -k -s -o nul -w "   /health 响应码: %%{http_code}\n" https://127.0.0.1:7266/health

echo.
echo [4] 查看服务器日志...
type server_test.log

REM 清理
echo.
echo [5] 关闭服务器...
taskkill /F /IM python.exe >nul 2>&1

echo.
echo === 测试完成 ===
pause
