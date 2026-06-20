"""
نقطة دخول WSGI للإنتاج.

    gunicorn -w 2 -b 0.0.0.0:5000 wsgi:application

أو مع Docker (انظر Dockerfile).
"""
from werkzeug.middleware.proxy_fix import ProxyFix

from app import app as application

# Cloudflare Tunnel / reverse proxy: X-Forwarded-Proto, Host, For
application.wsgi_app = ProxyFix(
    application.wsgi_app,
    x_for=1,
    x_proto=1,
    x_host=1,
)

__all__ = ["application"]
