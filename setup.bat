@echo off
rem First-time setup for BuddyAI. Safe to run again: it only does what is missing.
rem run_cli.bat and run_web.bat call this for you.
cd /d "%~dp0"

if exist ".venv\Scripts\python.exe" goto check_env
echo Creating the virtual environment and installing packages.
echo This takes a few minutes the first time...
python -m venv .venv
if errorlevel 1 goto no_python
".venv\Scripts\python.exe" -m pip install --quiet -r requirements.txt
if errorlevel 1 goto install_failed

:check_env
if exist "buddy_agent\.env" goto done
copy "buddy_agent\.env.example" "buddy_agent\.env" >nul
echo.
echo Created buddy_agent\.env from the example file.
echo Open it, replace the placeholder with your Gemini API key, then run this again.
exit /b 1

:no_python
echo Could not create the virtual environment. Install Python 3.11 or later first.
exit /b 1

:install_failed
echo Installing the packages failed. Check your internet connection and run this again.
exit /b 1

:done
exit /b 0
