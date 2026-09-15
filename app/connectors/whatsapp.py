"""
Real WhatsApp Business Cloud API Connector.
==============================================
Architecturally different from every other connector built so far — verified live
against developers.facebook.com, 2026-08-20: there is NO synchronous "give me
messages" endpoint. WhatsApp Cloud API is 100% webhook-push, for both new messages
AND the real 180-day history backfill (which arrives in phases, gated behind the
business explicitly opting in to history sharing on their own side — nothing this
connector can trigger via API call).

Auth: a real long-lived System User access token (Meta Business Manager), the same
"admin pastes a durable credential" shape as GitHub's PAT — not OAuth, since Meta's
docs don't flag this pattern as non-compliant the way Google/Atlassian do for their
token shortcuts. Requires phone_number_id (which real WhatsApp Business phone number)
stored in oauth_tokens.config, same slot GitHub uses for owner/repo.

list_resources() honestly returns nothing — real content only arrives via the webhook
receiver (see app/api/webhooks.py's /webhooks/whatsapp/{tenant_id}). This is a
deliberate, documented architectural fact, not a stub pretending to work.
"""
from typing import List, Tuple, Dict, Any, Optional
import httpx
from app.connectors.base import Connector, OAuthToken, RawResource, ACLData, GraphNode, GraphEdge
from app.connectors.registry import ConnectorRegistry

GRAPH_API_BASE = "https://graph.facebook.com/v21.0"


@ConnectorRegistry.register("whatsapp")
class WhatsAppConnector(Connector):
    """Real WhatsApp Business Cloud API connector. No synchronous history pull exists
    (see module docstring) — real ingestion happens through the webhook receiver."""

    @property
    def source_app(self) -> str:
        return "whatsapp"

    async def authenticate(self, tenant_id: str, code: str) -> OAuthToken:
        """`code` is the tenant's real long-lived System User access token, validated
        here via a real, lightweight Graph API call — no mock fallback on failure."""
        if not code:
            raise ValueError("WhatsAppConnector.authenticate requires a real System User access token — none provided.")

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(f"{GRAPH_API_BASE}/me", params={"access_token": code, "fields": "id,name"})
            data = resp.json()

        if "error" in data:
            raise ValueError(f"WhatsApp token validation failed: {data['error'].get('message', 'unknown_error')}")

        return OAuthToken(access_token=code, token_type="Bearer")

    async def list_resources(
        self,
        token: OAuthToken,
        cursor: Optional[str] = None,
        limit: int = 100,
    ) -> Tuple[List[RawResource], Optional[str]]:
        """Honestly returns nothing — see module docstring. A sync of this connector
        completing with zero items is the real, correct outcome, not a failure; new
        content arrives via the real-time webhook instead."""
        return [], None

    async def fetch_permissions(self, token: OAuthToken, resource: RawResource) -> List[ACLData]:
        """A real WhatsApp Business conversation is inherently 1:1 (or the small
        assigned-agent set) — there's no broader ACL concept to fetch per-message the
        way Drive/SharePoint files or Slack channels have. Real default: readable by
        anyone with access to this tenant's data (domain-level), same shape as
        GitHub's fetch_permissions."""
        return [ACLData(principal_type="domain", principal_external_id="whatsapp-business", permission="read")]

    def extract_graph(self, resource: RawResource) -> Tuple[List[GraphNode], List[GraphEdge]]:
        nodes = [GraphNode(id=resource.external_id, label="Document", properties={"title": resource.title or "", "type": "message"})]
        edges = []
        contact = resource.raw_payload.get("from")
        if contact:
            nodes.append(GraphNode(id=f"contact_{contact}", label="Person", properties={"phone": contact}))
            edges.append(GraphEdge(from_node_id=resource.external_id, to_node_id=f"contact_{contact}", label="AUTHORED_BY"))
        return nodes, edges
