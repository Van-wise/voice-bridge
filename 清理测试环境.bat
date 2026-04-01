@echo off
chcp 65001 >nul
title Voice Bridge - 测试环境清理

echo.
echo ============================================
echo       Voice Bridge 测试环境清理
echo ============================================
echo.
echo   本工具将清理所有构建产物，模拟新用户环境
echo.
echo   将删除：
echo     1. frontend/node_modules/     - npm 依赖
echo     2. frontend/dist/             - 构建产物
echo     3. backend/certs/            - HTTPS 证书
echo     4. backend/__pycache__/      - Python 缓存
echo     5. backend/*/__pycache__/     - Python 子模块缓存
echo     6. backend/*.pyc              - Python 编译文件
echo     7. backend/voice_bridge.db   - 数据库
echo     8. backend/device_names.json  - 设备记录
echo.
echo   不删除：
echo     - 源代码 (main.py, components 等)
echo     - requirements.txt, package.json
echo     - 配置文件
echo.
echo ============================================
echo.

set /p confirm=确认清理测试环境？(Y/N): 

if /i not "%confirm%"=="Y" (
    echo 已取消
    pause
    exit /b 0
)

set ROOT=%~dp0

echo.
echo [1/8] 清理 frontend/node_modules/ ...
if exist "%ROOT%frontend\node_modules" (
    rmdir /s /q "%ROOT%frontend\node_modules"
    echo   [OK] 已删除
) else (
    echo   [-] 不存在，跳过
)

echo [2/8] 清理 frontend/dist/ ...
if exist "%ROOT%frontend\dist" (
    rmdir /s /q "%ROOT%frontend\dist"
    echo   [OK] 已删除
) else (
    echo   [-] 不存在，跳过
)

echo [3/8] 清理 backend/certs/ ...
if exist "%ROOT%backend\certs" (
    rmdir /s /q "%ROOT%backend\certs"
    echo   [OK] 已删除
) else (
    echo   [-] 不存在，跳过
)

echo [4/8] 清理 backend/__pycache__/ ...
if exist "%ROOT%backend\__pycache__" (
    rmdir /s /q "%ROOT%backend\__pycache__"
    echo   [OK] 已删除
) else (
    echo   [-] 不存在，跳过
)

echo [5/8] 清理 backend/*/__pycache__/ ...
for /d %%d in ("%ROOT%backend\*") do (
    if exist "%%d\__pycache__" (
        rmdir /s /q "%%d\__pycache__"
        echo   [OK] 已清理 %%~nxd
    )
)
echo   [完成]

echo [6/8] 清理 .pyc 文件 ...
for /r "%ROOT%backend\" %%f in (*.pyc) do (
    del /q "%%f" 2>nul
)
echo   [OK] 已清理

echo [7/8] 清理 voice_bridge.db ...
if exist "%ROOT%backend\voice_bridge.db" (
    del /q "%ROOT%backend\voice_bridge.db"
    echo   [OK] 已删除
) else (
    echo   [-] 不存在，跳过
)

echo [8/8] 清理 device_names.json ...
if exist "%ROOT%backend\device_names.json" (
    del /q "%ROOT%backend\device_names.json"
    echo   [OK] 已删除
) else (
    echo   [-] 不存在，跳过
)

echo.
echo ============================================
echo       测试环境清理完成！
echo ============================================
echo.
echo   现在可以测试启动流程：
echo   1. 双击 启动.bat
echo   2. 观察检测和安装流程
echo.
pause
