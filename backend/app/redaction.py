"""Secret redaction and sensitive-content detection. Used by logs, audit, memory filter."""
from __future__ import annotations

import re
from typing import Any

_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"nvapi-[A-Za-z0-9_\-]{10,}"),
    re.compile(r"AIza[0-9A-Za-z_\-]{20,}"),
    re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{12,}"),
    re.compile(r"(?i)\b(api[_-]?key|access[_-]?token|auth[_-]?token|session[_-]?token|token|secret|password|passwd|pwd)\b\s*[:=]\s*[^\s,;\"']+"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\b[A-Za-z0-9_\-]{24,}\.[A-Za-z0-9_\-]{6,}\.[A-Za-z0-9_\-]{20,}\b"),  # JWT-like
]
_SSN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_CARD = re.compile(r"\b(?:\d[ -]?){13,19}\b")
SENSITIVE_KEYS = {"api_key", "apikey", "token", "secret", "password", "authorization", "x-zonic-token"}
MASK = "[REDACTED]"


def _luhn(digits: str) -> bool:
    total, alt = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if alt:
            d *= 2
            if d > 9:
                d -= 9
        total += d
        alt = not alt
    return total % 10 == 0


def _has_card(text: str) -> bool:
    for m in _CARD.finditer(text):
        digits = re.sub(r"\D", "", m.group())
        if 13 <= len(digits) <= 19 and _luhn(digits):
            return True
    return False


def contains_sensitive(text: str) -> bool:
    if not text:
        return False
    return any(p.search(text) for p in _PATTERNS) or bool(_SSN.search(text)) or _has_card(text)


def redact(text: str) -> str:
    if not text:
        return text
    out = text
    for p in _PATTERNS:
        out = p.sub(MASK, out)
    out = _SSN.sub(MASK, out)
    return _CARD.sub(lambda m: MASK if _luhn(re.sub(r"\D", "", m.group())) else m.group(), out)


def redact_obj(obj: Any, _key: str = "") -> Any:
    if isinstance(obj, dict):
        return {k: (MASK if str(k).lower() in SENSITIVE_KEYS and isinstance(v, str) else redact_obj(v, str(k))) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [redact_obj(v, _key) for v in obj]
    if isinstance(obj, str):
        return redact(obj)
    return obj
