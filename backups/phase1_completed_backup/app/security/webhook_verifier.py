import hmac
import hashlib
import time
from typing import Dict, Any

class WebhookVerifier:
    """
    Webhook Signature Verification for Workplace & Dev Connectors.
    Prevents webhook spoofing and replay attacks.
    """

    @staticmethod
    def verify_slack_signature(
        signing_secret: str,
        timestamp: str,
        raw_body: bytes,
        signature: str,
        max_age_seconds: int = 300
    ) -> bool:
        """
        Verifies Slack X-Slack-Signature (HMAC-SHA256).
        """
        if not signing_secret or not timestamp or not signature:
            return False

        # Prevent replay attacks
        if abs(time.time() - float(timestamp)) > max_age_seconds:
            return False

        sig_basename = f"v0:{timestamp}:".encode("utf-8") + raw_body
        computed_sig = "v0=" + hmac.new(
            signing_secret.encode("utf-8"),
            sig_basename,
            hashlib.sha256
        ).hexdigest()

        return hmac.compare_digest(computed_sig, signature)

    @staticmethod
    def verify_github_signature(
        webhook_secret: str,
        raw_body: bytes,
        signature: str
    ) -> bool:
        """
        Verifies GitHub X-Hub-Signature-256 (HMAC-SHA256).
        """
        if not webhook_secret or not signature or not signature.startswith("sha256="):
            return False

        expected_sig = "sha256=" + hmac.new(
            webhook_secret.encode("utf-8"),
            raw_body,
            hashlib.sha256
        ).hexdigest()

        return hmac.compare_digest(expected_sig, signature)

    @staticmethod
    def verify_whatsapp_signature(
        app_secret: str,
        raw_body: bytes,
        signature: str
    ) -> bool:
        """
        Verifies Meta / WhatsApp Business X-Hub-Signature-256.
        """
        return WebhookVerifier.verify_github_signature(app_secret, raw_body, signature)
