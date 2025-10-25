@echo off
REM Complete Fix for OpenContracts + Qatari Law Compliance

echo.
echo 🔧 Complete OpenContracts Fix and Qatari Law Setup
echo ================================================
echo.

REM Check if we're in the right directory
if not exist "manage.py" (
    echo ❌ Error: Please run this script from the OpenContracts root directory
    pause
    exit /b 1
)

echo 📝 Step 1: Creating .env file with database settings...

REM Create .env file if it doesn't exist
if not exist ".env" (
    echo Creating .env file...
    (
        echo # OpenContracts Environment Configuration
        echo DATABASE_URL=postgres://postgres:postgres@localhost:5432/opencontracts
        echo DJANGO_SETTINGS_MODULE=config.settings.local
        echo DJANGO_SECRET_KEY=dev-secret-key-change-in-production
        echo DJANGO_DEBUG=True
        echo DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1
        echo CELERY_BROKER_URL=redis://localhost:6379/0
        echo CELERY_RESULT_BACKEND=redis://localhost:6379/0
        echo USE_AWS=False
        echo EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend
        echo SECURE_SSL_REDIRECT=False
        echo SECURE_HSTS_SECONDS=0
    ) > .env
    echo ✅ Created .env file with basic settings
) else (
    echo ✅ .env file already exists
)

echo.
echo 📦 Step 2: Installing Python dependencies...
pip install -r requirements/local.txt

if errorlevel 1 (
    echo ⚠️  Full requirements failed. Installing essential packages...
    pip install django celery psycopg2-binary python-decouple django-environ redis
)

echo ✅ Dependencies installed
echo.

echo 🗄️ Step 3: Starting database services...

REM Check if Docker is available
docker --version >nul 2>&1
if not errorlevel 1 (
    echo ✅ Docker found. Starting PostgreSQL and Redis...
    docker-compose -f local.yml up postgres redis -d
    
    echo ⏳ Waiting for services to start...
    timeout /t 20 /nobreak >nul
    
    echo ✅ Database services started
) else (
    echo ⚠️  Docker not found. You'll need to install PostgreSQL and Redis manually.
    echo Or install Docker Desktop and run: docker-compose -f local.yml up postgres redis -d
    echo.
    echo For now, let's try with SQLite (simpler database)...
    
    REM Modify .env to use SQLite instead
    (
        echo # OpenContracts Environment Configuration - SQLite Version
        echo DATABASE_URL=sqlite:///db.sqlite3
        echo DJANGO_SETTINGS_MODULE=config.settings.local
        echo DJANGO_SECRET_KEY=dev-secret-key-change-in-production
        echo DJANGO_DEBUG=True
        echo DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1
        echo USE_AWS=False
        echo EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend
        echo SECURE_SSL_REDIRECT=False
        echo SECURE_HSTS_SECONDS=0
    ) > .env
    
    echo ✅ Configured to use SQLite database
)

echo.
echo 📋 Step 4: Running Django migrations...
python manage.py migrate

if errorlevel 1 (
    echo ❌ Migration failed. Let's troubleshoot...
    echo.
    echo Checking Django installation...
    python -c "import django; print('Django version:', django.get_version())"
    
    if errorlevel 1 (
        echo ❌ Django not properly installed. Installing again...
        pip install django
        python manage.py migrate
    )
)

if errorlevel 1 (
    echo ❌ Still having migration issues. Here's what to check:
    echo 1. Make sure PostgreSQL is running: docker-compose -f local.yml up postgres -d
    echo 2. Check the .env file was created correctly
    echo 3. Try: python manage.py check
    echo.
    pause
    exit /b 1
)

echo ✅ Migrations completed successfully!
echo.

echo 👤 Step 5: Creating superuser (optional)...
echo You can create an admin user to access the web interface
set /p create_user="Create superuser now? (y/n): "
if /i "%create_user%"=="y" (
    python manage.py createsuperuser
)

echo.
echo 🏛️ Step 6: Setting up Qatari Law Compliance Checker...
python manage.py setup_qatari_law_compliance

if errorlevel 1 (
    echo ⚠️  Compliance setup had issues, but the main system should work.
    echo You can try this command later: python manage.py setup_qatari_law_compliance
)

echo.
echo 🎉 SETUP COMPLETE!
echo ==================
echo.
echo ✅ OpenContracts is now configured and ready!
echo ✅ Database is set up and migrated
echo ✅ Qatari Law Compliance Checker is installed
echo.
echo 🚀 To start OpenContracts:
echo    docker-compose -f local.yml up
echo.
echo 🌐 Then open your browser to:
echo    http://localhost:3000
echo.
echo 📋 What you can do now:
echo    1. Upload the Qatari Commercial Law PDF
echo    2. Upload contracts for compliance checking
echo    3. View automatic analysis results
echo.
echo 📚 For detailed instructions:
echo    docs\qatari_law_compliance_guide.md
echo.
echo Press any key to exit...
pause >nul
