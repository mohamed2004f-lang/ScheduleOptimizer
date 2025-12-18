# دليل Docker و CI/CD

## 🐳 Docker

### بناء الصورة
```bash
docker build -t schedule-optimizer .
```

### تشغيل الحاوية
```bash
docker run -d -p 5000:5000 \
  -e ADMIN_USERNAME=admin \
  -e ADMIN_PASSWORD=your_password \
  -v $(pwd)/backend/database:/app/backend/database \
  -v $(pwd)/logs:/app/logs \
  --name schedule-optimizer \
  schedule-optimizer
```

### استخدام Docker Compose (الأسهل)
```bash
# تشغيل التطبيق
docker-compose up -d

# عرض السجلات
docker-compose logs -f

# إيقاف التطبيق
docker-compose down

# إعادة بناء الصورة
docker-compose up -d --build
```

### متغيرات البيئة في docker-compose.yml
يمكنك تعديل المتغيرات في ملف `docker-compose.yml`:
```yaml
environment:
  - ADMIN_USERNAME=admin
  - ADMIN_PASSWORD=your_password
  - SECRET_KEY=your-secret-key
```

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
قاعدة البيانات محفوظة في `backend/database/` ويمكن نسخها احتياطياً بسهولة.

