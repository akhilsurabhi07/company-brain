import base64
import hashlib
import hmac
import json
import time
from typing import Any, Dict, Optional
from app.config import settings

# JWT Secret Key from config or default fallback
JWT_SECRET_KEY = getattr(settings, "JWT_SECRET_KEY", "company_brain_jwt_secret_key_2026_super_secure")
JWT_ALGORITHM = "HS256"
DEFAULT_EXPIRATION_SECONDS = 86400 * 7  # 7 Days

def _base64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("utf-8")

def _base64url_decode(encoded_str: str) -> bytes:
    padding = "=" * (4 - (len(encoded_str) % 4))
    return base64.urlsafe_b64decode((encoded_str + padding).encode("utf-8"))

class JWTAuthEngine:
    """
    Stateless Enterprise JWT Authentication Engine.
    Generates and verifies HMAC-SHA256 (HS256) compliant JSON Web Tokens.
    Ensures multi-server scalability across distributed load-balanced instances.
    """

    def create_access_token(
        self,
        tenant_id: str,
        user_id: str,
        email: str,
        # Real hardening found via code audit 2026-09-11: this function mints
        # real, signed JWTs -- a durable credential valid until expiry, not
        # just a single function call's in-memory parameter. Both real
        # callers (signup, login in app/api/auth.py) already explicitly pass
        # a real role, so this default is currently unreachable, but a token-
        # issuing function's unreachable default is exactly the kind of thing
        # that becomes reachable the moment someone adds a new caller without
        # reading this far. Fail closed to the lowest privilege.
        role: str = "member",
        expires_in_seconds: int = DEFAULT_EXPIRATION_SECONDS,
    ) -> str:
        header = {"alg": JWT_ALGORITHM, "typ": "JWT"}
        payload = {
            "tenant_id": tenant_id,
            "user_id": user_id,
            "email": email,
            "role": role,
            "iat": int(time.time()),
            "exp": int(time.time()) + expires_in_seconds,
        }

        encoded_header = _base64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
        encoded_payload = _base64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))

        signing_input = f"{encoded_header}.{encoded_payload}".encode("utf-8")
        signature = hmac.new(JWT_SECRET_KEY.encode("utf-8"), signing_input, hashlib.sha256).digest()
        encoded_signature = _base64url_encode(signature)

        return f"{encoded_header}.{encoded_payload}.{encoded_signature}"

    def decode_access_token(self, token: str) -> Optional[Dict[str, Any]]:
        try:
            parts = token.split(".")
            if len(parts) != 3:
                return None

            encoded_header, encoded_payload, encoded_signature = parts
            signing_input = f"{encoded_header}.{encoded_payload}".encode("utf-8")
            expected_sig = hmac.new(JWT_SECRET_KEY.encode("utf-8"), signing_input, hashlib.sha256).digest()
            actual_sig = _base64url_decode(encoded_signature)

            if not hmac.compare_digest(expected_sig, actual_sig):
                return None  # Tampered token signature

            payload = json.loads(_base64url_decode(encoded_payload).decode("utf-8"))

            # Check expiration
            if payload.get("exp") and time.time() > payload["exp"]:
                return None  # Expired token

            return payload

        except Exception:
            return None

jwt_engine = JWTAuthEngine()
