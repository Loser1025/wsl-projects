@echo off
setlocal
cd /d "%~dp0"
set "PILOT_PY=C:\Users\mitsuba864\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
if not exist "%PILOT_PY%" set "PILOT_PY=python"
"%PILOT_PY%" -m unittest -v
if errorlevel 1 goto failed
"%PILOT_PY%" pilot.py demo
if errorlevel 1 goto failed
start "" "data\demo\review.html"
pause
exit /b 0
:failed
echo Pilot verification failed. See the output above.
pause
exit /b 1
