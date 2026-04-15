"""
معرّف الطلب (request id) عبر سياق Flask ومتغير سياق لاستخدامه في السجلات خارج الطلب.
"""
from __future__ import annotations

import uuid
from contextvars import ContextVar

_request_id_ctx: ContextVar[str | None] = ContextVar("request_id", default=None)

HEADER_IN = "X-Request-ID"
HEADER_OUT = "X-Request-ID"


def get_request_id() -> str | None:
    return _request_id_ctx.get()


def set_request_id(value: str | None) -> None:
    _request_id_ctx.set(value)


def new_request_id() -> str:
    return str(uuid.uuid4())


def resolve_incoming_request_id(header_value: str | None) -> str:
    """يقبل معرفاً من العميل إن كان قصيراً وبلا أحرف خطرة؛ وإلا يولّد معرفاً جديداً."""
    if not header_value:
        return new_request_id()
    s = header_value.strip()
    if 8 <= len(s) <= 128 and all(c.isprintable() and c not in "\r\n\t" for c in s):
        return s
    return new_request_id()
