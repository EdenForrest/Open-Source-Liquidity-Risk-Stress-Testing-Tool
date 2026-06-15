@echo off
REM Start backend and frontend development servers
REM Double-click this file to launch both services

setlocal enabledelayedexpansion

REM Get the directory this batch file is in
set "ProjectRoot=%~dp0"
cd /d "%ProjectRoot%"

REM Check if Python is available
python --version >nul 2>&1
if errorlevel 1 (
    echo Error: Python not found. Please ensure Python is installed and in PATH.
    pause
    exit /b 1
)

REM Check if npm is available
npm --version >nul 2>&1
if errorlevel 1 (
    echo Error: npm not found. Please ensure Node.js is installed and in PATH.
    pause
    exit /b 1
)

echo.
echo ========================================
echo  Liquidity Risk Tool - Dev Server Start
echo ========================================
echo.
echo Starting backend (FastAPI on port 8080)...
start "Backend - FastAPI" cmd /k python -m uvicorn backend.main:app --reload --port 8080

echo Waiting 3 seconds for backend to start...
timeout /t 3 /nobreak

echo Starting frontend (Vite on port 5173)...
cd frontend
start "Frontend - React Vite" cmd /k npm run dev
cd ..

echo.
echo ========================================
echo  ✅ Both services started!
echo ========================================
echo.
echo Backend:  http://localhost:8080/docs
echo Frontend: http://localhost:5173
echo.
echo Close the command windows to stop the services.
echo.
pause
