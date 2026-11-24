#!/bin/bash
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  echo "First run: setting things up..."
  python3 -m venv .venv || { echo "Install Python 3 first: https://www.python.org/downloads/"; exit 1; }
fi
.venv/bin/python -m pip install -q --upgrade -r requirements.txt
.venv/bin/python tiktok_saver.py
