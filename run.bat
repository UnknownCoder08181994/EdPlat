@echo off
echo ============================================
echo   AWM Institute of Technology - Launcher
echo ============================================
echo.

echo Killing any process on port 5000...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :5000 ^| findstr LISTENING') do (
    taskkill /F /PID %%a >nul 2>&1
)

if not exist venv (
    echo Creating virtual environment...
    python -m venv venv
)

call venv\Scripts\activate

echo Installing dependencies...
pip install -r requirements.txt --quiet

echo.
echo Starting AWM Institute of Technology on http://localhost:5000
echo Press Ctrl+C to stop the server.
echo.
python app.py
