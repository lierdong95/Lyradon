@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Run setup_personasync.bat first.
  exit /b 1
)
".venv\Scripts\python.exe" persona-sync.py
