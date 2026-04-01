@echo off
chcp 65001 >nul
title Voice Bridge 日志查看器

echo ========================================
echo    Voice Bridge 日志查看器
echo ========================================
echo.

set "LOG_FILE=%~dp0backend\logs\vb.log"

if not exist "%LOG_FILE%" (
    echo [错误] 日志文件不存在！
    echo.
    echo 请先启动服务生成日志文件。
    echo 日志文件路径: %LOG_FILE%
    pause
    exit /b 1
)

echo [信息] 日志文件: %LOG_FILE%
echo.

:menu
echo 请选择操作:
echo   1. 查看最近 50 行日志
echo   2. 查看最近 100 行日志
echo   3. 查看所有日志
echo   4. 查看错误日志 (ERROR)
echo   5. 实时追踪日志 (Ctrl+C 退出)
echo   6. 清空日志文件
echo   0. 退出
echo.
set /p choice=请输入选项 [1-6, 0退出]:

if "%choice%"=="1" goto tail50
if "%choice%"=="2" goto tail100
if "%choice%"=="3" goto all
if "%choice%"=="4" goto errors
if "%choice%"=="5" goto follow
if "%choice%"=="6" goto clear
if "%choice%"=="0" goto end

echo [错误] 无效选项，请重新选择
echo.
goto menu

:tail50
echo.
echo ============= 最近 50 行 =============
powershell -command "Get-Content '%LOG_FILE%' -Tail 50"
echo.
goto done

:tail100
echo.
echo ============= 最近 100 行 =============
powershell -command "Get-Content '%LOG_FILE%' -Tail 100"
echo.
goto done

:all
echo.
echo ============= 全部日志 =============
powershell -command "Get-Content '%LOG_FILE%'"
echo.
goto done

:errors
echo.
echo ============= 错误日志 =============
powershell -command "Select-String -Path '%LOG_FILE%' -Pattern 'ERROR|Exception|Traceback' | Select-Object -Last 50"
echo.
goto done

:follow
echo.
echo ============= 实时追踪日志 =============
echo 按 Ctrl+C 退出追踪模式
echo.
powershell -command "Get-Content '%LOG_FILE%' -Wait -Tail 30"
goto done

:clear
echo.
set /p confirm=确定要清空日志文件吗？ (Y/N):
if /i "%confirm%"=="Y" (
    type nul > "%LOG_FILE%"
    echo [成功] 日志文件已清空
) else (
    echo 已取消
)
echo.
goto done

:done
echo.
echo ----------------------------------------
echo 按任意键返回菜单...
pause >nul
goto menu

:end
echo.
echo 再见！
