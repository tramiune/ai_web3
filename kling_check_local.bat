@echo off
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
python kling_check.py
pause
