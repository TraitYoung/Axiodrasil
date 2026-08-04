@echo off
setlocal EnableExtensions
chcp 65001 >nul
echo.
echo Axiodrasil now runs inside WSL Ubuntu only.
echo Do NOT use this Windows .cmd for daily start.
echo.
echo Open Ubuntu terminal and run:
echo   cd ~/Axiodrasil
echo   ./start.sh
echo.
echo First-time setup:
echo   ./scripts/setup_linux_env.sh
echo.
pause
