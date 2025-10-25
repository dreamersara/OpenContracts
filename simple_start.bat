@echo off
REM Simple OpenContracts startup - no external services needed

echo 🚀 Simple OpenContracts Startup (Minimal Dependencies)
echo =====================================================
echo.

REM Create minimal .env file that works without external services
echo 📝 Creating minimal .env file...
(
echo # Minimal OpenContracts Configuration
echo DATABASE_URL=sqlite:///db.sqlite3
echo DJANGO_SETTINGS_MODULE=config.settings.local
echo DJANGO_SECRET_KEY=dev-secret-key-for-testing
echo DJANGO_DEBUG=True
echo DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,0.0.0.0
echo.
echo # Disable external services for now
echo EMBEDDINGS_MICROSERVICE_URL=http://localhost:5002
echo VECTOR_EMBEDDER_API_KEY=dummy
echo CELERY_BROKER_URL=memory://
echo CELERY_RESULT_BACKEND=cache+memory://
echo.
echo # Optional services - disabled
echo USE_AWS=False
echo USE_VECTOR_EMBEDDINGS=False
echo EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend
echo.
echo # API Keys - empty for now
echo ANTHROPIC_API_KEY=
echo OPENAI_API_KEY=
) > .env

echo ✅ Created minimal .env file
echo.

echo 📋 Running database setup...
python manage.py migrate

if errorlevel 1 (
    echo ❌ Migration failed. Let's try creating the database first...
    python manage.py migrate --run-syncdb
)

echo.
echo 👤 Creating superuser (optional)...
set /p create_user="Create admin user? (y/n): "
if /i "%create_user%"=="y" (
    python manage.py createsuperuser
)

echo.
echo 🚀 Starting Django server...
echo.
echo ✅ OpenContracts will be available at: http://localhost:8000
echo.
echo 📝 Note: This is a minimal setup. Some features may not work without:
echo    - PostgreSQL database
echo    - Redis for Celery
echo    - Embeddings microservice
echo.
echo 🎯 But you can still:
echo    - Upload documents
echo    - View and annotate PDFs
echo    - Use basic document management
echo.
echo Starting server now...
python manage.py runserver 0.0.0.0:8000
