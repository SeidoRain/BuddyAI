@echo off
rem Start the BuddyAI terminal chat. Double-click this file, or run it from a terminal.
cd /d "%~dp0"
call "%~dp0setup.bat"
if errorlevel 1 goto failed

".venv\Scripts\python.exe" main.py
if errorlevel 1 goto failed
exit /b 0

:failed
echo.
pause
exit /b 1
