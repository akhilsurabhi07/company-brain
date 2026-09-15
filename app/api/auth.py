import uuid
import bcrypt
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional
from fastapi import APIRouter, HTTPException, status, Depends
from pydantic import BaseModel, EmailStr
from sqlalchemy import text
from app.db.database import async_session_factory
from app.security.jwt_auth import jwt_engine
from app.security.auth_dependency import require_authenticated_tenant

router = APIRouter(prefix="/api/v1/auth", tags=["Authentication & Tenants"])

INVITE_TOKEN_PREFIX = "cbinv_"
INVITE_EXPIRY_DAYS = 7

class SignupRequest(BaseModel):
    company_name: str
    company_domain: str
    email: EmailStr
    password: str
    full_name: Optional[str] = "Enterprise Admin"
    # Real invite path (see /invite below): joining an EXISTING tenant requires one of
    # these, checked against a specific email + not expired + not already used. Without
    # a valid one, signup against an already-registered domain is rejected outright —
    # see the real fix this replaced, right below in signup().
    invite_token: Optional[str] = None

class InviteRequest(BaseModel):
    email: EmailStr
    role: str = "member"

class InviteResponse(BaseModel):
    invite_token: str
    email: str
    role: str
    expires_at: str
    company_name: str
    company_domain: str

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

class ProfileResponse(BaseModel):
    user_id: str
    tenant_id: str
    email: str
    full_name: Optional[str] = None
    department: Optional[str] = None
    role: str

class UpdateProfileRequest(BaseModel):
    full_name: Optional[str] = None
    department: Optional[str] = None

class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str

def hash_password(password: str) -> str:
    """Hashes a password with bcrypt — a real per-password random salt (bcrypt.gensalt()
    embeds it in the returned hash), not the previous SHA-256 + one hardcoded salt shared
    by every user, which offered no real per-user salting at all and is fast enough to be
    brute-forced at scale."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")

def verify_password(password: str, hashed: str) -> bool:
    """Verifies a plaintext password against a bcrypt hash. Returns False (rather than
    raising) for anything that isn't a valid bcrypt hash, so a leftover pre-migration
    SHA-256 hash just fails closed instead of crashing the login request."""
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False

@router.post("/invite", response_model=InviteResponse)
async def create_invite(req: InviteRequest, token=Depends(require_authenticated_tenant)):
    """Real invite creation — the actual path for bringing a teammate into an existing
    tenant, replacing the "just guess the domain" hole that used to exist. Only a
    tenant admin can invite; the raw token is returned once and only its hash is
    persisted (same principle as mcp_api_keys), bound to one specific email so someone
    who intercepts the link can't redeem it as themselves."""
    if token.get("role") != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only a workspace admin can invite teammates.")

    tenant_id = token["tenant_id"]
    raw_token = INVITE_TOKEN_PREFIX + secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
    expires_at = datetime.now(timezone.utc) + timedelta(days=INVITE_EXPIRY_DAYS)

    async with async_session_factory() as session:
        await session.execute(text("SELECT set_config('app.current_tenant_id', :tid, true)"), {"tid": tenant_id})
        await session.execute(
            text("""
                INSERT INTO tenant_invites (tenant_id, invited_by_user_id, email, role, token_hash, expires_at)
                VALUES (:tenant_id, :invited_by, :email, :role, :hash, :expires_at)
            """),
            {
                "tenant_id": tenant_id,
                "invited_by": token["user_id"],
                "email": req.email.lower().strip(),
                "role": req.role,
                "hash": token_hash,
                "expires_at": expires_at,
            },
        )
        tenant_row = (await session.execute(
            text("SELECT name, domain FROM tenants WHERE id = :id"), {"id": tenant_id}
        )).fetchone()
        await session.commit()

    return InviteResponse(
        invite_token=raw_token,
        email=req.email.lower().strip(),
        role=req.role,
        expires_at=expires_at.isoformat(),
        company_name=tenant_row.name,
        company_domain=tenant_row.domain,
    )

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

        invite_role = None  # set below only when a real invite is redeemed

        if existing_tenant:
            existing_tenant_id = str(existing_tenant[0])
            # Real fix: signup used to silently join whoever asked into an EXISTING
            # tenant as role='admin' just by supplying its domain string — no proof of
            # domain ownership, no invite, no approval. That's an account-takeover path:
            # anyone who knows/guesses "acme.com" could self-provision full admin access
            # to Acme's tenant. Joining now requires a real invite, checked against this
            # exact tenant + this exact email, unexpired and unused — anything else is
            # rejected rather than silently joined.
            if not req.invite_token:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="A workspace for this domain already exists. Ask your workspace admin for an invite instead of signing up again.",
                )

            invite_hash = hashlib.sha256(req.invite_token.encode("utf-8")).hexdigest()
            await session.execute(text("SELECT set_config('app.current_tenant_id', :tid, true)"), {"tid": existing_tenant_id})
            res_invite = await session.execute(
                text("""
                    SELECT id, email, role FROM tenant_invites
                    WHERE tenant_id = :tid AND token_hash = :hash
                      AND used_at IS NULL AND expires_at > now()
                """),
                {"tid": existing_tenant_id, "hash": invite_hash},
            )
            invite_row = res_invite.fetchone()
            if not invite_row or invite_row.email.lower() != req.email.lower().strip():
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="This invite is invalid, expired, already used, or not addressed to this email.",
                )

            tenant_id = existing_tenant_id
            invite_role = invite_row.role
            await session.execute(
                text("UPDATE tenant_invites SET used_at = now() WHERE id = :id"), {"id": invite_row.id}
            )
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
        # First person into a brand-new tenant is its admin; anyone joining an existing
        # tenant gets exactly the role their invite specified — never a silent upgrade.
        assigned_role = invite_role or "admin"

        await session.execute(
            text("SELECT set_config('app.current_tenant_id', :tenant_id, true)"),
            {"tenant_id": tenant_id}
        )

        await session.execute(
            text("""
                INSERT INTO users (id, tenant_id, email, hashed_password, full_name, role)
                VALUES (:id, :tenant_id, :email, :hashed_pwd, :full_name, :role)
            """),
            {
                "id": user_id,
                "tenant_id": tenant_id,
                "email": req.email.lower().strip(),
                "hashed_pwd": hashed_pwd,
                "full_name": req.full_name,
                "role": assigned_role,
            },
        )
        await session.commit()

        # Issue production JWT access token
        jwt_token = jwt_engine.create_access_token(
            tenant_id=tenant_id,
            user_id=user_id,
            email=req.email,
            role=assigned_role,
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
        # bcrypt hashes are salted per-password, so unlike the old SHA-256 scheme we
        # can't compare hashes in SQL — fetch by email, then verify in Python.
        res_user = await session.execute(
            text("""
                SELECT u.id, u.tenant_id, u.email, t.name, u.role, u.hashed_password
                FROM users u
                JOIN tenants t ON u.tenant_id = t.id
                WHERE u.email = :email
            """),
            {"email": req.email.lower().strip()},
        )
        user = res_user.fetchone()

        if not user or not verify_password(req.password, user[5]):
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


@router.get("/me", response_model=ProfileResponse)
async def get_my_profile(token=Depends(require_authenticated_tenant)):
    """Real self-service profile read, for the Settings UI to prefill its form.
    Built 2026-08-31 — no Settings UI existed at all before this; not a rebuild
    of anything, this endpoint (and change-password/update-profile below) are
    entirely new surface area."""
    async with async_session_factory() as session:
        await session.execute(text("SELECT set_config('app.current_tenant_id', :tid, true)"), {"tid": token["tenant_id"]})
        res = await session.execute(
            text("SELECT email, full_name, department, role FROM users WHERE id = :uid AND tenant_id = :tid"),
            {"uid": token["user_id"], "tid": token["tenant_id"]},
        )
        row = res.fetchone()
        if not row:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
        return ProfileResponse(
            user_id=token["user_id"], tenant_id=token["tenant_id"],
            email=row.email, full_name=row.full_name, department=row.department,
            role=row.role or "member",
        )


@router.patch("/profile", response_model=ProfileResponse)
async def update_my_profile(req: UpdateProfileRequest, token=Depends(require_authenticated_tenant)):
    """Real self-service profile update — a user can change their own display
    name/department. Deliberately does NOT accept role or email here: role
    changes stay gated through the existing real admin-only role-management
    flow (admin.html), and email is the login identity, changed nowhere in
    this codebase today — both are out of scope for this endpoint, not
    overlooked."""
    if req.full_name is None and req.department is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Nothing to update.")
    async with async_session_factory() as session:
        await session.execute(text("SELECT set_config('app.current_tenant_id', :tid, true)"), {"tid": token["tenant_id"]})
        res = await session.execute(
            text("""
                UPDATE users SET
                    full_name = COALESCE(:full_name, full_name),
                    department = COALESCE(:department, department),
                    updated_at = now()
                WHERE id = :uid AND tenant_id = :tid
                RETURNING email, full_name, department, role
            """),
            {"full_name": req.full_name, "department": req.department, "uid": token["user_id"], "tid": token["tenant_id"]},
        )
        row = res.fetchone()
        if not row:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
        await session.commit()
        return ProfileResponse(
            user_id=token["user_id"], tenant_id=token["tenant_id"],
            email=row.email, full_name=row.full_name, department=row.department,
            role=row.role or "member",
        )


@router.post("/change-password")
async def change_password(req: ChangePasswordRequest, token=Depends(require_authenticated_tenant)):
    """Real self-service password change. Requires the real current password
    (not just a valid session) before allowing a new one — same principle as
    every other real credential-change flow in this codebase (MCP key
    creation requires an authenticated tenant; this requires proving you
    still are the account holder, not just that your JWT hasn't expired
    yet). Reuses the exact same bcrypt hash/verify functions signup and
    login already use — no new crypto primitive introduced."""
    if len(req.new_password) < 8:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="New password must be at least 8 characters.")
    if req.new_password == req.current_password:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="New password must be different from your current password.")

    async with async_session_factory() as session:
        await session.execute(text("SELECT set_config('app.current_tenant_id', :tid, true)"), {"tid": token["tenant_id"]})
        res = await session.execute(
            text("SELECT hashed_password FROM users WHERE id = :uid AND tenant_id = :tid"),
            {"uid": token["user_id"], "tid": token["tenant_id"]},
        )
        row = res.fetchone()
        if not row:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found.")
        if not verify_password(req.current_password, row.hashed_password):
            # Real bug found via live end-to-end testing 2026-08-31: 401 here
            # collided with the frontend's global authFetch() 401-handler,
            # which treats ANY 401 as "your session token is invalid" and
            # force-clears real auth state + reloads the page — a user who
            # simply mistyped their CURRENT password once got silently logged
            # out instead of seeing an inline "incorrect password" message.
            # This is a business-logic rejection of provided credentials, not
            # an invalid/expired session — 400, not 401.
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect.")

        new_hash = hash_password(req.new_password)
        await session.execute(
            text("UPDATE users SET hashed_password = :h, updated_at = now() WHERE id = :uid AND tenant_id = :tid"),
            {"h": new_hash, "uid": token["user_id"], "tid": token["tenant_id"]},
        )
        await session.commit()

    return {"status": "success", "message": "Password changed successfully."}
