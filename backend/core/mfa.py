"""التحقق بخطوتين (TOTP) لـ system_admin و college_dean."""
from __future__ import annotations

import logging
import os
from typing import Optional, Tuple

from flask import jsonify, redirect, request, session

logger = logging.getLogger(__name__)

SESSION_MFA_PENDING = "mfa_pending"
SESSION_MFA_USER = "mfa_user"
SESSION_MFA_SETUP = "mfa_setup_required"
SESSION_MFA_CTX = "mfa_ctx"
SESSION_MFA_SETUP_SECRET = "mfa_setup_secret"

MFA_ROLES = frozenset({"system_admin", "college_dean"})

_MFA_PATH_PREFIXES = (
    "/auth/mfa",
    "/mfa",
    "/static/",
    "/health",
    "/favicon",
)
_MFA_PATH_EXACT = frozenset({
    "/login",
    "/logout",
    "/auth/login",
    "/auth/logout",
})


def _get_connection():
    try:
        from backend.services.utilities import get_connection
        return get_connection
    except Exception:
        return None


def mfa_enforce() -> bool:
    """الإنتاج يفرض MFA للأدوار المحددة. الاختبارات لا تفرض إلا بـ MFA_ENFORCE=1."""
    v = (os.environ.get("MFA_ENFORCE") or "").strip().lower()
    forced_on = v in ("1", "true", "yes", "on")
    forced_off = v in ("0", "false", "no", "off")
    testing = False
    try:
        from flask import current_app
        testing = bool(current_app.config.get("TESTING"))
    except Exception:
        pass
    env = (os.environ.get("FLASK_ENV") or "").strip().lower()
    if env in ("testing", "test"):
        testing = True
    if testing:
        return forced_on
    if forced_off:
        return False
    if forced_on:
        return True
    return env == "production"


def role_requires_mfa(role: str) -> bool:
    r = (role or "").strip().lower().replace("-", "_").replace(" ", "_")
    return r in MFA_ROLES


def user_mfa_state(username: str) -> Tuple[bool, Optional[str]]:
    """(totp_enabled, secret). إن غابت الأعمدة يُعاد (False, None)."""
    get_connection = _get_connection()
    if get_connection is None or not (username or "").strip():
        return False, None
    try:
        with get_connection() as conn:
            row = conn.cursor().execute(
                """
                SELECT COALESCE(totp_enabled, 0), totp_secret
                FROM users WHERE lower(username) = lower(?)
                """,
                (username.strip(),),
            ).fetchone()
        if not row:
            return False, None
        enabled = int(row[0] or 0) == 1
        from backend.core.secret_box import decrypt_secret, is_encrypted

        stored = row[1]
        secret = decrypt_secret(stored)
        if secret and stored and not is_encrypted(str(stored)):
            save_user_totp(username, secret)
        return enabled, secret
    except Exception:
        logger.debug("user_mfa_state: totp columns unavailable", exc_info=True)
        return False, None


def save_user_totp(username: str, secret: str) -> bool:
    get_connection = _get_connection()
    if get_connection is None or not (username or "").strip() or not secret:
        return False
    try:
        with get_connection() as conn:
            cur = conn.cursor()
            from backend.core.secret_box import encrypt_secret

            cur.execute(
                """
                UPDATE users
                SET totp_secret = ?, totp_enabled = 1
                WHERE lower(username) = lower(?)
                """,
                (encrypt_secret(secret.strip()), username.strip()),
            )
            conn.commit()
        return True
    except Exception:
        logger.exception("save_user_totp failed username=%s", username)
        return False


def park_mfa_session(login_ctx: dict, *, setup: bool) -> None:
    session.clear()
    session.permanent = False
    session[SESSION_MFA_PENDING] = True
    session[SESSION_MFA_USER] = (login_ctx.get("canonical_user") or "").strip()
    session[SESSION_MFA_SETUP] = bool(setup)
    session[SESSION_MFA_CTX] = login_ctx
    session.modified = True


def park_and_respond(login_ctx: dict, *, setup: bool, wants_json: bool):
    park_mfa_session(login_ctx, setup=setup)
    if wants_json:
        if setup:
            return jsonify({
                "status": "mfa_setup_required",
                "code": "MFA_SETUP_REQUIRED",
                "message": "يجب تفعيل التحقق بخطوتين لهذا الحساب",
            }), 200
        return jsonify({
            "status": "mfa_required",
            "code": "MFA_REQUIRED",
            "message": "أدخل رمز التحقق من تطبيق المصادقة",
        }), 200
    return redirect("/mfa/setup" if setup else "/mfa/verify")


def intercept_login_mfa(login_ctx: dict, *, totp_code: str, wants_json: bool):
    """
    إن لزم MFA: أكمل الدخول إن كان الرمز صالحاً (None)، أو أعد استجابة التحدي.
    """
    from backend.core.totp import verify_totp

    role = login_ctx.get("role") or ""
    user = (login_ctx.get("canonical_user") or "").strip()
    enabled, secret = user_mfa_state(user)
    code = "".join(ch for ch in str(totp_code or "") if ch.isdigit())

    if enabled and secret:
        if code and verify_totp(secret, code):
            return None
        return park_and_respond(login_ctx, setup=False, wants_json=wants_json)

    if role_requires_mfa(role) and mfa_enforce():
        return park_and_respond(login_ctx, setup=True, wants_json=wants_json)
    return None


def mfa_path_allowed(path: str) -> bool:
    p = (path or "/").split("?")[0] or "/"
    if p in _MFA_PATH_EXACT:
        return True
    return any(p.startswith(prefix) for prefix in _MFA_PATH_PREFIXES)


def register_mfa_pending_guard(app) -> None:
    @app.before_request
    def _block_until_mfa():
        if request.method == "OPTIONS":
            return None
        if not session.get(SESSION_MFA_PENDING):
            return None
        if mfa_path_allowed(request.path or "/"):
            return None
        accept = (request.headers.get("Accept") or "").lower()
        is_api = (
            request.is_json
            or "application/json" in accept
            or (request.path or "").startswith("/api/")
            or request.headers.get("X-Requested-With") == "XMLHttpRequest"
        )
        if is_api:
            return jsonify({
                "status": "error",
                "message": "أكمل التحقق بخطوتين أولاً",
                "code": "MFA_PENDING",
            }), 401
        if session.get(SESSION_MFA_SETUP):
            return redirect("/mfa/setup")
        return redirect("/mfa/verify")
