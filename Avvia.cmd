@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
py -3.12 -c "import sys;sys.exit(sys.version_info[:2] != (3,12))" >nul 2>&1
if not errorlevel 1 (
    py -3.12 -X utf8 start.py %*
    goto finished
)
python3.12 -c "import sys;sys.exit(sys.version_info[:2] != (3,12))" >nul 2>&1
if not errorlevel 1 (
    python3.12 -X utf8 start.py %*
    goto finished
)
python -c "import sys;sys.exit(sys.version_info[:2] != (3,12))" >nul 2>&1
if not errorlevel 1 (
    python -X utf8 start.py %*
    goto finished
)
echo Python 3.12 x64 non trovato. Installa Python 3.12 da https://www.python.org/downloads/windows/ includendo il launcher py.
pause
exit /b 1
:finished
set "minimax_exit=%errorlevel%"
echo.
echo Programma terminato.
pause
exit /b %minimax_exit%
