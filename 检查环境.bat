@echo off
chcp 65001 >nul
title Voice Bridge - 环境检查与修复

echo.
echo ========================================
echo   Voice Bridge 环境检查与修复
echo ========================================
echo.

cd /d "%~dp0"

:: ========================================
:: 1. 检查 Python
:: ========================================
echo [1/6] 检查 Python 环境...

python --version >nul 2>&1
if errorlevel 1 (
    echo   [X] Python 未安装或未添加到 PATH
    echo   请从 https://python.org 安装 Python 3.8+
    echo.
    pause
    exit /b 1
)

for /f "tokens=2" %%i in ('python --version 2^>^&1') do set PYVER=%%i
echo   [OK] Python %PYVER%

:: ========================================
:: 2. 安装 Python 依赖
:: ========================================
echo.
echo [2/6] 检查 Python 依赖...

cd /d "%~dp0backend"

python -c "import fastapi" >nul 2>&1
if errorlevel 1 (
    echo   [!] 正在安装核心依赖...
    python -m pip install fastapi "uvicorn[standard]" pydantic pydantic-settings websockets pyperclip sounddevice numpy
    if errorlevel 1 (
        echo   [X] 核心依赖安装失败
        pause
        exit /b 1
    )
    echo   [OK] 核心依赖安装完成
) else (
    echo   [OK] 核心依赖已安装
)

:: 检查可选依赖（自动粘贴功能）
python -c "import pyautogui" >nul 2>&1
if errorlevel 1 (
    echo   [!] 可选依赖 pyautogui 未安装（自动粘贴功能不可用）
)

cd /d "%~dp0"

:: ========================================
:: 3. 检查 Node.js
:: ========================================
echo.
echo [3/6] 检查 Node.js...

node --version >nul 2>&1
if errorlevel 1 (
    echo   [X] Node.js 未安装
    echo   请从 https://nodejs.org 安装
    echo.
    echo   [!] 无法构建前端，退出
    pause
    exit /b 1
)

for /f "tokens=1" %%i in ('node --version') do set NODEVER=%%i
echo   [OK] Node.js %NODEVER%

:: ========================================
:: 4. 安装前端依赖
:: ========================================
echo.
echo [4/6] 检查前端依赖...

cd /d "%~dp0frontend"

if not exist "node_modules" (
    echo   [!] node_modules 不存在，正在安装...
    call npm install --no-audit --no-fund --ignore-scripts
    if errorlevel 1 (
        echo   [X] npm install 失败
        pause
        exit /b 1
    )
    echo   [OK] 依赖安装完成
) else (
    if not exist "node_modules\vite" (
        echo   [!] vite 未安装完整，正在重新安装...
        rd /s /q node_modules 2>nul
        call npm install --no-audit --no-fund --ignore-scripts
        if errorlevel 1 (
            echo   [X] npm install 失败
            pause
            exit /b 1
        )
        echo   [OK] 依赖安装完成
    ) else (
        echo   [OK] 前端依赖已安装
    )
)

cd /d "%~dp0"

:: ========================================
:: 5. 构建前端
:: ========================================
echo.
echo [5/6] 检查前端构建...

if not exist "frontend\dist\index.html" (
    echo   [!] 前端未构建，正在构建...
    cd /d "%~dp0frontend"
    call node node_modules\vite\bin\vite.js build
    if errorlevel 1 (
        echo   [X] 前端构建失败
        pause
        exit /b 1
    )
    echo   [OK] 前端构建完成
) else (
    echo   [OK] 前端已构建
)

cd /d "%~dp0"

:: ========================================
:: 6. 检查/生成证书
:: ========================================
echo.
echo [6/6] 检查 HTTPS 证书...

if not exist "backend\certs\server.crt" (
    echo   [!] 证书不存在，尝试生成...
    cd /d "%~dp0backend"
    
    :: 尝试使用 cryptography
    python -c "from cryptography import x509" >nul 2>&1
    if not errorlevel 1 (
        echo   [i] 使用 cryptography 生成证书...
        python generate_cert.py
        if exist "certs\server.crt" (
            echo   [OK] 证书生成成功
        ) else (
            echo   [!] 证书生成失败，将使用 HTTP 模式
        )
    ) else (
        :: 尝试使用 openssl
        where openssl >nul 2>&1
        if not errorlevel 1 (
            echo   [i] 使用 openssl 生成证书...
            if not exist "certs" mkdir certs
            openssl req -new -x509 -keyout certs\server.key -out certs\server.crt -days 365 -nodes -subj "/CN=localhost"
            if exist "certs\server.crt" (
                echo   [OK] 证书生成成功
            ) else (
                echo   [!] 证书生成失败，将使用 HTTP 模式
            )
        ) else (
            echo   [!] 未找到证书生成工具，将使用 HTTP 模式
            echo   [i] 安装 cryptography: pip install cryptography
            echo   [i] 或安装 OpenSSL: https://slproweb.com/products/Win32OpenSSL.html
        )
    )
    
    cd /d "%~dp0"
) else (
    echo   [OK] 证书已存在
)

:: ========================================
:: 完成
:: ========================================
echo.
echo ========================================
echo   环境检查完成！
echo ========================================
echo.
echo   下一步：运行 启动服务.bat 启动 Voice Bridge
echo.
pause
