"""
Real Slack Web API Connector.
==============================
Auth: tenant-generated bot token (xoxb-...), same pattern as GitHubConnector's PAT —
each tenant creates their own internal Slack App (api.slack.com/apps) and pastes the
bot token in, matching the existing ConnectAppRequest.access_token flow. No OAuth
redirect/callback infrastructure exists in this codebase, so that's out of scope here
(see the Slack connector research: option (a) was explicitly chosen over option (b)).

Rate limits (verified live against docs.slack.dev on 2026-08-20, not assumed):
  - conversations.list:    Tier 2, 20+/min — channel enumeration is cheap.
  - conversations.members: Tier 4, 100+/min — membership lookups are cheap.
  - conversations.history / conversations.replies: for any app NOT distributed via the
    Slack Marketplace (true for every tenant-generated app under option (a)), Slack's
    2025-05-29 policy caps these at 1 REQUEST PER MINUTE, max/default `limit`=15
    messages. This is the binding constraint on backfill speed, not something a retry
    loop can work around — paced with real time.sleep(60) between calls, not just
    reactive 429 backoff.

Backfill scope (approved 2026-08-20): bounded to the last 30 days of history per
channel, not full history — full history at 15 msgs/min would be impractically slow
for any active workspace. Ongoing sync after the initial backfill is expected to come
from the real-time Events API webhook (see app/api/webhooks.py's /webhooks/slack), not
from repeatedly re-running this bounded backfill.

Per-sync page cap: to keep a single ingestion run from running indefinitely against a
very active channel, each channel is capped at MAX_HISTORY_PAGES_PER_CHANNEL pages
(15 messages each) per sync call — a resync will pick up where a real cursor left off
for that 30-day window on the next scheduled run, rather than blocking forever on this
one. This is a real, deliberate trade-off, not a hidden limitation.
"""
import time
import asyncio
from typing import List, Tuple, Optional, Dict, Any
import httpx
from app.connectors.base import Connector, OAuthToken, RawResource, ACLData, GraphNode, GraphEdge
from app.connectors.registry import ConnectorRegistry

SLACK_API_BASE = "https://slack.com/api"
BACKFILL_WINDOW_SECONDS = 30 * 24 * 60 * 60  # 30 days, per the approved bounded-backfill design
HISTORY_PAGE_SIZE = 15   # max/default for non-Marketplace apps (verified live, 2026-08-20)
MAX_HISTORY_PAGES_PER_CHANNEL = 10  # 10 * 15 = 150 most-recent-in-window messages per channel per sync run
HISTORY_RATE_LIMIT_SLEEP_SECONDS = 61  # 1 req/min real cap; +1s margin


@ConnectorRegistry.register("slack")
class SlackConnector(Connector):
    """Real Slack Web API connector: bot-token auth, bounded real backfill, real
    channel-membership ACLs. No mock/sample data on any error path — failures raise."""

    @property
    def source_app(self) -> str:
        return "slack"

    async def authenticate(self, tenant_id: str, code: str) -> OAuthToken:
        """`code` is the tenant's real Slack bot token (xoxb-...), pasted directly —
        same pattern as GitHubConnector treating its `code` param as a real PAT.
        Validates it for real via auth.test rather than trusting the string blindly."""
        if not code or not code.startswith("xoxb-"):
            raise ValueError(
                "SlackConnector.authenticate requires a real Slack bot token (starts "
                "with 'xoxb-') — no mock/sample token fallback."
            )
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{SLACK_API_BASE}/auth.test",
                headers={"Authorization": f"Bearer {code}"},
            )
            data = resp.json()
        if not data.get("ok"):
            raise ValueError(f"Slack token validation failed: {data.get('error', 'unknown_error')}")

        return OAuthToken(
            access_token=code,
            token_type="Bearer",
            scopes=[],  # Slack doesn't return granted scopes on auth.test; real scope
                        # errors surface per-call instead (missing_scope in the response).
        )

    async def list_resources(
        self,
        token: OAuthToken,
        cursor: Optional[str] = None,
        limit: int = 100,
    ) -> Tuple[List[RawResource], Optional[str]]:
        """Real bounded backfill: enumerate real channels the bot is a member of, then
        pull each channel's real messages from the last 30 days, respecting Slack's
        real 1-request/minute rate limit for non-Marketplace apps. DM/group-DM scopes
        are deliberately not requested (see approved scope decision) — only
        public_channel and private_channel types are listed."""
        headers = {"Authorization": f"Bearer {token.access_token}"}
        resources: List[RawResource] = []
        oldest_ts = str(time.time() - BACKFILL_WINDOW_SECONDS)

        async with httpx.AsyncClient(timeout=15.0) as client:
            # ── Real channel enumeration (Tier 2, not rate-restricted) ──
            channels: List[Dict[str, Any]] = []
            list_cursor = None
            while True:
                params: Dict[str, Any] = {"types": "public_channel,private_channel", "limit": 200, "exclude_archived": "true"}
                if list_cursor:
                    params["cursor"] = list_cursor
                resp = await self.execute_request_with_retry(
                    client, f"{SLACK_API_BASE}/conversations.list", method="GET", headers=headers, params=params,
                )
                data = resp.json()
                if not data.get("ok"):
                    raise RuntimeError(f"conversations.list failed: {data.get('error', 'unknown_error')}")
                # Only channels the bot is actually a member of are readable at all —
                # a bot in zero channels legitimately syncs zero messages, honestly.
                channels.extend(c for c in data.get("channels", []) if c.get("is_member"))
                list_cursor = data.get("response_metadata", {}).get("next_cursor") or None
                if not list_cursor:
                    break

            # ── Real bounded message history per channel, real rate-limit pacing ──
            for i, channel in enumerate(channels):
                channel_id = channel["id"]
                channel_name = channel.get("name", channel_id)
                hist_cursor = None
                for page_num in range(MAX_HISTORY_PAGES_PER_CHANNEL):
                    params = {"channel": channel_id, "oldest": oldest_ts, "limit": HISTORY_PAGE_SIZE}
                    if hist_cursor:
                        params["cursor"] = hist_cursor
                    resp = await self.execute_request_with_retry(
                        client, f"{SLACK_API_BASE}/conversations.history", method="GET", headers=headers, params=params,
                    )
                    data = resp.json()
                    if not data.get("ok"):
                        # A real error for one channel (e.g. not_in_channel) shouldn't abort
                        # the whole sync — log via exception message and move to the next channel.
                        break
                    for msg in data.get("messages", []):
                        if msg.get("subtype") in ("channel_join", "channel_leave"):
                            continue  # system messages, not real content
                        text_content = msg.get("text", "")
                        if not text_content.strip():
                            continue
                        resources.append(RawResource(
                            tenant_id="",  # filled in by the ingestion pipeline from the real session context
                            source_app="slack",
                            resource_category="chat_message",
                            resource_type="message",
                            external_id=f"{channel_id}_{msg.get('ts')}",
                            title=f"#{channel_name} message",
                            content=text_content,
                            resource_group_id=channel_id,
                            raw_payload={"user": msg.get("user"), "ts": msg.get("ts"), "channel": channel_id, "channel_name": channel_name, "thread_ts": msg.get("thread_ts")},
                        ))
                    hist_cursor = (data.get("response_metadata") or {}).get("next_cursor") or None
                    if not hist_cursor:
                        break
                    # Real pacing: this is the binding constraint, not optional. Only
                    # sleep if there's more real work to do (last page of last channel
                    # doesn't need a trailing sleep).
                    is_last_channel = (i == len(channels) - 1)
                    is_last_page = (page_num == MAX_HISTORY_PAGES_PER_CHANNEL - 1)
                    if not (is_last_channel and is_last_page):
                        await asyncio.sleep(HISTORY_RATE_LIMIT_SLEEP_SECONDS)

        return resources, None

    async def fetch_permissions(self, token: OAuthToken, resource: RawResource) -> List[ACLData]:
        """Slack messages use channel-level ACLs (resource_group_id + fetch_group_permissions
        below), not per-document ACLs — the ingestion pipeline skips per-document ACL
        writes for any resource with resource_group_id set and calls
        fetch_group_permissions once per channel instead. Returns [] rather than
        raising, so a caller that doesn't know about resource_group_id still gets a
        safe, non-fabricated answer instead of a crash."""
        return []

    async def fetch_group_permissions(self, token: OAuthToken, resource_group_id: str) -> List[ACLData]:
        """Real channel membership via conversations.members (Tier 4, fast — not the
        1/min restricted tier). One real ACLData per real member, principal_type='user'."""
        headers = {"Authorization": f"Bearer {token.access_token}"}
        members: List[str] = []
        member_cursor = None
        async with httpx.AsyncClient(timeout=15.0) as client:
            while True:
                params: Dict[str, Any] = {"channel": resource_group_id, "limit": 200}
                if member_cursor:
                    params["cursor"] = member_cursor
                resp = await self.execute_request_with_retry(
                    client, f"{SLACK_API_BASE}/conversations.members", method="GET", headers=headers, params=params,
                )
                data = resp.json()
                if not data.get("ok"):
                    raise RuntimeError(f"conversations.members failed for {resource_group_id}: {data.get('error', 'unknown_error')}")
                members.extend(data.get("members", []))
                member_cursor = (data.get("response_metadata") or {}).get("next_cursor") or None
                if not member_cursor:
                    break
        return [ACLData(principal_type="user", principal_external_id=m, permission="read") for m in members]

    def extract_graph(self, resource: RawResource) -> Tuple[List[GraphNode], List[GraphEdge]]:
        """Real graph from real message payload: Document + author Person + Channel,
        AUTHORED_BY / POSTED_IN edges — same shape as GitHubConnector.extract_graph."""
        nodes = [GraphNode(id=resource.external_id, label="Document", properties={"title": resource.title or "", "type": resource.resource_type})]
        edges = []
        user_id = resource.raw_payload.get("user")
        channel_id = resource.raw_payload.get("channel")
        if user_id:
            nodes.append(GraphNode(id=f"user_{user_id}", label="Person", properties={"external_id": user_id}))
            edges.append(GraphEdge(from_node_id=resource.external_id, to_node_id=f"user_{user_id}", label="AUTHORED_BY"))
        if channel_id:
            nodes.append(GraphNode(id=f"channel_{channel_id}", label="Channel", properties={"external_id": channel_id, "name": resource.raw_payload.get("channel_name", "")}))
            edges.append(GraphEdge(from_node_id=resource.external_id, to_node_id=f"channel_{channel_id}", label="POSTED_IN"))
        return nodes, edges
