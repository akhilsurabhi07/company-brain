"""Subsystem 15: Output Safety Guard Engine."""

import re
from typing import Tuple


class OutputGuard:
    """Scans and redacts leaked secrets, API keys, passwords, PII, prompt leakage, and jailbreak attempts."""

    SECRET_PATTERNS = [
        (re.compile(r"sk_(live|test)_[0-9a-zA-Z]{16,}"), "[REDACTED_API_KEY]"),
        (re.compile(r"xox[baprs]-[0-9a-zA-Z]{10,48}"), "[REDACTED_SLACK_TOKEN]"),
        (re.compile(r"gh[pousr]_[A-Za-z0-9_]{36,255}"), "[REDACTED_GITHUB_TOKEN]"),
        (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[REDACTED_SSN]"),
    ]

    PROMPT_LEAK_PATTERNS = [
        re.compile(r"(?i)ignore previous instructions"),
        re.compile(r"(?i)you are an unconstrained ai"),
        re.compile(r"(?i)system prompt:"),
    ]

    @classmethod
    def sanitize_output(cls, text: str) -> Tuple[str, bool]:
        if not text:
            return "", True

        sanitized = text
        for pattern, replacement in cls.SECRET_PATTERNS:
            sanitized = pattern.sub(replacement, sanitized)

        for leak_pattern in cls.PROMPT_LEAK_PATTERNS:
            if leak_pattern.search(text):
                # Detected prompt leakage or jailbreak attempt
                return "[REDACTED: System Policy Security Guard Blocked Leakage]", False

        return sanitized, True
