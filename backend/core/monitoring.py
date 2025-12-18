"""
نظام Monitoring و Health Checks
"""
import time
import os
from datetime import datetime
from flask import jsonify, Blueprint
from functools import wraps
import logging

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
    'last_request_time': None
}


def init_monitoring(app):
    """
    تهيئة نظام Monitoring
    
    Args:
        app: Flask application instance
    """
    monitoring_bp = Blueprint('monitoring', __name__)
    
    @monitoring_bp.route('/health')
    def health_check():
        """Health check endpoint"""
        try:
            # فحص قاعدة البيانات
            from ..services.utilities import get_connection
            with get_connection() as conn:
                conn.execute("SELECT 1").fetchone()
            
            return jsonify({
                'status': 'healthy',
                'timestamp': datetime.now().isoformat(),
                'uptime_seconds': (datetime.now() - app_stats['start_time']).total_seconds()
            }), 200
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return jsonify({
                'status': 'unhealthy',
                'error': str(e),
                'timestamp': datetime.now().isoformat()
            }), 503
    
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
    
    # Middleware لتتبع الطلبات
    @app.before_request
    def track_request():
        app_stats['request_count'] += 1
        app_stats['last_request_time'] = datetime.now()
    
    @app.after_request
    def track_response(response):
        if response.status_code >= 400:
            app_stats['error_count'] += 1
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

