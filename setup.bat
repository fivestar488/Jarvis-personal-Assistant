@echo off
rem One-time setup: installs Python if needed, then everything Jarvis uses, then asks for your API key.
rem The Python environment lives outside OneDrive so it doesn't get synced.
setlocal
set "VENV=%LOCALAPPDATA%\JarvisVenv"
cd /d "%~dp0"
if exist "%VENV%\Scripts\python.exe" goto packages

rem Find a Python that works (3.10-3.13). The Microsoft Store "python" shortcut doesn't count.
set PY=
for %%v in (3.12 3.13 3.11 3.10) do (
  if not defined PY ( py -%%v -c "" >nul 2>&1 && set "PY=py -%%v" )
)
if not defined PY (
  python -c "import sys; sys.exit(not (3,10) <= sys.version_info[:2] <= (3,13))" >nul 2>&1 && set "PY=python"
)
if defined PY goto venv

echo Python not found - installing Python 3.12 (about 2 minutes)...
winget install -e --id Python.Python.3.12 --scope user --silent --accept-package-agreements --accept-source-agreements
if not exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" (
  echo Downloading Python from python.org instead...
  powershell -NoProfile -Command "Invoke-WebRequest https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe -OutFile $env:TEMP\python-setup.exe"
  "%TEMP%\python-setup.exe" /quiet InstallAllUsers=0 PrependPath=1 Include_launcher=1
)
if not exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" (
  echo.
  echo Couldn't install Python automatically. Install Python 3.12 from https://www.python.org/downloads/
  echo ^(tick "Add python.exe to PATH"^), then run setup.bat again.
  pause
  exit /b 1
)
set PY="%LOCALAPPDATA%\Programs\Python\Python312\python.exe"

:venv
echo Creating Jarvis's Python environment...
%PY% -m venv "%VENV%"

:packages
echo Installing Jarvis's components (5-10 minutes the first time)...
"%VENV%\Scripts\python.exe" -m pip install --upgrade pip
"%VENV%\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
  echo.
  echo Something failed to install - check the messages above, then run setup.bat again.
  pause
  exit /b 1
)

if exist .env goto done
copy .env.example .env >nul
echo.
echo Almost done. Jarvis needs a Claude API key: https://console.anthropic.com/settings/keys
set /p "JKEY=Paste your API key and press Enter: "
set /p "JOWNER=Your name (Jarvis says he's your assistant): "
set /p "JCALL=What should Jarvis call you (e.g. sir, or your first name): "
powershell -NoProfile -Command ^
  "$l = Get-Content .env;" ^
  "function put($k, $v) { if ($v) { $script:l = $script:l -replace ('^' + $k + '=.*'), ($k + '=' + $v.Trim().Replace('$', '$$')) } }" ^
  "put 'ANTHROPIC_API_KEY' $env:JKEY; put 'JARVIS_OWNER' $env:JOWNER; put 'JARVIS_USER_NAME' $env:JCALL;" ^
  "[IO.File]::WriteAllLines((Join-Path $pwd '.env'), $l)"

:done
echo.
echo Setup done. Double-click jarvis.bat to start Jarvis. (Settings are in the .env file.)
pause
