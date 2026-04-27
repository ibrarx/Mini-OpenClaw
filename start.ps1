# Mini-OpenClaw Windows Startup Script (PowerShell)
# This installs dependencies and starts both backend and frontend.

Write-Host "=== Mini-OpenClaw Setup ===" -ForegroundColor Cyan

Write-Host "`nInstalling Python dependencies..."
pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Failed to install Python dependencies." -ForegroundColor Red
    exit 1
}

Write-Host "`nInstalling Node dependencies..."
Push-Location apps/web
npm install
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Failed to install Node dependencies." -ForegroundColor Red
    Pop-Location
    exit 1
}
Pop-Location

Write-Host "`n=== Starting Mini-OpenClaw ===" -ForegroundColor Cyan
Write-Host "Starting backend on http://localhost:8000 ..."
Start-Process -NoNewWindow powershell -ArgumentList "-Command", "cd apps/api; python -m uvicorn main:app --reload --port 8000"

Write-Host "Starting frontend on http://localhost:5173 ..."
Start-Process -NoNewWindow powershell -ArgumentList "-Command", "cd apps/web; npm run dev"

Write-Host "`nBoth servers starting. Open http://localhost:5173 in your browser." -ForegroundColor Green
Write-Host "Press Ctrl+C to stop."
Read-Host "Press Enter to exit"
