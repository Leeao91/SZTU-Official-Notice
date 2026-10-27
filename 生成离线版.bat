@echo off
chcp 65001 >nul
rem Build a single self-contained HTML (last 14 days inlined) that works offline.
rem Send it to the phone (WeChat / QQ / cloud drive) and open with any browser.
setlocal
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
where python.exe >nul 2>nul
if %errorlevel%==0 (
    python "%~dp0serve.py" --export "%~dp0reports\手机版-离线.html" --days 14
) else (
    py "%~dp0serve.py" --export "%~dp0reports\手机版-离线.html" --days 14
)
echo.
echo Output: reports\手机版-离线.html  -- send it to your phone, open in browser.
pause
