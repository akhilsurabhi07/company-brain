"""
Real test for the tenant invite system.

Signing up against an already-registered domain used to either silently grant admin
access (the original bug) or, after the fix, be rejected outright with no way for a
real admin to actually bring a teammate in. This is that real path: an admin creates
an invite scoped to one specific email + role; redeeming it joins that exact tenant
with that exact role — never admin by default, never usable by a different email,
never twice, never after it expires.
"""
import uuid
import httpx
import pytest
from sqlalchemy import text
from app.db.database import async_session_factory
from app.main import app


async def _signup(client, uid, invite_token=None, email=None, password="TestPass123!"):
    payload = {
        "company_name": f"Invite Test Co {uid}",
        "company_domain": f"invite-test-{uid}.example.com",
        "email": email or f"admin_{uid}@example.com",
        "password": password,
    }
    if invite_token:
        payload["invite_token"] = invite_token
    return await client.post("/api/v1/auth/signup", json=payload)


@pytest.mark.asyncio
async def test_admin_can_invite_and_teammate_can_join_with_correct_role():
    uid = str(uuid.uuid4())[:8]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        # Real admin signs up a brand-new workspace.
        admin_resp = await _signup(client, uid)
        assert admin_resp.status_code == 200
        admin_data = admin_resp.json()
        admin_token = admin_data["token"]
        tenant_id = admin_data["tenant_id"]

        teammate_email = f"teammate_{uid}@example.com"
        invite_resp = await client.post(
            "/api/v1/auth/invite",
            json={"email": teammate_email, "role": "member"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert invite_resp.status_code == 200
        invite_token = invite_resp.json()["invite_token"]

        # Teammate redeems it against the SAME domain.
        join_resp = await _signup(
            client, uid, invite_token=invite_token, email=teammate_email, password="TeammatePass123!"
        )
        assert join_resp.status_code == 200
        join_data = join_resp.json()
        assert join_data["tenant_id"] == tenant_id  # joined the real existing tenant, not a new one

        # The teammate's own token must reflect the invited role, not admin.
        async with async_session_factory() as session:
            await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": tenant_id})
            res = await session.execute(
                text("SELECT role FROM users WHERE email = :email"), {"email": teammate_email}
            )
            assert res.fetchone()[0] == "member"


@pytest.mark.asyncio
async def test_invite_cannot_be_redeemed_by_a_different_email():
    uid = str(uuid.uuid4())[:8]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        admin_resp = await _signup(client, uid)
        admin_token = admin_resp.json()["token"]

        invite_resp = await client.post(
            "/api/v1/auth/invite",
            json={"email": f"invited_{uid}@example.com", "role": "member"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        invite_token = invite_resp.json()["invite_token"]

        # A different person tries to use the same invite token.
        imposter_resp = await _signup(client, uid, invite_token=invite_token, email=f"imposter_{uid}@example.com")
        assert imposter_resp.status_code == 403


@pytest.mark.asyncio
async def test_invite_cannot_be_redeemed_twice():
    uid = str(uuid.uuid4())[:8]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        admin_resp = await _signup(client, uid)
        admin_token = admin_resp.json()["token"]
        teammate_email = f"teammate2_{uid}@example.com"

        invite_resp = await client.post(
            "/api/v1/auth/invite",
            json={"email": teammate_email, "role": "member"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        invite_token = invite_resp.json()["invite_token"]

        first = await _signup(client, uid, invite_token=invite_token, email=teammate_email)
        assert first.status_code == 200

        # Same token, different (new) email this time — still must fail, since the
        # token itself is now used, regardless of whose email it claims.
        second = await _signup(client, uid, invite_token=invite_token, email=f"another_{uid}@example.com")
        assert second.status_code == 403


@pytest.mark.asyncio
async def test_non_admin_cannot_create_invites():
    uid = str(uuid.uuid4())[:8]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        admin_resp = await _signup(client, uid)
        admin_token = admin_resp.json()["token"]
        member_email = f"member_{uid}@example.com"

        invite_resp = await client.post(
            "/api/v1/auth/invite",
            json={"email": member_email, "role": "member"},
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        member_join = await _signup(client, uid, invite_token=invite_resp.json()["invite_token"], email=member_email)
        member_token = member_join.json()["token"]

        # The member (not admin) tries to invite someone else.
        escalation_attempt = await client.post(
            "/api/v1/auth/invite",
            json={"email": f"friend_{uid}@example.com", "role": "admin"},
            headers={"Authorization": f"Bearer {member_token}"},
        )
        assert escalation_attempt.status_code == 403


@pytest.mark.asyncio
async def test_signup_without_invite_against_existing_domain_still_rejected():
    """The original fix must still hold: no invite_token at all still means 409, same
    as before this feature existed."""
    uid = str(uuid.uuid4())[:8]
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        await _signup(client, uid)
        second_attempt = await _signup(client, uid, email=f"uninvited_{uid}@example.com")
        assert second_attempt.status_code == 409
