#!/bin/sh
set -e
echo "Applying Alembic migrations (PostgreSQL)..."
alembic upgrade head
echo "Starting gunicorn..."
exec gunicorn --bind 0.0.0.0:5000 --workers 2 --threads 4 --timeout 120 wsgi:application
