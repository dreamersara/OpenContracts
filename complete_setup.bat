@echo off
REM Complete OpenContracts + Qatari Law Compliance Setup

echo.
echo 🚀 Complete OpenContracts + Qatari Law Compliance Setup
echo =====================================================
echo.

REM Check if we're in the right directory
if not exist "manage.py" (
    echo ❌ Error: Please run this script from the OpenContracts root directory
    pause
    exit /b 1
)

echo 📦 Step 1: Installing Python dependencies...
echo This may take a few minutes...
pip install -r requirements/local.txt

if errorlevel 1 (
    echo ❌ Failed to install dependencies. Trying with virtual environment...
    echo.
    echo 🔧 Creating virtual environment...
    python -m venv venv
    
    echo 🔧 Activating virtual environment...
    call venv\Scripts\activate.bat
    
    echo 📦 Installing dependencies in virtual environment...
    pip install -r requirements/local.txt
    
    if errorlevel 1 (
        echo ❌ Installation failed. Please check your Python setup.
        pause
        exit /b 1
    )
)

echo ✅ Dependencies installed successfully!
echo.

echo 🗄️ Step 2: Setting up database...
echo Checking if Docker is available...

docker --version >nul 2>&1
if errorlevel 1 (
    echo ⚠️  Docker not found. You'll need to set up PostgreSQL manually.
    echo Please install PostgreSQL and create a database for OpenContracts.
    echo Then update your .env file with database settings.
    echo.
    echo Press any key to continue with Django setup...
    pause >nul
) else (
    echo ✅ Docker found. Starting PostgreSQL...
    docker-compose -f local.yml up postgres -d
    
    echo ⏳ Waiting for database to start...
    timeout /t 10 /nobreak >nul
)

echo.
echo 📋 Step 3: Running Django migrations...
python manage.py migrate

if errorlevel 1 (
    echo ❌ Migration failed. Database might not be ready yet.
    echo Please check:
    echo 1. PostgreSQL is running
    echo 2. Database connection settings in .env file
    echo 3. Try running: docker-compose -f local.yml up postgres -d
    pause
    exit /b 1
)

echo ✅ Database setup complete!
echo.

echo 🏛️ Step 4: Setting up Qatari Law Compliance...
python manage.py setup_qatari_law_compliance

if errorlevel 1 (
    echo ❌ Compliance setup failed. Please check the error messages above.
    pause
    exit /b 1
)

echo.
echo 🎉 COMPLETE SETUP FINISHED!
echo ========================
echo.
echo ✅ OpenContracts is now ready with Qatari Law Compliance!
echo.
echo 🚀 To start OpenContracts:
echo    docker-compose -f local.yml up
echo.
echo 🌐 Then open your browser to:
echo    http://localhost:3000
echo.
echo 📚 Usage guide:
echo    docs\qatari_law_compliance_guide.md
echo.
echo Press any key to exit...
pause >nul
