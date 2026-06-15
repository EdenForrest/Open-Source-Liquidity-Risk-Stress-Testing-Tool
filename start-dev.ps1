# Start both backend (FastAPI) and frontend (React Vite dev server) in parallel
# Run from project root: PowerShell -ExecutionPolicy Bypass -File start-dev.ps1

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

Write-Host "🚀 Liquidity Risk Tool — Starting backend and frontend..." -ForegroundColor Cyan
Write-Host "Project root: $ProjectRoot" -ForegroundColor Gray
Write-Host ""

# Function to cleanup processes on exit
$BackendJob = $null
$FrontendJob = $null

function Cleanup {
    Write-Host "`n⏹️  Shutting down..." -ForegroundColor Yellow

    if ($BackendJob) {
        Write-Host "Stopping backend..." -ForegroundColor Gray
        Stop-Job -Job $BackendJob -ErrorAction SilentlyContinue
        Remove-Job -Job $BackendJob -ErrorAction SilentlyContinue
    }

    if ($FrontendJob) {
        Write-Host "Stopping frontend..." -ForegroundColor Gray
        Stop-Job -Job $FrontendJob -ErrorAction SilentlyContinue
        Remove-Job -Job $FrontendJob -ErrorAction SilentlyContinue
    }

    Write-Host "Done." -ForegroundColor Cyan
    exit 0
}

# Register cleanup on script exit / Ctrl+C
$null = Register-EngineEvent -SourceIdentifier PowerShell.Exiting -Action { Cleanup }
trap { Cleanup }

# Start backend
Write-Host "▶️  Backend (FastAPI on port 8080)..." -ForegroundColor Green
$BackendJob = Start-Job -ScriptBlock {
    param($root)
    Set-Location $root
    $PythonInterp = python.exe
    if (-not (Get-Command $PythonInterp -ErrorAction SilentlyContinue)) {
        Write-Error "Python not found. Ensure Python is in PATH."
        exit 1
    }
    & $PythonInterp -m uvicorn backend.main:app --reload --port 8080
} -ArgumentList $ProjectRoot

# Wait briefly for backend to start
Start-Sleep -Seconds 3

# Start frontend
Write-Host "▶️  Frontend (Vite dev server on port 5173)..." -ForegroundColor Green
$FrontendJob = Start-Job -ScriptBlock {
    param($root)
    Set-Location "$root\frontend"
    $NodeExe = npm.cmd
    if (-not (Get-Command $NodeExe -ErrorAction SilentlyContinue)) {
        Write-Error "npm not found. Ensure Node.js is in PATH."
        exit 1
    }
    & npm run dev
} -ArgumentList $ProjectRoot

Write-Host ""
Write-Host "✅ Both services started!" -ForegroundColor Green
Write-Host ""
Write-Host "Backend:  http://localhost:8080/docs" -ForegroundColor Cyan
Write-Host "Frontend: http://localhost:5173" -ForegroundColor Cyan
Write-Host ""
Write-Host "Press Ctrl+C to stop both services." -ForegroundColor Gray
Write-Host ""

# Stream output from both jobs
while ($true) {
    $BackendMessages = Receive-Job -Job $BackendJob -ErrorAction SilentlyContinue
    if ($BackendMessages) {
        Write-Host "[Backend] $BackendMessages" -ForegroundColor White
    }

    $FrontendMessages = Receive-Job -Job $FrontendJob -ErrorAction SilentlyContinue
    if ($FrontendMessages) {
        Write-Host "[Frontend] $FrontendMessages" -ForegroundColor White
    }

    # Check if either job has failed
    if ($BackendJob.State -eq 'Failed') {
        Write-Host "❌ Backend job failed" -ForegroundColor Red
        Cleanup
    }
    if ($FrontendJob.State -eq 'Failed') {
        Write-Host "❌ Frontend job failed" -ForegroundColor Red
        Cleanup
    }

    Start-Sleep -Milliseconds 500
}
