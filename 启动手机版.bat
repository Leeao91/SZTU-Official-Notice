@echo off
chcp 65001 >nul
rem Start the mobile web UI and open it in the default browser.
rem Keep this window open while using the phone; close it (or Ctrl+C) to stop.
setlocal
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
where python.exe >nul 2>nul
if %errorlevel%==0 (
    python -u "%~dp0serve.py" --port 8080 --open
) else (
    py -u "%~dp0serve.py" --port 8080 --open
)
pause
