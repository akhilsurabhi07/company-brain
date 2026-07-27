import re

class PIIRedactor:
    """
    Secrets & Sensitive Data Redaction Engine.
    Scans text extracted from Slack, GitHub, Jira, etc. for leaked API keys, tokens,
    passwords, and credentials before saving to PostgreSQL or Vector DBs.
    """

    PATTERNS = [
        # AWS Access Key ID
        (re.compile(r"\b(AKIA|ASIA)[0-9A-Z]{16}\b"), "[REDACTED_AWS_KEY_ID]"),
        # AWS Secret Access Key
        (re.compile(r"(?i)aws_secret_access_key\s*[:=]\s*['\"]?([A-Za-z0-9/+=]{40})['\"]?"), "aws_secret_access_key = [REDACTED_AWS_SECRET]"),
        # Stripe / Generic API Keys (sk_live_ / sk_test_)
        (re.compile(r"sk_(live|test)_[0-9a-zA-Z]{16,}"), "[REDACTED_API_KEY]"),
        # Slack Tokens
        (re.compile(r"xox[baprs]-[0-9a-zA-Z]{10,48}"), "[REDACTED_SLACK_TOKEN]"),
        # GitHub Personal Access Token / App Token
        (re.compile(r"gh[pousr]_[A-Za-z0-9_]{36,255}"), "[REDACTED_GITHUB_TOKEN]"),
        # Generic API Key / Secret / Password assignment
        (re.compile(r"(?i)(api[_-]?key|secret|password|bearer|auth[_-]?token)\s*[:=]\s*['\"]?([A-Za-z0-9_\-\.]{16,})['\"]?"), r"\1 = [REDACTED_SECRET]"),
        # Private Keys
        (re.compile(r"-----BEGIN (RSA|EC|PGP|OPENSSH) PRIVATE KEY-----[\s\S]*?-----END \1 PRIVATE KEY-----"), "[REDACTED_PRIVATE_KEY]"),
    ]

    @classmethod
    def redact_secrets(cls, text: str) -> str:
        """Scans and redacts detected secrets and API keys from text."""
        if not text:
            return ""
            
        redacted_text = text
        for pattern, replacement in cls.PATTERNS:
            redacted_text = pattern.sub(replacement, redacted_text)
        return redacted_text

pii_redactor = PIIRedactor()
