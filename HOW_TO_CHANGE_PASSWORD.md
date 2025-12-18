# كيفية تعديل اسم المستخدم وكلمة المرور

هناك **ثلاث طرق** لتعديل اسم المستخدم وكلمة المرور:

## الطريقة 1: تعديل ملف config.py (الأسهل) ⭐

1. افتح ملف `config.py` في المجلد الرئيسي للمشروع
2. عدّل القيم التالية:
   ```python
   ADMIN_USERNAME = 'اسم_المستخدم_الجديد'
   ADMIN_PASSWORD = 'كلمة_المرور_الجديدة'
   ```
3. احفظ الملف
4. أعد تشغيل التطبيق

**مثال:**
```python
ADMIN_USERNAME = 'manager'
ADMIN_PASSWORD = 'MySecurePassword123!'
```

---

## الطريقة 2: استخدام متغيرات البيئة

### في Windows PowerShell:
```powershell
$env:ADMIN_USERNAME="اسم_المستخدم"
$env:ADMIN_PASSWORD="كلمة_المرور"
python app.py
```

### في Windows CMD:
```cmd
set ADMIN_USERNAME=اسم_المستخدم
set ADMIN_PASSWORD=كلمة_المرور
python app.py
```

### في Linux/Mac:
```bash
export ADMIN_USERNAME="اسم_المستخدم"
export ADMIN_PASSWORD="كلمة_المرور"
python app.py
```

---

## الطريقة 3: تعديل الكود مباشرة

1. افتح ملف `backend/core/auth.py`
2. ابحث عن السطور:
   ```python
   DEFAULT_USERNAME = os.environ.get('ADMIN_USERNAME', 'admin')
   DEFAULT_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'admin123')
   ```
3. عدّل القيم الافتراضية:
   ```python
   DEFAULT_USERNAME = os.environ.get('ADMIN_USERNAME', 'اسم_المستخدم_الجديد')
   DEFAULT_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'كلمة_المرور_الجديدة')
   ```
4. احفظ الملف
5. أعد تشغيل التطبيق

---

## ملاحظات مهمة:

1. **بعد أي تعديل، يجب إعادة تشغيل التطبيق** حتى يتم تطبيق التغييرات
2. **الأولوية:** ملف config.py > متغيرات البيئة > القيم الافتراضية في الكود
3. **الأمان:** يُنصح بشدة بتغيير كلمة المرور الافتراضية `admin123` في بيئة الإنتاج
4. **قوة كلمة المرور:** استخدم كلمة مرور قوية تحتوي على:
   - 8 أحرف على الأقل
   - مزيج من الأحرف الكبيرة والصغيرة
   - أرقام
   - رموز خاصة (!@#$%^&*)

---

## مثال عملي:

لنفترض أنك تريد تغيير:
- اسم المستخدم إلى: `administrator`
- كلمة المرور إلى: `SecurePass2024!`

### باستخدام config.py:
1. افتح `config.py`
2. عدّل:
   ```python
   ADMIN_USERNAME = 'administrator'
   ADMIN_PASSWORD = 'SecurePass2024!'
   ```
3. احفظ وأعد تشغيل التطبيق

### باستخدام PowerShell:
```powershell
$env:ADMIN_USERNAME="administrator"
$env:ADMIN_PASSWORD="SecurePass2024!"
python app.py
```

---

## التحقق من التغييرات:

بعد إعادة التشغيل، جرب تسجيل الدخول بالبيانات الجديدة:
- افتح: `http://127.0.0.1:5000/login`
- أدخل اسم المستخدم وكلمة المرور الجديدة

---

## نصائح إضافية:

- **لا تشارك** ملف `config.py` في Git إذا كان يحتوي على كلمات مرور حقيقية
- يمكنك إضافة `config.py` إلى `.gitignore` لحماية كلمات المرور
- في بيئة الإنتاج، استخدم متغيرات البيئة بدلاً من ملف config.py

