"""Regex-tier PII redaction for attachment text, applied before content can reach
any model. Fully local and deterministic.

Catches structured PII: emails, phone numbers, SSNs, credit cards (Luhn-checked),
IPv4 addresses. Does NOT catch names or addresses — that requires an NER tier.
Identical values map to identical placeholders so experts can still reason about
the document ("the person at [EMAIL-1] called twice").
"""

from __future__ import annotations

import re

_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("EMAIL", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")),
    ("SSN", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    (
        "PHONE",
        re.compile(
            r"(?<!\d)(?:\+\d{1,3}[ .-]?)?(?:\(\d{3}\)[ .-]?|\d{3}[ .-])\d{3}[ .-]\d{4}(?!\d)"
        ),
    ),
    ("CARD", re.compile(r"\b(?:\d[ -]?){13,19}\b")),
    ("IP", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")),
]


def _luhn_ok(digits: str) -> bool:
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


def redact_pii(text: str) -> str:
    if not text:
        return text
    seen: dict[str, str] = {}
    counters: dict[str, int] = {}

    def _placeholder(kind: str, value: str) -> str:
        key = f"{kind}:{value}"
        if key not in seen:
            counters[kind] = counters.get(kind, 0) + 1
            seen[key] = f"[{kind}-{counters[kind]}]"
        return seen[key]

    for kind, pattern in _PATTERNS:
        def _sub(m: re.Match[str], kind: str = kind) -> str:
            value = m.group(0)
            if kind == "CARD":
                digits = re.sub(r"\D", "", value)
                if not (13 <= len(digits) <= 19 and _luhn_ok(digits)):
                    return value  # not a card number — leave it alone
            return _placeholder(kind, value)

        text = pattern.sub(_sub, text)
    return text
