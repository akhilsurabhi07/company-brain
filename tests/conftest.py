"""
Shared test helpers.

auth_headers_for() mints a real, validly-signed JWT for a given tenant_id using the
same jwt_engine production code uses — not a fake/mocked token. Tests that create
their own test tenant directly via raw SQL (a common pattern in this suite, to get
a clean isolated tenant per test) can't go through the real HTTP /signup flow to get
a token for that specific tenant_id, since signup always creates a new tenant of its
own. Minting directly with jwt_engine is the correct equivalent: it's the exact same
signing path signup/login use, just invoked without the extra DB round-trip.
"""
from app.security.jwt_auth import jwt_engine


def auth_headers_for(tenant_id: str, user_id: str = "test_user", email: str = "test@example.com", role: str = "admin") -> dict:
    token = jwt_engine.create_access_token(tenant_id=str(tenant_id), user_id=user_id, email=email, role=role)
    return {"Authorization": f"Bearer {token}"}
