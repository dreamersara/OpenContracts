@echo off
REM Start OpenContracts without Docker

echo 🚀 Starting OpenContracts (No Docker Version)
echo ===============================================
echo.

REM Check if we're in the right directory
if not exist "manage.py" (
    echo ❌ Error: Please run this script from the OpenContracts root directory
    pause
    exit /b 1
)

echo 📋 Step 1: Starting Django backend...
echo Backend will run on http://localhost:8000
echo.

REM Start Django in background
start "Django Backend" cmd /k "python manage.py runserver 0.0.0.0:8000"

echo ⏳ Waiting for backend to start...
timeout /t 5 /nobreak >nul

echo 📦 Step 2: Checking Node.js...
node --version >nul 2>&1
if errorlevel 1 (
    echo ❌ Node.js not found. Please install Node.js from https://nodejs.org
    echo After installing Node.js, run this script again.
    pause
    exit /b 1
)

echo ✅ Node.js found
echo.

echo 🎨 Step 3: Starting React frontend...
echo Frontend will run on http://localhost:3000
echo.

REM Navigate to frontend and start
cd frontend

REM Install dependencies if needed
if not exist "node_modules" (
    echo 📦 Installing frontend dependencies (first time)...
    npm install
)

REM Start frontend
start "React Frontend" cmd /k "npm start"

echo.
echo 🎉 OpenContracts is starting!
echo ============================
echo.
echo ✅ Backend: http://localhost:8000
echo ✅ Frontend: http://localhost:3000
echo.
echo 🌐 Open your browser to: http://localhost:3000
echo.
echo 📝 Note: Two command windows will open:
echo    - One for Django backend
echo    - One for React frontend
echo.
echo ⚠️  Keep both windows open while using OpenContracts
echo.
echo Press any key to exit this window...
pause >nul

