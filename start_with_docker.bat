@echo off
echo 🐳 Starting OpenContracts with Docker
echo ===================================
echo.

REM Check if Docker is installed
docker --version >nul 2>&1
if errorlevel 1 (
    echo ❌ Docker not found. Please install Docker Desktop first:
    echo    https://www.docker.com/products/docker-desktop
    pause
    exit /b 1
)

echo ✅ Docker found
echo.

echo 📋 Step 1: Running database migrations...
docker-compose -f local.yml --profile migrate up migrate

if errorlevel 1 (
    echo ⚠️  Migration profile not available. Running regular migrations...
    docker-compose -f local.yml up postgres -d
    timeout /t 10 /nobreak >nul
    docker-compose -f local.yml run --rm django python manage.py migrate
)

echo.
echo 🚀 Step 2: Starting all OpenContracts services...
echo This will start:
echo   - PostgreSQL database
echo   - Redis cache
echo   - Django backend
echo   - React frontend
echo   - Celery workers
echo.

docker-compose -f local.yml up

echo.
echo 🎉 OpenContracts should now be running!
echo.
echo 🌐 Open your browser to:
echo    Frontend: http://localhost:3000
echo    Backend:  http://localhost:8000
echo.
echo 📝 To stop all services, press Ctrl+C
echo    Or run: docker-compose -f local.yml down
