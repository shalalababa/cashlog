@echo off
cd /d "%~dp0backend"
start "" "http://127.0.0.1:8000"
python -m scripts.serve
pause