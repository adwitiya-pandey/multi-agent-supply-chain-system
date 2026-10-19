"""Input sanitization and prompt injection detection for untrusted external text."""

from __future__ import annotations

import re
import unicodedata

# Compiled prompt-injection heuristics per SPEC 15 (S3)
INJECTION_PATTERNS = [
    re.compile(
        r"(ignore|disregard)\s+(all\s+)?(previous|prior|past|system|\s+)*(instructions?|prompts?|rules?)",
        re.IGNORECASE,
    ),
    re.compile(r"system\s+prompt\s+override", re.IGNORECASE),
    re.compile(r"you\s+are\s+now\s+(dan|an\s+executive)", re.IGNORECASE),
    re.compile(r"new\s+role\s*:", re.IGNORECASE),
    re.compile(r"bypass\s+guardrails?", re.IGNORECASE),
    re.compile(r"do\s+not\s+check\s+reorder", re.IGNORECASE),
    re.compile(r"auto\s+approve", re.IGNORECASE),
    re.compile(r"<script[\s>]", re.IGNORECASE),
    re.compile(r"reveal\s+your\s+(secret\s+key|internal\s+prompt)", re.IGNORECASE),
    re.compile(r"!\[.*?\]\(https?://", re.IGNORECASE),
    re.compile(r"order\s+[0-9]{5,}\s+(items?|units?)?", re.IGNORECASE),
]


def sanitize_untrusted_text(text: str, max_length: int = 400) -> tuple[str, bool]:
    """Strip control and format characters, cap length, wrap in untrusted tags,

    and detect injection patterns.
    """
    if not text:
        return "<untrusted></untrusted>", False

    # 1. Remove non-printable control and invisible unicode formatting characters
    cleaned_chars: list[str] = []
    for char in text:
        # Retain standard safe whitespace
        if char in ("\n", "\r", "\t", " "):
            cleaned_chars.append(char)
            continue

        cat = unicodedata.category(char)
        # Drop Cc (control), Cf (format e.g. zero-width space, direction overrides), Cs (surrogates)
        if cat in ("Cc", "Cf", "Cs"):
            continue

        cleaned_chars.append(char)

    cleaned = "".join(cleaned_chars)

    # Collapse multiple redundant spaces
    cleaned = re.sub(r"[ \t]+", " ", cleaned).strip()

    # 2. Cap length at max_length
    if len(cleaned) > max_length:
        cleaned = cleaned[:max_length]

    # 3. Detect prompt injection patterns
    flagged = any(pattern.search(cleaned) is not None for pattern in INJECTION_PATTERNS)

    # 4. Wrap inside <untrusted> tags
    wrapped = f"<untrusted>{cleaned}</untrusted>"
    return wrapped, flagged


def is_injection_pattern(text: str) -> bool:
    """Check whether text matches any prompt injection heuristic."""
    _, flagged = sanitize_untrusted_text(text)
    return flagged
