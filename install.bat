@echo off
REM 520apkhook one-click installer (Windows)
REM
REM   install.bat                  install everything
REM   install.bat --check          diagnose only
REM   install.bat --venv --mirror aliyun
REM
REM The real work is done by install.py (Linux/macOS: bash install.sh).
REM This file stays ASCII-only on purpose: cmd.exe reads .bat in the OEM
REM code page, so non-ASCII characters here would break command parsing.

setlocal
cd /d "%~dp0"

set "PY="

py -3 -c "import sys;sys.exit(0 if sys.version_info>=(3,8) else 1)" >nul 2>nul
if not errorlevel 1 (
    set "PY=py -3"
    goto :run
)

python -c "import sys;sys.exit(0 if sys.version_info>=(3,8) else 1)" >nul 2>nul
if not errorlevel 1 (
    set "PY=python"
    goto :run
)

python3 -c "import sys;sys.exit(0 if sys.version_info>=(3,8) else 1)" >nul 2>nul
if not errorlevel 1 (
    set "PY=python3"
    goto :run
)

echo [-] Python 3.8+ not found.
echo     Install it from https://www.python.org/downloads/
echo     and tick "Add python.exe to PATH", then reopen the terminal.
exit /b 2

:run
echo [*] using %PY%
%PY% install.py %*
exit /b %errorlevel%
