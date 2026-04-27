@echo off
REM Mini-OpenClaw Windows Startup Script (CMD)
REM This installs dependencies and starts both backend and frontend.

echo === Mini-OpenClaw Setup ===

echo.
echo Installing Python dependencies...
pip install -r requirements.txt
if %ERRORLEVEL% neq 0 (
    echo ERROR: Failed to install Python dependencies.
    pause
    exit /b 1
)

echo.
echo Installing Node dependencies...
cd apps\web
call npm install
if %ERRORLEVEL% neq 0 (
    echo ERROR: Failed to install Node dependencies.
    pause
    exit /b 1
)
cd ..\..

echo.
echo === Starting Mini-OpenClaw ===
echo Starting backend on http://localhost:8000 ...
start "Mini-OpenClaw Backend" cmd /c "cd apps\api && python -m uvicorn main:app --reload --port 8000"

echo Starting frontend on http://localhost:5173 ...
start "Mini-OpenClaw Frontend" cmd /c "cd apps\web && npm run dev"

echo.
echo Both servers starting. Open http://localhost:5173 in your browser.
echo Close this window or press Ctrl+C to stop.
pause
