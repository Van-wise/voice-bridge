@echo off
chcp 65001 >nul
title Voice Bridge - 清理工具

echo.
echo ============================================
echo       Voice Bridge 项目清理工具
echo ============================================
echo.
echo   本工具将删除以下内容：
echo.
echo   1. server/          - 旧版 Flask 代码 (0.17 MB)
echo   2. launcher/         - 旧版托盘工具 (0.06 MB)
echo   3. docs/            - 开发文档 (0.04 MB)
echo   4. audio_uploads/    - 测试录音文件 (1.16 MB)
echo   5. diagnose_vmic.bat - 独立诊断脚本
echo   6. build_frontend.bat - 独立构建脚本
echo   7. 启动HTTPS测试.bat - 冗余启动脚本
echo   8. 启动Cloudflare Tunnel.bat - 冗余启动脚本
echo.
echo   删除后可节省约 2 MB
echo.
echo ============================================
echo.

set /p confirm=确认删除？(Y/N): 

if /i not "%confirm%"=="Y" (
    echo 已取消
    pause
    exit /b 0
)

set ROOT=%~dp0

echo.
echo [1/8] 删除 server/ ...
if exist "%ROOT%server" (
    rmdir /s /q "%ROOT%server"
    echo   已删除
) else (
    echo   不存在，跳过
)

echo [2/8] 删除 launcher/ ...
if exist "%ROOT%launcher" (
    rmdir /s /q "%ROOT%launcher"
    echo   已删除
) else (
    echo   不存在，跳过
)

echo [3/8] 删除 docs/ ...
if exist "%ROOT%docs" (
    rmdir /s /q "%ROOT%docs"
    echo   已删除
) else (
    echo   不存在，跳过
)

echo [4/8] 删除 audio_uploads/ ...
if exist "%ROOT%backend\audio_uploads" (
    rmdir /s /q "%ROOT%backend\audio_uploads"
    echo   已删除
) else (
    echo   不存在，跳过
)

echo [5/8] 删除 diagnose_vmic.bat ...
if exist "%ROOT%diagnose_vmic.bat" (
    del /q "%ROOT%diagnose_vmic.bat"
    echo   已删除
) else (
    echo   不存在，跳过
)

echo [6/8] 删除 build_frontend.bat ...
if exist "%ROOT%build_frontend.bat" (
    del /q "%ROOT%build_frontend.bat"
    echo   已删除
) else (
    echo   不存在，跳过
)

echo [7/8] 删除 启动HTTPS测试.bat ...
if exist "%ROOT%启动HTTPS测试.bat" (
    del /q "%ROOT%启动HTTPS测试.bat"
    echo   已删除
) else (
    echo   不存在，跳过
)

echo [8/8] 删除 启动Cloudflare Tunnel.bat ...
if exist "%ROOT%启动Cloudflare Tunnel.bat" (
    del /q "%ROOT%启动Cloudflare Tunnel.bat"
    echo   已删除
) else (
    echo   不存在，跳过
)

echo.
echo ============================================
echo       清理完成！
echo ============================================
echo.
echo 建议删除的文件（手动处理）：
echo   - backend/debug_audio/ （如果存在）
echo   - backend/__pycache__/
echo.
pause
