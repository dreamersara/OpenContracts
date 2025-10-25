@echo off
REM Create complete .env file for OpenContracts

echo 🔧 Creating complete .env file with all required settings...
echo.

REM Create .env file with all necessary environment variables
(
echo # OpenContracts Complete Environment Configuration
echo.
echo # Database Configuration
echo DATABASE_URL=postgres://postgres:postgres@localhost:5432/opencontracts
echo.
echo # Django Settings
echo DJANGO_SETTINGS_MODULE=config.settings.local
echo DJANGO_SECRET_KEY=dev-secret-key-change-in-production
echo DJANGO_DEBUG=True
echo DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,0.0.0.0
echo.
echo # Celery Configuration
echo CELERY_BROKER_URL=redis://localhost:6379/0
echo CELERY_RESULT_BACKEND=redis://localhost:6379/0
echo.
echo # Embeddings Microservice (required^)
echo EMBEDDINGS_MICROSERVICE_URL=http://localhost:5002
echo VECTOR_EMBEDDER_API_KEY=
echo.
echo # LLM API Keys (optional - leave empty for now^)
echo ANTHROPIC_API_KEY=
echo OPENAI_API_KEY=
echo.
echo # Storage Settings
echo USE_AWS=False
echo AWS_ACCESS_KEY_ID=
echo AWS_SECRET_ACCESS_KEY=
echo AWS_STORAGE_BUCKET_NAME=
echo.
echo # Email Settings
echo EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend
echo.
echo # Security Settings
echo SECURE_SSL_REDIRECT=False
echo SECURE_HSTS_SECONDS=0
echo.
echo # Optional: Disable features that need external services
echo USE_VECTOR_EMBEDDINGS=False
echo USE_MICROSERVICE_EMBEDDER=False
) > .env

echo ✅ Created complete .env file!
echo.
echo 📋 The .env file now includes:
echo    ✓ Database settings
echo    ✓ Django configuration  
echo    ✓ Required microservice URLs
echo    ✓ API key placeholders
echo    ✓ Security settings
echo.
echo 🚀 Now try starting OpenContracts:
echo    python manage.py runserver
echo.
echo Press any key to continue...
pause >nul
