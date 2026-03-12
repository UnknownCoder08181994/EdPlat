@echo off
REM =========================================================================
REM  Sentinel — One-Click Launcher
REM  Creates venv if needed, installs dependencies, starts the server.
REM  Requires LLM server running at localhost:1234.
REM =========================================================================
title Sentinel — Server
setlocal enabledelayedexpansion

set "ROOT=%~dp0"
set "BACKEND=%ROOT%backend"
set "VENV=%BACKEND%\venv"
set "PYTHON=%VENV%\Scripts\python.exe"
set "PIP=%VENV%\Scripts\pip.exe"

echo.
echo ===================================================
echo   Sentinel Server Launcher
echo ===================================================
echo.

REM --- Step 1: Check LLM server ---
echo [1/5] Checking LLM server at localhost:1234...
curl -s http://localhost:1234/v1/models >nul 2>&1
if errorlevel 1 (
    echo.
    echo  *** WARNING: LLM server not reachable at localhost:1234 ***
    echo  Make sure LLM server is running with a model loaded.
    echo  The server will start but LLM calls will fail until LLM server is up.
    echo.
)

REM --- Step 2: Create venv if it doesn't exist ---
echo.
echo [2/5] Checking Python virtual environment...
if not exist "%PYTHON%" (
    echo  Creating venv at %VENV%...
    python -m venv "%VENV%"
    if errorlevel 1 (
        echo  *** FATAL: Failed to create venv. Is Python 3.10+ installed? ***
        pause
        exit /b 1
    )
    echo  venv created.
) else (
    echo  venv exists.
)

REM --- Step 3: Install dependencies ---
echo.
echo [3/5] Installing dependencies...
"%PIP%" install -q -r "%ROOT%requirements.txt"
if errorlevel 1 (
    echo  *** WARNING: Some dependencies may have failed. Continuing... ***
)

REM --- Step 4: Kill anything on port 5000 ---
echo.
echo [4/5] Freeing port 5000...
for /f "tokens=5" %%p in ('netstat -aon ^| findstr ":5000 " ^| findstr "LISTENING"') do (
    echo  Killing PID %%p on port 5000...
    taskkill /F /PID %%p >nul 2>&1
)

REM --- Step 5: Launch the server ---
echo.
echo [5/5] Starting Sentinel server...
echo ===================================================
echo   Server: http://localhost:5000
echo   LLM:    LLM server at localhost:1234
echo   Press Ctrl+C to stop
echo ===================================================
echo.
cd /d "%BACKEND%"
"%PYTHON%" app.py

REM If server exits, pause so user can see errors
echo.
echo Server stopped.
pause
