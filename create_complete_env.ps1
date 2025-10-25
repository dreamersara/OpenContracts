# Complete OpenContracts .env file creator
# This PowerShell script creates a .env file with ALL required environment variables

Write-Host "🔧 Creating COMPLETE .env file for OpenContracts..." -ForegroundColor Green

$envContent = @"
# OpenContracts Complete Environment Configuration
# This file contains ALL environment variables needed to run OpenContracts

# Core Django Settings
DJANGO_SETTINGS_MODULE=config.settings.local
DJANGO_SECRET_KEY=dev-secret-key-change-in-production
DJANGO_DEBUG=True
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1,0.0.0.0

# Database Configuration
DATABASE_URL=sqlite:///db.sqlite3

# Docker Configuration
USE_DOCKER=no

# Microservice URLs
EMBEDDINGS_MICROSERVICE_URL=http://localhost:5002
DOCLING_PARSER_SERVICE_URL=http://localhost:5001
NLM_INGEST_PARSER_SERVICE_URL=http://localhost:5003

# API Keys and Authentication
VECTOR_EMBEDDER_API_KEY=dummy-key
ANTHROPIC_API_KEY=
OPENAI_API_KEY=

# Celery Configuration
CELERY_BROKER_URL=memory://
CELERY_RESULT_BACKEND=cache+memory://

# Storage Configuration
USE_AWS=False
AWS_ACCESS_KEY_ID=
AWS_SECRET_ACCESS_KEY=
AWS_STORAGE_BUCKET_NAME=
AWS_S3_REGION_NAME=us-east-1

# Email Configuration
EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend
EMAIL_HOST=
EMAIL_PORT=587
EMAIL_USE_TLS=True
EMAIL_HOST_USER=
EMAIL_HOST_PASSWORD=

# Security Settings
SECURE_SSL_REDIRECT=False
SECURE_HSTS_SECONDS=0
SECURE_HSTS_INCLUDE_SUBDOMAINS=False
SECURE_HSTS_PRELOAD=False
SECURE_CONTENT_TYPE_NOSNIFF=True
SECURE_BROWSER_XSS_FILTER=True
SESSION_COOKIE_SECURE=False
CSRF_COOKIE_SECURE=False

# Redis Configuration (if not using memory)
REDIS_URL=redis://localhost:6379/0

# Logging
DJANGO_LOG_LEVEL=INFO

# Feature Flags
USE_VECTOR_EMBEDDINGS=False
USE_MICROSERVICE_EMBEDDER=False
ENABLE_CORPUS_ACTIONS=True

# Parser Configuration
DEFAULT_PARSER=opencontractserver.pipeline.parsers.oc_text_parser.TxtParser

# Frontend Configuration
FRONTEND_URL=http://localhost:3000

# Webhook Configuration
WEBHOOK_SECRET=

# Rate Limiting
ENABLE_RATELIMIT=False

# Analytics
ENABLE_ANALYTICS=False
GOOGLE_ANALYTICS_ID=

# Sentry (Error Tracking)
SENTRY_DSN=

# Additional Optional Settings
TIME_ZONE=UTC
LANGUAGE_CODE=en-us
USE_I18N=True
USE_L10N=True
USE_TZ=True

# File Upload Settings
FILE_UPLOAD_MAX_MEMORY_SIZE=26214400
DATA_UPLOAD_MAX_MEMORY_SIZE=26214400

# Session Configuration
SESSION_ENGINE=django.contrib.sessions.backends.db
SESSION_COOKIE_AGE=1209600

# CORS Settings (if needed)
CORS_ALLOW_ALL_ORIGINS=True
CORS_ALLOWED_ORIGINS=http://localhost:3000,http://127.0.0.1:3000

# Additional Django Settings
APPEND_SLASH=True
PREPEND_WWW=False
"@

# Write the .env file
$envContent | Out-File -FilePath ".env" -Encoding UTF8 -NoNewline

Write-Host "✅ Complete .env file created successfully!" -ForegroundColor Green
Write-Host ""
Write-Host "📋 The .env file includes:" -ForegroundColor Cyan
Write-Host "   ✓ All required Django settings" -ForegroundColor Green
Write-Host "   ✓ Database configuration (SQLite)" -ForegroundColor Green
Write-Host "   ✓ All microservice URLs" -ForegroundColor Green
Write-Host "   ✓ Security settings" -ForegroundColor Green
Write-Host "   ✓ Feature flags (disabled for simplicity)" -ForegroundColor Green
Write-Host "   ✓ USE_DOCKER=no (for local development)" -ForegroundColor Green
Write-Host ""
Write-Host "🚀 Now try starting OpenContracts:" -ForegroundColor Yellow
Write-Host "   python manage.py runserver" -ForegroundColor White
Write-Host ""
Write-Host "Press any key to continue..." -ForegroundColor Gray
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
