@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo ============================================================
echo   电真万确 - AI 赋能电力教学仿真平台（仅本机模式）
echo ============================================================
echo   运行方式：只监听 127.0.0.1，只有这台电脑能访问
echo             不开放端口、不需要修改防火墙
echo ============================================================

where python >nul 2>nul
if errorlevel 1 (
  echo [错误] 未检测到 Python，请先安装 Python 3.11 及以上版本。
  echo        安装时请勾选 "Add python.exe to PATH"。
  pause
  exit /b 1
)

set "POWEREDU_PORT=8000"
if not "%~1"=="" set "POWEREDU_PORT=%~1"

set PYTHONIOENCODING=utf-8
python -m server.app --port %POWEREDU_PORT% --open

echo.
echo 服务已退出。若为异常退出，请把上方报错信息反馈给平台维护人员。
pause
