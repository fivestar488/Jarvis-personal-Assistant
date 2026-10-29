@echo off
rem Starts the Iron Man HUD. Use "jarvis.bat --text" for the terminal instead.
cd /d "%~dp0"
"%LOCALAPPDATA%\JarvisVenv\Scripts\python.exe" jarvis.py %*
pause
