# دليل Docker و CI/CD

## إصدارات Python

- **صورة Docker:** Python **3.11** (`python:3.11-slim`) — المصدر الرسمي لبيئة التشغيل المعبأة.
- **CI (GitHub Actions):** يُشغَّل الاختبارات على **3.10 و 3.11 و 3.12 و 3.13** مع نفس `requirements.txt`.
- **تطوير محلي:** يُفضّل **3.11+** لمطابقة الحاوية، أو أي إصدار ضمن مصفوفة CI. ملف `.python-version` يقترح **3.11** لأدوات مثل pyenv.

## 🐳 Docker

### بناء الصورة
```bash
docker build -t schedule-optimizer .
```

### تشغيل الحاوية (بدون Compose)
يحتاج التطبيق في الإنتاج إلى **PostgreSQL** (`DATABASE_URL`). مثال مع خادم Postgres على الشبكة نفسها:
```bash
docker run -d -p 5000:5000 \
  -e FLASK_ENV=production \
  -e ADMIN_USERNAME=admin \
  -e ADMIN_PASSWORD=your_password \
  -e SECRET_KEY=$(python -c "import secrets; print(secrets.token_hex(32))") \
  -e DATABASE_URL=postgresql+psycopg://user:pass@host:5432/schedule_optimizer \
  -v $(pwd)/logs:/app/logs \
  -v $(pwd)/backups:/app/backups \
  --name schedule-optimizer \
  schedule-optimizer
```

### استخدام Docker Compose (الأسهل — Postgres مدمج)
أنشئ ملف `.env` من `.env.example` وعيّن على الأقل: `ADMIN_USERNAME`، `ADMIN_PASSWORD`، `SECRET_KEY`، **`POSTGRES_PASSWORD`** (لخدمة `db` واتصال `web`).
```bash
# تشغيل التطبيق وقاعدة البيانات
docker compose up -d

# عرض السجلات
docker-compose logs -f

# إيقاف التطبيق
docker-compose down

# إعادة بناء الصورة
docker-compose up -d --build
```

### متغيرات البيئة في docker-compose.yml
القيم الحساسة تُقرأ من ملف `.env` (مثل `ADMIN_*`، `SECRET_KEY`، `POSTGRES_PASSWORD`). عنوان `DATABASE_URL` يُبنى تلقائياً للاتصال بخدمة `db` داخل الشبكة الداخلية.

## 🔄 CI/CD

### GitHub Actions
تم إعداد CI/CD pipeline تلقائياً في `.github/workflows/ci.yml`

#### المهام المتضمنة:
1. **Tests**: تشغيل الاختبارات على Python 3.10 و 3.11
2. **Linting**: فحص جودة الكود باستخدام flake8 و pylint
3. **Docker Build**: بناء صورة Docker واختبارها
4. **Security Scan**: فحص الأمان باستخدام Bandit

#### تشغيل CI/CD:
- يتم التشغيل تلقائياً عند:
  - Push إلى branches: `main`, `develop`
  - Pull Request إلى branches: `main`, `develop`

### تشغيل الاختبارات محلياً
```bash
# تثبيت المتطلبات
pip install -r requirements.txt

# تشغيل الاختبارات
pytest tests/ -v

# مع تقرير التغطية
pytest tests/ -v --cov=backend --cov-report=html
```

## 📊 Monitoring

### Health Check
```bash
curl http://localhost:5000/health
```

### Metrics
```bash
curl http://localhost:5000/metrics
```

### Stats
```bash
curl http://localhost:5000/stats
```

## 📝 Logging

### ملفات السجلات
- `logs/schedule_optimizer.log` - السجلات العامة
- `logs/errors.log` - الأخطاء فقط
- `logs/access.log` - طلبات HTTP
- `logs/daily.log` - سجلات يومية (تدوير يومي)

### مستويات السجلات
- **DEBUG**: معلومات تفصيلية (في وضع التطوير فقط)
- **INFO**: معلومات عامة
- **ERROR**: أخطاء فقط

## 🚀 النشر

### النشر على خادم
1. نسخ المشروع إلى الخادم
2. بناء صورة Docker
3. تشغيل باستخدام docker-compose

```bash
git clone <repository-url>
cd ScheduleOptimizer
docker-compose up -d
```

### النسخ الاحتياطي
مع Compose، بيانات PostgreSQL في Docker volume اسمه `postgres_data`. للنسخ الاحتياطي استخدم `pg_dump` من حاوية `db` أو من عميل على الخادم. مجلدا `logs/` و`backups/` يُركّبان من المضيف كما في `docker-compose.yml`.

