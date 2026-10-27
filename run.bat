@echo off
chcp 65001 >nul
rem Run the digest once, with console output visible.
rem Extra args are passed through to nbw_digest.py:
rem   run.bat --dry-run    print only, no files written
rem   run.bat --test       parse list page only
rem   run.bat --rebuild    rebuild baseline
setlocal
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
where python.exe >nul 2>nul
if %errorlevel%==0 (
    python "%~dp0nbw_digest.py" %*
) else (
    py "%~dp0nbw_digest.py" %*
)
echo.
pause
