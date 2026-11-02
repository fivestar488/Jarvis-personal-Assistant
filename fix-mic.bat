@echo off
rem Checks and fixes the settings Jarvis's microphone needs.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File fix-mic.ps1 %*
pause
