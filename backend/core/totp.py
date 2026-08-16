"""TOTP (RFC 6238) بدون اعتماد خارجي — HMAC-SHA1، 6 أرقام، خطوة 30 ثانية."""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote


def generate_secret(nbytes: int = 20) -> str:
    raw = secrets.token_bytes(max(10, nbytes))
    return base64.b32encode(raw).decode("ascii").rstrip("=")


def _decode_secret(secret: str) -> bytes:
    s = (secret or "").strip().replace(" ", "").replace("-", "").upper()
    pad = "=" * ((8 - len(s) % 8) % 8)
    return base64.b32decode(s + pad, casefold=True)


def hotp(secret: str, counter: int, digits: int = 6) -> str:
    key = _decode_secret(secret)
    msg = struct.pack(">Q", int(counter))
    digest = hmac.new(key, msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(code % (10 ** digits)).zfill(digits)


def totp_at(secret: str, for_time: int | None = None, step: int = 30, digits: int = 6) -> str:
    ts = int(time.time() if for_time is None else for_time)
    return hotp(secret, ts // int(step), digits=digits)


def verify_totp(secret: str, code: str, *, window: int = 1, step: int = 30, for_time: int | None = None) -> bool:
    raw = "".join(ch for ch in str(code or "") if ch.isdigit())
    if len(raw) != 6 or not secret:
        return False
    ts = int(time.time() if for_time is None else for_time)
    counter = ts // int(step)
    for delta in range(-int(window), int(window) + 1):
        if hmac.compare_digest(hotp(secret, counter + delta), raw):
            return True
    return False


def provisioning_uri(secret: str, username: str, issuer: str = "ScheduleOptimizer") -> str:
    label = quote(f"{issuer}:{username}")
    iss = quote(issuer)
    user = quote(username or "")
    sec = (secret or "").replace(" ", "")
    return (
        f"otpauth://totp/{label}?secret={sec}&issuer={iss}"
        f"&algorithm=SHA1&digits=6&period=30&account={user}"
    )


def provisioning_qr_svg(secret: str, username: str, issuer: str = "ScheduleOptimizer") -> str:
    """SVG لرمز QR. أي فشل يُتجاهل — الصفحة تعتمد على المفتاح اليدوي."""
    try:
        import segno

        uri = provisioning_uri(secret, username, issuer)
        qr = segno.make(uri, error="m")
        svg = qr.svg_inline(scale=5)
        return svg if isinstance(svg, str) else svg.decode("utf-8", errors="replace")
    except Exception:
        return ""
