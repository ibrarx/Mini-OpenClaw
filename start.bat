@echo off
echo ============================================
echo   Mini-OpenClaw Startup
echo ============================================
echo.

REM Check for Python
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found. Install Python 3.11+ from python.org
    pause
    exit /b 1
)

REM Check for Node
node --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Node.js not found. Install Node.js 18+ from nodejs.org
    pause
    exit /b 1
)

REM Check for .env
if not exist .env (
    echo ERROR: .env file not found.
    echo Run: copy .env.example .env
    echo Then edit .env and add your ANTHROPIC_API_KEY.
    pause
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

REM Start backend in a new window
echo Starting backend on http://localhost:8000...
start "Mini-OpenClaw Backend" cmd /c "python -m uvicorn apps.api.main:app --port 8000 --reload --reload-dir apps --reload-dir scripts"

timeout /t 3 /nobreak >nul

REM Start frontend in a new window
echo Starting frontend on http://localhost:5173...
start "Mini-OpenClaw Frontend" cmd /c "cd apps\web && npm run dev"

echo.
echo ============================================
echo   Mini-OpenClaw is starting!
echo   Backend:  http://localhost:8000
echo   Frontend: http://localhost:5173
echo ============================================
echo.
echo Press any key to exit this window (servers keep running).
pause >nul
