from app.processors.pii_redactor import pii_redactor

def test_aws_key_redaction():
    text_with_aws_key = "Leaked key: AKIAIOSFODNN7EXAMPLE in codebase!"
    redacted = pii_redactor.redact_secrets(text_with_aws_key)
    assert "AKIAIOSFODNN7EXAMPLE" not in redacted
    assert "[REDACTED_AWS_KEY_ID]" in redacted

def test_slack_token_redaction():
    text_with_slack_token = "Slack bot token: xoxb-1234567890-abcdefghij"
    redacted = pii_redactor.redact_secrets(text_with_slack_token)
    assert "xoxb-1234567890-abcdefghij" not in redacted
    assert "[REDACTED_SLACK_TOKEN]" in redacted

def test_github_token_redaction():
    text_with_gh_token = "GitHub token ghp_1234567890abcdefghijklmnopqrstuvwxyz"
    redacted = pii_redactor.redact_secrets(text_with_gh_token)
    assert "ghp_1234567890abcdefghijklmnopqrstuvwxyz" not in redacted
    assert "[REDACTED_GITHUB_TOKEN]" in redacted
