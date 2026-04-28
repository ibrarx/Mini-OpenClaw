# Mini-OpenClaw Windows startup script (PowerShell)

Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  Mini-OpenClaw Startup" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

# Check prerequisites
try { python --version | Out-Null } catch {
    Write-Host "ERROR: Python not found. Install Python 3.11+ from python.org" -ForegroundColor Red
    exit 1
}
try { node --version | Out-Null } catch {
    Write-Host "ERROR: Node.js not found. Install Node.js 18+ from nodejs.org" -ForegroundColor Red
    exit 1
}

if (-not (Test-Path ".env")) {
    Write-Host "ERROR: .env file not found." -ForegroundColor Red
    Write-Host "Run: copy .env.example .env" -ForegroundColor Yellow
    Write-Host "Then edit .env and add your ANTHROPIC_API_KEY." -ForegroundColor Yellow
    exit 1
}

# Install dependencies
Write-Host "Installing Python dependencies..." -ForegroundColor Yellow
pip install -r requirements.txt --quiet

Write-Host "Installing Node dependencies..." -ForegroundColor Yellow
Push-Location apps/web
npm install --silent
Pop-Location

# Seed demo data
Write-Host "Seeding demo workspace..." -ForegroundColor Yellow
python scripts/seed_demo.py

# Start backend in a new window
Write-Host "Starting backend on http://localhost:8000..." -ForegroundColor Green
Start-Process powershell -ArgumentList "-Command", "python -m uvicorn apps.api.main:app --port 8000 --reload --reload-dir apps --reload-dir scripts"

Start-Sleep -Seconds 3

# Start frontend in a new window
Write-Host "Starting frontend on http://localhost:5173..." -ForegroundColor Green
Start-Process powershell -ArgumentList "-Command", "Set-Location apps/web; npm run dev"

Write-Host ""
Write-Host "============================================" -ForegroundColor Green
Write-Host "  Mini-OpenClaw is starting!" -ForegroundColor Green
Write-Host "  Backend:  http://localhost:8000" -ForegroundColor Yellow
Write-Host "  Frontend: http://localhost:5173" -ForegroundColor Yellow
Write-Host "============================================" -ForegroundColor Green
