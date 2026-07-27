import time
from app.security.crypto import token_crypto
from app.security.webhook_verifier import WebhookVerifier

def test_envelope_token_encryption_decryption():
    raw_token = "xoxb-secret-oauth-access-token-12345"
    tenant_id = "tenant_uuid_8888"

    # Encrypt
    encrypted_token = token_crypto.encrypt_token(raw_token, tenant_id)
    assert encrypted_token != raw_token
    assert len(encrypted_token) > 0

    # Decrypt
    decrypted_token = token_crypto.decrypt_token(encrypted_token, tenant_id)
    assert decrypted_token == raw_token

def test_slack_webhook_verification():
    signing_secret = "8f7a69219f74022f2342342342342342"
    timestamp = str(int(time.time()))
    body = b'{"type":"event_callback","event":{"type":"message"}}'

    # Compute valid signature
    import hmac, hashlib
    sig_basename = f"v0:{timestamp}:".encode("utf-8") + body
    valid_sig = "v0=" + hmac.new(signing_secret.encode("utf-8"), sig_basename, hashlib.sha256).hexdigest()

    # Verify true
    is_valid = WebhookVerifier.verify_slack_signature(signing_secret, timestamp, body, valid_sig)
    assert is_valid is True

    # Verify invalid secret fails
    is_invalid = WebhookVerifier.verify_slack_signature("wrong_secret", timestamp, body, valid_sig)
    assert is_invalid is False
