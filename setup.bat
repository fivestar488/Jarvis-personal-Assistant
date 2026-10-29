@echo off
rem One-time setup. The Python environment lives outside OneDrive so it doesn't get synced.
set VENV=%LOCALAPPDATA%\JarvisVenv
cd /d "%~dp0"
if not exist "%VENV%\Scripts\python.exe" python -m venv "%VENV%"
"%VENV%\Scripts\python.exe" -m pip install --upgrade pip
"%VENV%\Scripts\python.exe" -m pip install -r requirements.txt
if not exist .env copy .env.example .env
echo.
echo Setup done. Open .env, paste your ANTHROPIC_API_KEY, then run jarvis.bat or jarvis-voice.bat
pause
