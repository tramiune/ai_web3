@echo off
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
echo Kaling bot LOCAL — Kling Playwright (Firestore: kaling_vps_bot)
echo Bật/Tắt tren Admin -^> Bots -^> kaling_vps_bot
echo.
python -u bot.py --name kaling_vps_bot
pause
