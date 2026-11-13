@echo off
setlocal
cd /d "%~dp0"

if not exist storage\logs mkdir storage\logs

if "%HTTP_PORT%"=="" set "HTTP_PORT=8092"
if "%SERIAL_PORT%"=="" set "SERIAL_PORT=COM3"
if "%BAUD%"=="" set "BAUD=115200"

echo Starting Pi SMS bridge on port %HTTP_PORT% (serial %SERIAL_PORT% @ %BAUD%)...
start "Pi SMS Bridge" cmd /k "python scripts\send_to_pi.py --serve --http-port %HTTP_PORT% --serial-port %SERIAL_PORT% --baud %BAUD%"

echo Starting Laravel dev server (composer run dev)...
start "Laravel Dev" cmd /k "composer run dev"

echo.
echo Both processes started in separate windows.
echo Close those windows (or press Ctrl+C in them) to stop.
endlocal