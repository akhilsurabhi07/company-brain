from typing import List, Tuple, Dict, Any, Optional
from app.connectors.base import Connector, OAuthToken, RawResource, ACLData, GraphNode, GraphEdge
from app.connectors.registry import ConnectorRegistry

@ConnectorRegistry.register("teams")
class TeamsConnector(Connector):
    """Microsoft Teams Graph API Connector Archetype Plugin."""

    @property
    def source_app(self) -> str:
        return "teams"

    async def authenticate(self, tenant_id: str, code: str) -> OAuthToken:
        return OAuthToken(
            access_token=f"teams_token_{code[:8]}",
            refresh_token="teams_refresh_mock",
        )

    async def list_resources(
        self,
        token: OAuthToken,
        cursor: Optional[str] = None,
        limit: int = 100
    ) -> Tuple[List[RawResource], Optional[str]]:
        raw_msg = {
            "id": "teams_msg_9001",
            "body": {"content": "Architecture sync transcript in General channel."},
            "from": {"user": {"displayName": "Engineering Manager"}}
        }
        res = RawResource(
            tenant_id="00000000-0000-0000-0000-000000000001",
            source_app=self.source_app,
            resource_category="chat_message",
            resource_type="message",
            external_id="teams_msg_9001",
            title="Teams Channel Chat: Architecture Sync",
            content="Architecture sync transcript in General channel.",
            raw_payload=raw_msg,
        )
        return [res], None

    async def fetch_permissions(self, token: OAuthToken, resource: RawResource) -> List[ACLData]:
        return [ACLData(principal_type="public", principal_external_id="everyone", permission="read")]

    def extract_graph(self, resource: RawResource) -> Tuple[List[GraphNode], List[GraphEdge]]:
        node = GraphNode(id=resource.external_id, label="Document", properties={"title": resource.title or ""})
        return [node], []
