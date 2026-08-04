@echo off
setlocal EnableExtensions
chcp 65001 >nul
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"

REM launcher\ 的上一级即仓库根；UNC 下勿用 cd/%CD%
set "SCRIPT_DIR=%~dp0"
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"
for %%I in ("%SCRIPT_DIR%\..") do set "AX_PROJECT_ROOT=%%~fI"

pushd "%AX_PROJECT_ROOT%" 2>nul
if errorlevel 1 (
  echo [Axiodrasil] Cannot enter project folder:
  echo   %AX_PROJECT_ROOT%
  pause
  exit /b 1
)

python -m launcher
set "ERR=%ERRORLEVEL%"
popd

if not "%ERR%"=="0" (
  echo.
  echo Start failed. Install deps:
  echo   pip install -r launcher\requirements-launcher.txt
  pause
  exit /b %ERR%
)
