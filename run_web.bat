@echo off
rem Start the BuddyAI browser chat (ADK web UI). Double-click this file, or run it
rem from a terminal. Set BUDDYAI_NO_BROWSER=1 to stop it opening a browser tab.
cd /d "%~dp0"
call "%~dp0setup.bat"
if errorlevel 1 goto failed

set "BUDDYAI_URL=http://127.0.0.1:8000/dev-ui/?app=buddy_agent"
echo BuddyAI browser chat: %BUDDYAI_URL%
echo Leave this window open while you chat. Press Ctrl+C here to stop.
echo.
if defined BUDDYAI_NO_BROWSER goto start_server
rem Open the page a few seconds from now, once the server below has started.
start "" /b powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep -Seconds 7; Start-Process $env:BUDDYAI_URL"

:start_server
".venv\Scripts\adk.exe" web --port 8000
exit /b 0

:failed
echo.
pause
exit /b 1
