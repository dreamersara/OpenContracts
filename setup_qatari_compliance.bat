@echo off
REM Qatari Commercial Law Compliance Setup Script for Windows
REM Double-click this file to set up the compliance checker

echo.
echo 🏛️  Setting up Qatari Commercial Law Compliance Checker...
echo ==================================================
echo.

REM Check if we're in the right directory
if not exist "manage.py" (
    echo ❌ Error: Please run this script from the OpenContracts root directory
    echo Current directory: %CD%
    echo Please copy this file to your OpenContracts folder and run it there
    pause
    exit /b 1
)

REM Check if Python is available
python --version >nul 2>&1
if errorlevel 1 (
    echo ❌ Error: Python not found. Please install Python first.
    pause
    exit /b 1
)

echo ✅ Found Python
echo.

REM Check if the law PDF exists
if not exist "pdf\Law-No--11-of-2015---Promulgating-the-Commercial-Companies-Law---English.pdf" (
    echo ⚠️  Warning: Qatari Commercial Law PDF not found
    echo    You can still set up the system and upload the PDF later
    echo.
)

echo 📋 Step 1: Running database migrations...
python manage.py migrate

if errorlevel 1 (
    echo ❌ Migration failed. Please check your database connection.
    echo Make sure OpenContracts is properly set up and database is running
    pause
    exit /b 1
)

echo ✅ Migrations completed
echo.

echo 🔧 Step 2: Setting up compliance system...
python manage.py setup_qatari_law_compliance

if errorlevel 1 (
    echo ❌ Setup failed. Please check the error messages above.
    pause
    exit /b 1
)

echo.
echo ✅ Setup completed successfully!
echo.
echo 🎉 QATARI COMMERCIAL LAW COMPLIANCE CHECKER IS READY!
echo ==================================================
echo.
echo 📖 What's been set up:
echo    ✓ Compliance analyzer registered
echo    ✓ Dedicated corpus created  
echo    ✓ Automatic analysis configured
echo    ✓ Reference law document uploaded (if PDF was found)
echo.
echo 🚀 Next steps:
echo    1. Start OpenContracts: docker-compose up (or your preferred method)
echo    2. Open the web interface in your browser
echo    3. Navigate to 'Qatari Commercial Law Compliance' corpus
echo    4. Upload a contract PDF
echo    5. View automatic compliance analysis results!
echo.
echo 📚 For detailed usage instructions, see:
echo    docs\qatari_law_compliance_guide.md
echo.
echo ⚖️  Legal Note: This tool provides automated analysis for informational
echo    purposes only and does not constitute legal advice.
echo.
echo Setup complete! Press any key to close...
pause >nul
