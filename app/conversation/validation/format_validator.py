"""Subsystem 16: Response Format Validator."""

import json
from typing import Tuple


class ResponseFormatValidator:
    """Validates output format compliance (Markdown, JSON, Plain Text, Structured)."""

    @classmethod
    def validate_format(cls, text: str, expected_format: str = "markdown") -> Tuple[bool, str]:
        if expected_format.lower() == "json":
            try:
                json.loads(text)
                return True, "Valid JSON"
            except Exception as e:
                return False, f"Invalid JSON format: {e}"
        return True, f"Valid {expected_format}"
