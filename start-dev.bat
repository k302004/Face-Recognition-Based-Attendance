@echo off
setlocal
cd /d "%~dp0"

if not exist storage\logs mkdir storage\logs

if "%HTTP_PORT%"=="" set "HTTP_PORT=8092"
if "%SERIAL_PORT%"=="" set "SERIAL_PORT=COM3"
if "%BAUD%"=="" set "BAUD=115200"

rem Detect Python
set "PYEXE=python"
python --version >nul 2>&1
if errorlevel 1 (
    set "PYEXE=python3"
    python3 --version >nul 2>&1
    if errorlevel 1 (
        echo Python was not found on PATH. Install Python and retry.
        pause
        exit /b 1
    )
)

echo Starting camera stream...
start "Camera Stream" cmd /k "%PYEXE% scripts\camera_stream.py"

echo Starting Pi SMS bridge on port %HTTP_PORT% (serial %SERIAL_PORT% @ %BAUD%)...
start "Pi SMS Bridge" cmd /k "%PYEXE% scripts\send_to_pi.py --serve --http-port %HTTP_PORT% --serial-port %SERIAL_PORT% --baud %BAUD%"

echo Starting Laravel dev server (composer run dev)...
start "Laravel Dev" cmd /k "composer run dev"

echo.
echo All processes started in separate windows.
echo Close those windows (or press Ctrl+C in them) to stop.
pause
endlocal