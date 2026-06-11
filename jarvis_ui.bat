@echo off
cd /d "D:\Personal Jarvis"
set "JARVIS_LOG_TO_FILE=1"

where pyw >nul 2>nul
if %errorlevel%==0 (
    start "" pyw -3.11 "D:\Personal Jarvis\jarvis.py"
    start "" pyw -3.11 "D:\Personal Jarvis\jarvis_ui.py"
    exit /b
)

start "Jarvis Core" /min py -3.11 -u "D:\Personal Jarvis\jarvis.py"
start "Jarvis HUD" py -3.11 "D:\Personal Jarvis\jarvis_ui.py"
