@echo off
setlocal
cd /d "%~dp0"
rem Reuse the same guarded launcher as the VBS shortcuts.
cscript.exe //Nologo "Start All.vbs"
exit /b %errorlevel%
