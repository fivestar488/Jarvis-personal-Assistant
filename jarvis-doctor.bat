@echo off
rem Setup doctor: checks everything Jarvis needs (mic, speakers, API key, Google, phone link...) and says how to fix
rem anything that is wrong, in plain English. It changes nothing.
cd /d "%~dp0"
if not exist "%LOCALAPPDATA%\JarvisVenv\Scripts\python.exe" (
  echo Jarvis is not installed yet. Double-click setup.bat first.
  pause
  exit /b 1
)
"%LOCALAPPDATA%\JarvisVenv\Scripts\python.exe" -m jarvis.doctor
pause
