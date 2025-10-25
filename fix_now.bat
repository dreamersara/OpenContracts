@echo off
echo Creating .env file...

echo USE_DOCKER=no > .env
echo DJANGO_SETTINGS_MODULE=config.settings.local >> .env
echo DJANGO_SECRET_KEY=dev-secret-key >> .env
echo DATABASE_URL=sqlite:///db.sqlite3 >> .env
echo DJANGO_DEBUG=True >> .env
echo DJANGO_ALLOWED_HOSTS=localhost >> .env
echo EMBEDDINGS_MICROSERVICE_URL=http://localhost:5002 >> .env
echo DOCLING_PARSER_SERVICE_URL=http://localhost:5001 >> .env
echo VECTOR_EMBEDDER_API_KEY=dummy >> .env
echo CELERY_BROKER_URL=memory:// >> .env
echo USE_AWS=False >> .env
echo EMAIL_BACKEND=django.core.mail.backends.console.EmailBackend >> .env
echo ANTHROPIC_API_KEY= >> .env
echo OPENAI_API_KEY= >> .env

echo .env file created!
echo Starting Django...

python manage.py migrate
python manage.py runserver 0.0.0.0:8000
