# تواصل الأستاذ وروابط مجموعات المقرر

## للمستخدمين

### الأستاذ
- من شريط التنقل **تواصلي** أو **مقرراتي ← اختصار تواصلي** (`/my_contact`):
  - يتحكم بظهور: الإيميل / رقم واتساب / اسم مستخدم واتساب.
- من **صفحة المقرر → تبويب «تواصل الطلبة»**: روابط مجموعة المقرر.

### رئيس القسم / الإدارة
- يضبط **ظهور الإيميل فقط**.
- يمكنه تعبئة رقم/`@` واتساب دون تغيير أعلام ظهورهما (تبقى كما ضبطها الأستاذ، والافتراضي مخفي).
- ظهور واتساب و`@` = صلاحية الأستاذ حصراً (واجهة + خادم).

### الطالب
- يرى التواصل في **صفحة المقرر المسجّل**.
- شارة «تواصل متاح» في قائمة مقرراتي الدراسية.
- أيقونة بجانب اسم الأستاذ في **جدولي** عند توفر تواصل.

## للمطوّرين

- السياسة: `backend/core/instructor_contact_policy.py`
- أعمدة `instructors`: `contact_email_visible`, `whatsapp_*`
- جدول: `course_group_links`
- API:
  - `GET|POST /instructors/me/contact_settings`
  - `GET|POST /instructors/<id>/contact_settings`
  - `GET /course_pages/instructor/group_links`
  - `POST /course_pages/instructor/group_links/save`
  - `GET /course_pages/student/course` → حقل `contact`
  - `GET /course_pages/student/my_courses` → `contact_available`
