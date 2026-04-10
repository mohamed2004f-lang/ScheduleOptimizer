# Alembic وقاعدة البيانات

## المتغيرات

- **`DATABASE_URL`**: عنوان SQLAlchemy الموحّد.
  - تطوير (SQLite): `sqlite:///backend/database/mechanical.db` أو مسار مطلق.
  - إنتاج (PostgreSQL): `postgresql+psycopg://USER:PASS@HOST:5432/DBNAME`
- **`DATABASE_PATH`**: مسار ملف SQLite (توافق خلفي؛ يُستخدم عند عدم ضبط `DATABASE_URL` في `config.py`).

## الأوامر

```bash
# ترقية إلى آخر إصدار
alembic upgrade head

# إنشاء ترحيل جديد (بعد تعديل المخطط)
alembic revision -m "describe change"
```

## ملاحظات

- التطبيق يستخدم **`sqlite3`** في وقت التشغيل مع SQLite. راجع `docs/POSTGRES_MIGRATION.md` لخطة الانتقال الكاملة.
- الترحيلات عبر Alembic يمكنها تطبيق المخطط على PostgreSQL (انظر `0001_baseline`).
- ترحيل `0001_baseline` على PostgreSQL يطبّق DDL مُحوَّلاً من تعريفات SQLite؛ راجع أي اختلافات نوعية عند أول نشر على الإنتاج.
