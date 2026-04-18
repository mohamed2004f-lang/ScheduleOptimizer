"""
إعدادات Logging محسّنة
"""
import os
import logging
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler


class FlaskContextFilter(logging.Filter):
    """يضيف request_id و method و path عند وجود سياق Flask."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = "-"
        record.http_method = "-"
        record.http_path = "-"
        try:
            from flask import has_request_context, request as flask_request
            from flask import g as flask_g

            if has_request_context():
                record.request_id = getattr(flask_g, "request_id", None) or "-"
                record.http_method = flask_request.method
                record.http_path = flask_request.path
        except Exception:
            pass
        return True


class SafeTimedRotatingFileHandler(TimedRotatingFileHandler):
    """
    Windows-safe TimedRotatingFileHandler.
    في ويندوز قد يفشل os.rename أثناء doRollover بسبب قفل الملف (WinError 32).
    بدل أن يكسر الـ logging thread، نتجاهل التدوير لهذه المرة ونكمل الكتابة.
    """

    def doRollover(self):
        try:
            return super().doRollover()
        except PermissionError:
            # ملف اللوج مقفول من عملية/محرر آخر. تجاهل التدوير الآن.
            return


def setup_logging(app, log_dir='logs'):
    """
    إعداد نظام Logging محسّن للتطبيق
    
    Args:
        app: Flask application instance
        log_dir: مجلد حفظ ملفات السجلات
    """
    # إنشاء مجلد السجلات إذا لم يكن موجوداً
    os.makedirs(log_dir, exist_ok=True)
    
    # إزالة المعالجات الافتراضية
    if not app.debug:
        # إزالة معالج الـ console الافتراضي
        for handler in app.logger.handlers[:]:
            app.logger.removeHandler(handler)
    
    # إعداد مستوى السجلات
    log_level = logging.INFO if not app.debug else logging.DEBUG
    app.logger.setLevel(log_level)

    ctx_filter = FlaskContextFilter()

    # معالج Console دائماً:
    # - في debug: مستوى DEBUG لسهولة التطوير
    # - خارج debug: مستوى INFO حتى تظهر العمليات والأخطاء في الـ Terminal أيضاً
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG if app.debug else logging.INFO)
    console_handler.addFilter(ctx_filter)
    console_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - '
        '[req=%(request_id)s %(http_method)s %(http_path)s] %(message)s'
    )
    console_handler.setFormatter(console_formatter)
    app.logger.addHandler(console_handler)
    
    # معالج للـ File (دوراني - Rotating)
    # delay=True يقلل مشاكل قفل الملفات على Windows (لا يفتح الملف إلا عند أول كتابة)
    file_handler = RotatingFileHandler(
        os.path.join(log_dir, 'schedule_optimizer.log'),
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=10,
        encoding='utf-8',
        delay=True,
    )
    file_handler.setLevel(logging.INFO)
    file_handler.addFilter(ctx_filter)
    file_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - '
        '[req=%(request_id)s %(http_method)s %(http_path)s] %(message)s '
        '[in %(pathname)s:%(lineno)d]',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    file_handler.setFormatter(file_formatter)
    app.logger.addHandler(file_handler)
    
    # معالج منفصل للأخطاء (Error Log)
    error_handler = RotatingFileHandler(
        os.path.join(log_dir, 'errors.log'),
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=10,
        encoding='utf-8',
        delay=True,
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.addFilter(ctx_filter)
    error_handler.setFormatter(file_formatter)
    app.logger.addHandler(error_handler)
    
    # معالج للسجلات اليومية (Daily Rotating)
    # في وضع التطوير (debug + reloader) على Windows قد يحدث WinError 32 عند التدوير
    # لذلك نفعّله فقط خارج debug.
    if not app.debug:
        daily_handler = SafeTimedRotatingFileHandler(
            os.path.join(log_dir, 'daily.log'),
            when='midnight',
            interval=1,
            backupCount=30,  # الاحتفاظ بـ 30 يوم
            encoding='utf-8',
            delay=True,
        )
        daily_handler.setLevel(logging.INFO)
        daily_handler.addFilter(ctx_filter)
        daily_handler.setFormatter(file_formatter)
        app.logger.addHandler(daily_handler)
    
    # معالج للـ Access Log (طلبات HTTP)
    access_handler = RotatingFileHandler(
        os.path.join(log_dir, 'access.log'),
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=10,
        encoding='utf-8',
        delay=True,
    )
    access_handler.setLevel(logging.INFO)
    access_handler.addFilter(ctx_filter)
    access_formatter = logging.Formatter(
        '%(asctime)s - [req=%(request_id)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    access_handler.setFormatter(access_formatter)
    
    # إنشاء logger منفصل للـ Access
    access_logger = logging.getLogger('access')
    access_logger.setLevel(logging.INFO)
    access_logger.addHandler(access_handler)
    access_logger.propagate = False
    
    app.logger.info('Logging system initialized')
    return app.logger


def log_request_info(request, logger):
    """
    تسجيل معلومات الطلب
    
    Args:
        request: Flask request object
        logger: Logger instance
    """
    access_logger = logging.getLogger('access')
    access_logger.info(
        "client=%s method=%s path=%s user_agent=%s",
        getattr(request, "remote_addr", "-"),
        request.method,
        request.path,
        (request.headers.get("User-Agent") or "Unknown")[:500],
    )


def log_error_with_context(error, request=None, logger=None):
    """
    تسجيل الأخطاء مع السياق
    
    Args:
        error: Exception object
        request: Flask request object (optional)
        logger: Logger instance (optional)
    """
    if logger is None:
        logger = logging.getLogger(__name__)
    
    error_msg = f"Error: {str(error)}"
    if request:
        error_msg += f" | Path: {request.path} | Method: {request.method}"
        error_msg += f" | IP: {request.remote_addr}"
    
    logger.error(error_msg, exc_info=True)

