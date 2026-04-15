"""
نظام Monitoring و Health Checks
"""
import time
import os
import traceback
from collections import deque
from datetime import datetime
from flask import jsonify, Blueprint, g, request, has_request_context
from functools import wraps
import logging

from backend.core.request_context import HEADER_IN, HEADER_OUT, resolve_incoming_request_id, set_request_id

# محاولة استيراد psutil بشكل اختياري
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False
    logging.warning("psutil not available - metrics will be limited")

logger = logging.getLogger(__name__)

# إحصائيات التطبيق
app_stats = {
    'start_time': datetime.now(),
    'request_count': 0,
    'error_count': 0,
    'last_request_time': None,
}

# آخر أحداث خطأ حرجة (لعرضها في لوحة الإدارة) — حلقة ثابتة الحجم
CRITICAL_ERRORS_MAX = 20
critical_errors: deque[dict] = deque(maxlen=CRITICAL_ERRORS_MAX)


def record_critical_error(
    *,
    message: str,
    exc: BaseException | None = None,
    path: str | None = None,
    request_id: str | None = None,
) -> None:
    """تسجيل ملخص خطأ حرج لعرضه في /admin/system_diagnostics (بدون رفع الاستثناء)."""
    try:
        entry = {
            "ts": datetime.now().isoformat(),
            "message": (message or "")[:2000],
            "type": type(exc).__name__ if exc else "error",
            "path": (path or "")[:500],
            "request_id": (request_id or "")[:128],
        }
        if exc is not None:
            tb = traceback.format_exception(type(exc), exc, exc.__traceback__)
            entry["traceback_tail"] = "".join(tb)[-4000:]
        critical_errors.append(entry)
    except Exception:
        pass


def get_critical_errors_snapshot() -> list[dict]:
    return list(critical_errors)


def init_monitoring(app):
    """
    تهيئة نظام Monitoring
    
    Args:
        app: Flask application instance
    """
    monitoring_bp = Blueprint('monitoring', __name__)
    # ملاحظة: مسار /health مُعرّف في app.py للتوافق مع Docker (استجابة خفيفة).

    @monitoring_bp.route('/metrics')
    def metrics():
        """Metrics endpoint - إحصائيات التطبيق"""
        try:
            metrics_data = {
                'application': {
                    'uptime_seconds': (datetime.now() - app_stats['start_time']).total_seconds(),
                    'request_count': app_stats['request_count'],
                    'error_count': app_stats['error_count'],
                    'last_request_time': app_stats['last_request_time'].isoformat() if app_stats['last_request_time'] else None
                },
                'timestamp': datetime.now().isoformat()
            }
            
            # إضافة معلومات النظام إذا كان psutil متاحاً
            if PSUTIL_AVAILABLE:
                try:
                    process = psutil.Process(os.getpid())
                    memory_info = process.memory_info()
                    disk_usage = psutil.disk_usage('/')
                    
                    metrics_data['system'] = {
                        'cpu_percent': psutil.cpu_percent(interval=0.1),
                        'memory': {
                            'used_mb': memory_info.rss / 1024 / 1024,
                            'percent': process.memory_percent()
                        },
                        'disk': {
                            'used_gb': disk_usage.used / 1024 / 1024 / 1024,
                            'free_gb': disk_usage.free / 1024 / 1024 / 1024,
                            'percent': disk_usage.percent
                        }
                    }
                except Exception as e:
                    logger.warning(f"Failed to collect system metrics: {e}")
                    metrics_data['system'] = {'error': 'System metrics unavailable'}
            else:
                metrics_data['system'] = {'note': 'psutil not installed - install it for system metrics'}
            
            return jsonify(metrics_data), 200
        except Exception as e:
            logger.error(f"Metrics collection failed: {e}")
            return jsonify({
                'status': 'error',
                'message': str(e)
            }), 500
    
    @monitoring_bp.route('/stats')
    def stats():
        """إحصائيات مبسطة"""
        return jsonify({
            'uptime_seconds': (datetime.now() - app_stats['start_time']).total_seconds(),
            'requests': app_stats['request_count'],
            'errors': app_stats['error_count']
        }), 200
    
    app.register_blueprint(monitoring_bp)
    
    access_logger = logging.getLogger('access')

    @app.before_request
    def track_request():
        rid = resolve_incoming_request_id(request.headers.get(HEADER_IN))
        g.request_id = rid
        set_request_id(rid)
        app_stats['request_count'] += 1
        app_stats['last_request_time'] = datetime.now()
    
    @app.after_request
    def track_response(response):
        try:
            rid = getattr(g, 'request_id', None) or ''
            if rid:
                response.headers[HEADER_OUT] = rid
        except Exception:
            pass
        if response.status_code >= 400:
            app_stats['error_count'] += 1
        # سطر وصول منظم (ملف access.log عبر logger access)
        try:
            if has_request_context():
                access_logger.info(
                    "request_id=%s method=%s path=%s status=%s",
                    getattr(g, 'request_id', '-'),
                    request.method,
                    request.path,
                    response.status_code,
                )
        except Exception:
            pass
        set_request_id(None)
        return response
    
    return monitoring_bp


def track_performance(func):
    """Decorator لتتبع أداء الدوال"""
    @wraps(func)
    def wrapper(*args, **kwargs):
        start_time = time.time()
        try:
            result = func(*args, **kwargs)
            duration = time.time() - start_time
            logger.info(f"{func.__name__} executed in {duration:.3f}s")
            return result
        except Exception as e:
            duration = time.time() - start_time
            logger.error(f"{func.__name__} failed after {duration:.3f}s: {e}")
            raise
    return wrapper

