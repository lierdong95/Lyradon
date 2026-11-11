@echo off
setlocal
cd /d "%~dp0"
if not exist "..\langbot-venv\Scripts\python.exe" (
  python -m venv "..\langbot-venv"
  if errorlevel 1 exit /b 1
)
"..\langbot-venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 exit /b 1
echo Installed. Configure LangBot separately; no private data or plugin is included.
