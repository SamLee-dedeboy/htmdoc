@echo off
REM Double-click this file to start the htmdoc helper.
REM Leave this window open while you edit; close it when you're done.
REM
REM To add options, edit the "python htmdoc.py" line below, e.g.:
REM   python htmdoc.py --root "%USERPROFILE%\Documents"
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo Python was not found on your PATH.
  echo Install it once from https://www.python.org/downloads/ and tick
  echo "Add python.exe to PATH" during setup, then double-click this file again.
  pause
  exit /b 1
)
python htmdoc.py %*
echo.
echo The helper stopped. Close this window or press a key to exit.
pause
