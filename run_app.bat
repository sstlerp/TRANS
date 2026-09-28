@echo off
REM ==========================================================================
REM  TRANS ERP - start the application on Windows
REM
REM  Double-click this file, or run from Command Prompt:
REM      run_app.bat            start on port 8000
REM      run_app.bat 8080       start on another port
REM
REM  First run: creates the Python environment, installs packages, asks for
REM  the MySQL login, creates database ERP_LOGISTICS + all tables, loads the
REM  starting data. Later runs: applies any new migrations and starts the app.
REM ==========================================================================
setlocal
cd /d "%~dp0"
title TRANS ERP
set "PORT=%~1"
if "%PORT%"=="" set "PORT=8000"

echo.
echo ===============================================
echo    TRANS ERP - Transport and Logistics ERP
echo ===============================================

REM ---- 1. find Python ------------------------------------------------------
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if not defined PY goto :nopython

REM ---- 2. virtual environment ---------------------------------------------
if exist ".venv\Scripts\python.exe" goto :venv_ok
echo [1/6] Creating Python environment .venv ...
%PY% -m venv .venv
if errorlevel 1 goto :fail
:venv_ok
set "VPY=.venv\Scripts\python.exe"

REM ---- 3. packages (reinstalled only when requirements.txt changes) ------------
fc /b requirements.txt ".venv\requirements.installed" >nul 2>nul
if not errorlevel 1 goto :packages_ok
echo [2/6] Installing packages - this takes a few minutes the first time ...
"%VPY%" -m pip install --upgrade pip >nul
"%VPY%" -m pip install -r requirements.txt
if errorlevel 1 goto :fail
copy /y requirements.txt ".venv\requirements.installed" >nul
:packages_ok

REM ---- 4. settings file ---------------------------------------------------
if exist ".env" goto :env_ok
echo [3/6] First-time settings ...
"%VPY%" scripts\make_env.py
if errorlevel 1 goto :fail
:env_ok
if not exist storage mkdir storage
if not exist logs mkdir logs

echo [4/6] Checking MySQL connection ...
"%VPY%" scripts\make_env.py --check-db
if errorlevel 1 goto :fail

REM ---- 5. database + tables (creates ERP_LOGISTICS if missing) ------------
echo [5/6] Creating / updating database tables ...
"%VPY%" -m alembic upgrade head
if errorlevel 1 goto :fail

REM ---- 6. starting data (first run only) ----------------------------------
if exist "storage\.seeded" goto :seed_ok
echo [6/6] Loading starting data - roles, admin user, lists, templates ...
choice /c YN /m "Also load DEMO data - sample vehicles, drivers, tyres"
if errorlevel 2 (
    "%VPY%" -m app.seed
) else (
    "%VPY%" -m app.seed --demo
)
if errorlevel 1 goto :fail
echo seeded> "storage\.seeded"
:seed_ok

echo.
echo  App address : http://localhost:%PORT%
echo  API docs    : http://localhost:%PORT%/docs
echo  First login : admin / Admin@12345  - you will be asked to change it
echo  Keep this window open. Press Ctrl+C to stop the app.
echo.
start "" cmd /c "timeout /t 5 /nobreak >nul & start http://localhost:%PORT%"
"%VPY%" -m uvicorn app.main:app --host 0.0.0.0 --port %PORT%
goto :end

:nopython
echo.
echo  Python 3.11+ was not found. Install it from https://www.python.org/downloads/
echo  and tick "Add Python to PATH" during installation, then run this file again.
goto :end

:fail
echo.
echo  *** Something went wrong - see the messages above. ***
echo  Logs are in the "logs" folder. Fix the problem and run this file again.

:end
echo.
pause
endlocal
