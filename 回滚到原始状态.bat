@echo off
chcp 65001 >nul
echo ============================================
echo   Voice Bridge 回滚脚本
echo   恢复 dual_protocol_server 到原始状态
echo ============================================
echo.

set BACKUP_DIR=%~dp0backup_before_dual_protocol
set BACKEND_DIR=%~dp0backend

if not exist "%BACKUP_DIR%" (
    echo [错误] 备份目录不存在: %BACKUP_DIR%
    echo 请确保运行过本项目的任何修改脚本
    pause
    exit /b 1
)

echo [1/3] 检查备份文件...
if not exist "%BACKUP_DIR%\dual_protocol_server.py.bak" (
    echo [错误] 找不到备份文件: dual_protocol_server.py.bak
    pause
    exit /b 1
)

if not exist "%BACKUP_DIR%\main.py.bak" (
    echo [错误] 找不到备份文件: main.py.bak
    pause
    exit /b 1
)

echo [2/3] 恢复文件...
copy /Y "%BACKUP_DIR%\dual_protocol_server.py.bak" "%BACKEND_DIR%\dual_protocol_server.py"
copy /Y "%BACKUP_DIR%\main.py.bak" "%BACKEND_DIR%\main.py"

if exist "%BACKUP_DIR%\generate_cert.py.bak" (
    copy /Y "%BACKUP_DIR%\generate_cert.py.bak" "%BACKEND_DIR%\generate_cert.py"
)

echo [3/3] 清理备份目录...
echo.
echo ============================================
echo   回滚完成！
echo ============================================
echo.
echo 已恢复以下文件:
echo   - backend\dual_protocol_server.py
echo   - backend\main.py
echo   - backend\generate_cert.py (如存在)
echo.
echo 如需完全清理备份，请删除目录:
echo   %BACKUP_DIR%
echo.
pause
