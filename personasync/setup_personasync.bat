@echo off
chcp 65001 >nul
cd /d "%~dp0"
python -m venv .venv
if errorlevel 1 exit /b 1
if not exist "persona-sync.json" copy /y "persona-sync.example.json" "persona-sync.json" >nul
echo Setup complete. Edit persona-sync.json before enabling.
