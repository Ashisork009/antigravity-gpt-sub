@echo off
setlocal
title Antigravity Codex Plugin Manager
chcp 65001 >nul
set "PYTHONUTF8=1"
cd /d "%~dp0"

set "PY_EXE="
set "PY_ARGS="
set "PY_CHECK=import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)"

python -c "%PY_CHECK%" >nul 2>nul
if %ERRORLEVEL%==0 (
  set "PY_EXE=python"
  goto PY_READY
)

py -3 -c "%PY_CHECK%" >nul 2>nul
if %ERRORLEVEL%==0 (
  set "PY_EXE=py"
  set "PY_ARGS=-3"
  goto PY_READY
)

for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python3*" "%ProgramFiles%\Python3*") do (
  if exist "%%~D\python.exe" (
    "%%~D\python.exe" -c "%PY_CHECK%" >nul 2>nul
    if not errorlevel 1 set "PY_EXE=%%~D\python.exe"
  )
)
if defined PY_EXE goto PY_READY

echo [ERROR] Python 3.11+ was not found.
echo Please install Python 3.11 or newer from https://www.python.org/downloads/ and check "Add python.exe to PATH".
echo.
pause
exit /b 1

:PY_READY
"%PY_EXE%" %PY_ARGS% -B "%~dp0launcher.py" %*
set "EXIT_CODE=%ERRORLEVEL%"
if /i "%~1"=="--status" exit /b %EXIT_CODE%
echo.
if %EXIT_CODE% neq 0 (
  echo [ERROR] Operation failed with exit code %EXIT_CODE%.
  pause
  exit /b %EXIT_CODE%
)
echo Closing window in 5 seconds...
timeout /t 5 >nul 2>nul || ping -n 6 127.0.0.1 >nul
exit /b 0
