"""
نقطة دخول WSGI للإنتاج.

    gunicorn -w 2 -b 0.0.0.0:5000 wsgi:application

أو مع Docker (انظر Dockerfile).
"""
from app import app as application

__all__ = ["application"]
