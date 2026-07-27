import hashlib
import uuid
from typing import Optional
from fastapi import APIRouter, HTTPException, status, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, EmailStr
from sqlalchemy import text
from app.db.database import async_session_factory
from app.security.jwt_auth import jwt_engine

router = APIRouter(prefix="/api/v1/auth", tags=["Authentication & Tenants"])
security_bearer = HTTPBearer(auto_error=False)

class SignupRequest(BaseModel):
    company_name: str
    company_domain: str
    email: EmailStr
    password: str
    full_name: Optional[str] = "Enterprise Admin"

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class AuthResponse(BaseModel):
    status: str
    tenant_id: str
    user_id: str
    email: str
    company_name: str
    token: str

def hash_password(password: str) -> str:
    """Hashes user password securely using SHA-256 with salt."""
    salt = "company_brain_auth_salt_2026"
    return hashlib.sha256((password + salt).encode("utf-8")).hexdigest()

def get_current_tenant_from_jwt(credentials: Optional[HTTPAuthorizationCredentials] = Depends(security_bearer)) -> str:
    """FastAPI Dependency: Validates bearer JWT token and returns tenant_id."""
    if not credentials:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing Authentication Token.")
    payload = jwt_engine.decode_access_token(credentials.credentials)
    if not payload:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or Expired JWT Token.")
    return payload["tenant_id"]

@router.post("/signup", response_model=AuthResponse)
async def signup(req: SignupRequest):
    """
    Step 1: Signup & Tenant Creation
    Creates company tenant in 'tenants' table and admin account in 'users' table.
    Issues signed JWT access token.
    """
    async with async_session_factory() as session:
        # Check if domain already registered
        res_tenant = await session.execute(
            text("SELECT id FROM tenants WHERE domain = :domain"),
            {"domain": req.company_domain.lower().strip()},
        )
        existing_tenant = res_tenant.fetchone()
        
        if existing_tenant:
            tenant_id = str(existing_tenant[0])
        else:
            tenant_id = str(uuid.uuid4())
            await session.execute(
                text("INSERT INTO tenants (id, name, domain) VALUES (:id, :name, :domain)"),
                {"id": tenant_id, "name": req.company_name, "domain": req.company_domain.lower().strip()},
            )

        # Check if user email exists
        res_user = await session.execute(
            text("SELECT id FROM users WHERE email = :email"),
            {"email": req.email.lower().strip()},
        )
        if res_user.fetchone():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="User email already registered. Please login.",
            )

        user_id = str(uuid.uuid4())
        hashed_pwd = hash_password(req.password)

        await session.execute(
            text(f"SET LOCAL app.current_tenant_id = '{tenant_id}'")
        )

        await session.execute(
            text("""
                INSERT INTO users (id, tenant_id, email, hashed_password, full_name, role)
                VALUES (:id, :tenant_id, :email, :hashed_pwd, :full_name, 'admin')
            """),
            {
                "id": user_id,
                "tenant_id": tenant_id,
                "email": req.email.lower().strip(),
                "hashed_pwd": hashed_pwd,
                "full_name": req.full_name,
            },
        )
        await session.commit()

        # Issue production JWT access token
        jwt_token = jwt_engine.create_access_token(
            tenant_id=tenant_id,
            user_id=user_id,
            email=req.email,
            role="admin",
        )

        return AuthResponse(
            status="success",
            tenant_id=tenant_id,
            user_id=user_id,
            email=req.email,
            company_name=req.company_name,
            token=jwt_token,
        )

@router.post("/login", response_model=AuthResponse)
async def login(req: LoginRequest):
    """
    Step 1: Enterprise Login
    Verifies credentials and returns signed JWT access token + tenant_id.
    """
    async with async_session_factory() as session:
        hashed_pwd = hash_password(req.password)
        
        res_user = await session.execute(
            text("""
                SELECT u.id, u.tenant_id, u.email, t.name, u.role
                FROM users u
                JOIN tenants t ON u.tenant_id = t.id
                WHERE u.email = :email AND u.hashed_password = :hashed_pwd
            """),
            {"email": req.email.lower().strip(), "hashed_pwd": hashed_pwd},
        )
        user = res_user.fetchone()
        
        if not user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password.",
            )

        user_id, tenant_id, email, company_name, role = str(user[0]), str(user[1]), user[2], user[3], user[4]

        # Issue production JWT access token
        jwt_token = jwt_engine.create_access_token(
            tenant_id=tenant_id,
            user_id=user_id,
            email=email,
            role=role or "admin",
        )

        return AuthResponse(
            status="success",
            tenant_id=tenant_id,
            user_id=user_id,
            email=email,
            company_name=company_name,
            token=jwt_token,
        )
