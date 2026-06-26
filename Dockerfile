# Dockerfile لـ Schedule Optimizer
# الإنتاج: Python 3.11. يُختبر في CI أيضاً 3.10 و 3.12 و 3.13 (انظر .github/workflows/ci.yml).
FROM postgres:17-bookworm AS pgclient

FROM python:3.11-slim-bookworm

LABEL maintainer="Schedule Optimizer Team"
LABEL description="Schedule Optimizer Application"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    FLASK_APP=wsgi.py \
    FLASK_ENV=production \
    PG_DUMP_PATH=/usr/local/bin/pg_dump \
    PIP_DEFAULT_TIMEOUT=180 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# pg_dump 17 من صورة postgres الرسمية (نفس glibc) — أسرع من مستودع PGDG
COPY --from=pgclient /usr/lib/postgresql/17/bin/pg_dump /usr/local/bin/pg_dump
COPY --from=pgclient /usr/lib/postgresql/17/bin/pg_restore /usr/local/bin/pg_restore

# libxml2/libxslt + gcc: wheels لـ lxml (python-pptx)؛ freetype/png لـ matplotlib
RUN apt-get update && apt-get install -y --no-install-recommends \
    wkhtmltopdf \
    xvfb \
    libpq5 \
    gcc \
    g++ \
    libxml2-dev \
    libxslt1-dev \
    zlib1g-dev \
    libfreetype6-dev \
    libpng-dev \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir lxml==5.3.1 && \
    pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p logs backups backend/database && chmod +x app.py

EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:5000/health')" || exit 1

CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "--threads", "4", "--timeout", "120", "wsgi:application"]
