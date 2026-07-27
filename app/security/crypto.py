import base64
import os
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from app.config import settings

class TokenEncryptionEngine:
    """
    Envelope Encryption Engine for storing tenant OAuth access/refresh tokens securely.
    Uses AES-256-GCM for authenticated encryption at rest.
    """

    def __init__(self, master_key_str: str = settings.MASTER_ENCRYPTION_KEY):
        # Key must be 32 bytes for AES-256
        key_bytes = master_key_str.encode("utf-8")
        if len(key_bytes) < 32:
            key_bytes = key_bytes.ljust(32, b"0")
        elif len(key_bytes) > 32:
            key_bytes = key_bytes[:32]
            
        self.aesgcm = AESGCM(key_bytes)

    def encrypt_token(self, plain_token: str, tenant_id: str) -> str:
        """
        Encrypts an OAuth token string bound to a tenant_id as Associated Authenticated Data (AAD).
        Returns base64 encoded ciphertext containing the nonce.
        """
        if not plain_token:
            return ""
            
        nonce = os.urandom(12)  # 96-bit nonce for GCM
        aad = tenant_id.encode("utf-8")
        ciphertext = self.aesgcm.encrypt(nonce, plain_token.encode("utf-8"), aad)
        
        # Combine nonce + ciphertext
        encrypted_bytes = nonce + ciphertext
        return base64.b64encode(encrypted_bytes).decode("utf-8")

    def decrypt_token(self, encrypted_token_b64: str, tenant_id: str) -> str:
        """
        Decrypts an encrypted OAuth token string verifying tenant_id authenticity.
        """
        if not encrypted_token_b64:
            return ""

        encrypted_bytes = base64.b64decode(encrypted_token_b64.encode("utf-8"))
        nonce = encrypted_bytes[:12]
        ciphertext = encrypted_bytes[12:]
        aad = tenant_id.encode("utf-8")

        plain_bytes = self.aesgcm.decrypt(nonce, ciphertext, aad)
        return plain_bytes.decode("utf-8")

# Global singleton instance
token_crypto = TokenEncryptionEngine()
