# Mini-OpenClaw Windows startup script (PowerShell)

Write-Host "Starting Mini-OpenClaw..." -ForegroundColor Cyan

# Check prerequisites
try { python --version | Out-Null } catch {
    Write-Host "ERROR: Python not found. Install Python 3.11+ from python.org" -ForegroundColor Red
    exit 1
}
try { node --version | Out-Null } catch {
    Write-Host "ERROR: Node.js not found. Install Node.js 18+ from nodejs.org" -ForegroundColor Red
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

# Start backend
Write-Host "Starting backend on http://localhost:8000..." -ForegroundColor Green
Start-Process -NoNewWindow powershell -ArgumentList "-Command", "python -m uvicorn apps.api.main:app --reload --port 8000 --reload-dir apps --reload-dir scripts --reload-exclude 'workspace/*' --reload-exclude '*.db' --reload-exclude '*.db-journal' --reload-exclude 'exports/*'"

Start-Sleep -Seconds 3

# Start frontend
Write-Host "Starting frontend on http://localhost:5173..." -ForegroundColor Green
Push-Location apps/web
npm run dev
