@echo off
echo Starting Mini-OpenClaw...
echo.

REM Check for Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found. Install Python 3.11+ from python.org
    exit /b 1
)

REM Check for Node
node --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Node.js not found. Install Node.js 18+ from nodejs.org
    exit /b 1
)

REM Install Python dependencies
echo Installing Python dependencies...
pip install -r requirements.txt --quiet

REM Install Node dependencies
echo Installing Node dependencies...
cd apps\web
call npm install --silent
cd ..\..

REM Seed demo data
echo Seeding demo workspace...
python scripts\seed_demo.py

REM Start backend in background
echo Starting backend on http://localhost:8000...
start "Mini-OpenClaw Backend" cmd /c "python -m uvicorn apps.api.main:app --reload --port 8000"

REM Wait a moment for backend
timeout /t 3 >nul

REM Start frontend
echo Starting frontend on http://localhost:5173...
cd apps\web
call npm run dev
