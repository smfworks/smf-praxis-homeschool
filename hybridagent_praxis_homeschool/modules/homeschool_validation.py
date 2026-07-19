"""Strict scalar validators shared by the governed homeschool modules."""
from __future__ import annotations

import re
from datetime import date

_SHA256_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
_BASIC_DATE_RE = re.compile(r"[0-9]{8}\Z")


def valid_sha256(value: object) -> bool:
    """Return whether *value* is a canonical lowercase SHA-256 reference."""
    return isinstance(value, str) and _SHA256_RE.fullmatch(value) is not None


def iso_date(value: object, field: str) -> date:
    """Parse an ISO calendar date or raise a field-specific ``ValueError``."""
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be an ISO date")
    if _BASIC_DATE_RE.fullmatch(value):
        value = f"{value[:4]}-{value[4:6]}-{value[6:]}"
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field} must be an ISO date") from exc
