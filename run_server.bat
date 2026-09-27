@echo off
setlocal
cd /d "%~dp0"

REM ---------------------------------------------------------------
REM  FOAI dashboard launcher
REM  Keep this window OPEN on failure so errors are readable
REM  instead of flashing for one second and vanishing.
REM ---------------------------------------------------------------

set "PORT=8000"
set "URL=http://127.0.0.1:%PORT%/"

REM Resolve a Python interpreter: prefer PATH, fall back to the py launcher.
set "PY="
where python >nul 2>nul && set "PY=python"
if not defined PY (
    where py >nul 2>nul && set "PY=py -3"
)
if not defined PY (
    echo [ERROR] No Python interpreter found on PATH.
    echo         Install Python 3.10+ and re-run, or use the py launcher.
    goto :fail
)

REM Is the port already serving? Then something is already up.
powershell -NoProfile -Command ^
  "try { $c = New-Object Net.Sockets.TcpClient('127.0.0.1', %PORT%); $c.Close(); exit 0 } catch { exit 1 }" >nul 2>nul
if not errorlevel 1 goto :inuse

echo Starting FOAI dashboard at %URL%
echo Press Ctrl+C in THIS window to stop the server.
echo.
%PY% -m uvicorn web.main:app --host 127.0.0.1 --port %PORT%
if errorlevel 1 goto :fail
echo.
echo Server stopped.
goto :end

:inuse
echo [INFO] Port %PORT% is already in use - a server is ALREADY running.
echo        The dashboard is live at:  %URL%
echo.
echo        Opening your browser now. Close this window.
start "" "%URL%"
goto :end

:fail
echo.
echo ==============================================================
echo  STARTUP FAILED - the window stays open so you can read this.
echo ==============================================================
echo.
echo  Most common cause: port %PORT% is already in use.
echo  Find the process holding it:
echo      netstat -ano ^| findstr :%PORT%
echo  Then stop it:
echo      taskkill /PID ^<pid^> /F
echo.
echo  If it is a stale FOAI server, this script would have opened your
echo  browser instead. If Python is missing, install Python 3.10+ and
echo  ensure it is on PATH.
echo.
pause

:end
endlocal

