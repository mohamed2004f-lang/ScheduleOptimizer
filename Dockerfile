# Dockerfile لـ Schedule Optimizer
# الإنتاج: Python 3.11. يُختبر في CI أيضاً 3.10 و 3.12 و 3.13 (انظر .github/workflows/ci.yml).
FROM python:3.11-slim

# تعيين معلومات الصيانة
LABEL maintainer="Schedule Optimizer Team"
LABEL description="Schedule Optimizer Application"

# تعيين متغيرات البيئة
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    FLASK_APP=wsgi.py \
    FLASK_ENV=production

# إنشاء مجلد العمل
WORKDIR /app

# تثبيت التبعيات النظامية
RUN apt-get update && apt-get install -y --no-install-recommends \
    wkhtmltopdf \
    xvfb \
    && rm -rf /var/lib/apt/lists/*

# نسخ ملف المتطلبات وتثبيت التبعيات
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# نسخ الكود
COPY . .

# إنشاء المجلدات المطلوبة
RUN mkdir -p logs backups backend/database

# تعيين الصلاحيات
RUN chmod +x app.py

# فتح المنفذ
EXPOSE 5000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:5000/health')" || exit 1

# تشغيل الإنتاج عبر Gunicorn (لا تعتمد على app.run)
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "--threads", "4", "--timeout", "120", "wsgi:application"]

