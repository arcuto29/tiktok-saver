@echo off
cd /d "%~dp0"
if not exist .venv (
  echo First run: setting things up...
  python -m venv .venv || (echo Install Python from https://www.python.org/downloads/ and tick "Add to PATH". & pause & exit /b 1)
)
.venv\Scripts\python -m pip install -q --upgrade -r requirements.txt
.venv\Scripts\python tiktok_saver.py
pause
