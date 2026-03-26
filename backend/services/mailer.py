import os
import smtplib
from email.message import EmailMessage
from typing import Optional


def send_email(
    to_email: str,
    subject: str,
    body_text: str,
    *,
    body_html: Optional[str] = None,
) -> None:
    """
    إرسال بريد عبر SMTP اعتماداً على متغيرات البيئة:
      SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, SMTP_FROM
      SMTP_TLS=1 لتفعيل STARTTLS (افتراضي: 1)
    """
    host = (os.environ.get("SMTP_HOST") or "").strip()
    port_raw = (os.environ.get("SMTP_PORT") or "").strip()
    user = (os.environ.get("SMTP_USER") or "").strip()
    password = (os.environ.get("SMTP_PASS") or "").strip()
    from_email = (os.environ.get("SMTP_FROM") or user or "").strip()
    use_tls = (os.environ.get("SMTP_TLS") or "1").strip().lower() not in ("0", "false", "no")

    if not host or not from_email:
        raise RuntimeError("SMTP is not configured (SMTP_HOST/SMTP_FROM)")

    try:
        port = int(port_raw) if port_raw else 587
    except Exception:
        port = 587

    msg = EmailMessage()
    msg["From"] = from_email
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content(body_text or "")
    if body_html:
        msg.add_alternative(body_html, subtype="html")

    with smtplib.SMTP(host, port, timeout=20) as smtp:
        smtp.ehlo()
        if use_tls:
            smtp.starttls()
            smtp.ehlo()
        if user and password:
            smtp.login(user, password)
        smtp.send_message(msg)

