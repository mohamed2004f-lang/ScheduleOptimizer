# نشر ScheduleOptimizer — دليل مختصر

## A) تجربة بدون domain (ابدأ هنا)

### على Windows (جهازك أو سيرفر الكلية)

```powershell
cd ScheduleOptimizer
copy .env.example .env
# عبّئ: SECRET_KEY, ADMIN_PASSWORD, DATABASE_URL (PostgreSQL محلي)

docker compose up -d --build
# أو بدون Docker: python scripts/run_waitress.py
```

- داخل الشبكة: `http://IP-السيرفر:5000`
- من نفس الجهاز: `http://127.0.0.1:5000/health`

**اختبار دعوة خارجية مؤقت (4G):**

```powershell
# ثبّت cloudflared، ثم:
cloudflared tunnel --url http://127.0.0.1:5000
```

استخدم الرابط المؤقت لاختبار `/academic_quality/surveys/invite/TOKEN` — **ليس للحملة الرسمية**.

---

## B) نشر إنتاج (Docker + PostgreSQL)

### 1. `.env` (إلزامي)

```env
FLASK_ENV=production
FLASK_DEBUG=0
SECRET_KEY=<python -c "import secrets; print(secrets.token_hex(32))">
ADMIN_USERNAME=admin-mohamed
ADMIN_PASSWORD=<قوية>
POSTGRES_PASSWORD=<قوية>
WEB_BIND=127.0.0.1
```

مع Compose لا تحتاج `DATABASE_URL` — يُبنى تلقائياً.

### 2. نقل البيانات

**على جهاز التطوير:**

```powershell
python scripts/pg_dump_via_env.py
# الملف في backups/pg_dump/
# انسخ أيضاً: backend\uploads\
```

**على السيرفر (Linux):**

```bash
docker compose up -d db
# بعد healthy:
docker compose exec -T db pg_restore -U schedule -d schedule_optimizer -c --if-exists < backups/pg_dump/your.dump
# أو من المضيف: pg_restore -h localhost -U schedule -d schedule_optimizer -c backups/pg_dump/your.dump
```

انسخ مجلد `backend/uploads/` إلى نفس المسار على السيرفر (يُركّب تلقائياً في الحاوية عبر `docker-compose.yml`).

### 3. تشغيل

```bash
docker compose up -d --build
curl http://127.0.0.1:5000/health
```

### 4. HTTPS (بعد شراء domain)

```bash
# عدّل deploy/Caddyfile → اسم نطاقكم
docker compose -f docker-compose.yml -f deploy/docker-compose.caddy.yml up -d --build
```

أو nginx: `deploy/nginx.conf.example`

---

## C) نسخ احتياطي يومي

```bash
python scripts/pg_dump_via_env.py
# + نسخ backend/uploads
```

Windows: `scripts\backup_db_daily.bat`

---

## D) قائمة تحقق

- [ ] `FLASK_ENV=production`
- [ ] بيانات مستعادة + uploads
- [ ] `/health` يعمل
- [ ] HTTPS (443) قبل الدعوات الخارجية
- [ ] كلمات مرور المستخدمين مُحدَّثة
- [ ] Postgres غير مفتوح للإنترنت
