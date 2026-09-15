"""
Company Brain Technologies Inc.
Authentication & Security Microservice — Auth Module
"""

import jwt
import datetime
from typing import Dict, Any, Optional

SECRET_KEY = "company_brain_jwt_secret_key_prod"
ALGORITHM = "HS256"
TOKEN_EXPIRE_MINUTES = 60

class AuthService:
    """Manages JWT authentication tokens and tenant role assignments."""
    
    @staticmethod
    def create_access_token(tenant_id: str, user_id: str, role: str = "engineer") -> str:
        payload = {
            "tenant_id": tenant_id,
            "user_id": user_id,
            "role": role,
            "exp": datetime.datetime.utcnow() + datetime.timedelta(minutes=TOKEN_EXPIRE_MINUTES),
            "iss": "company_brain_auth_service"
        }
        return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

    @staticmethod
    def verify_token(token: str) -> Optional[Dict[str, Any]]:
        try:
            payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
            return payload
        except jwt.PyJWTError:
            return None
