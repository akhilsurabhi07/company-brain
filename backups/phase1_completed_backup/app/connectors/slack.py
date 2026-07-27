from typing import List, Optional, Tuple
from app.connectors.base import Connector, OAuthToken, RawResource, ACLData, GraphNode, GraphEdge
from app.connectors.registry import ConnectorRegistry

@ConnectorRegistry.register("slack")
class SlackConnector(Connector):
    """Slack Workplace Connector."""

    @property
    def source_app(self) -> str:
        return "slack"

    async def authenticate(self, tenant_id: str, code: str) -> OAuthToken:
        # Stub OAuth exchange logic
        return OAuthToken(
            access_token=f"xoxb-mock-slack-token-{code}",
            scopes=["channels:history", "users:read", "files:read"]
        )

    async def list_resources(
        self,
        token: OAuthToken,
        cursor: Optional[str] = None,
        limit: int = 100
    ) -> Tuple[List[RawResource], Optional[str]]:
        # Mock resource listing returning messages
        mock_resource = RawResource(
            tenant_id="tenant_default",
            source_app="slack",
            resource_category="chat_message",
            resource_type="message",
            external_id="msg_1001",
            title="Channel Message in #general",
            content="Hey team, let's review the Phase 1 architecture plan for Company Brain.",
            raw_payload={
                "type": "message",
                "user": "U12345",
                "text": "Hey team, let's review the Phase 1 architecture plan for Company Brain.",
                "ts": "1700000000.000100",
                "channel": "C98765"
            }
        )
        return [mock_resource], None

    async def fetch_permissions(self, token: OAuthToken, resource: RawResource) -> List[ACLData]:
        return [
            ACLData(principal_type="channel", principal_external_id=resource.raw_payload.get("channel", "public"), permission="read")
        ]

    def extract_graph(self, resource: RawResource) -> Tuple[List[GraphNode], List[GraphEdge]]:
        nodes = [
            GraphNode(id=resource.external_id, label="Document", properties={"title": resource.title, "app": "slack"}),
            GraphNode(id=resource.raw_payload["user"], label="Person", properties={"external_id": resource.raw_payload["user"]}),
            GraphNode(id=resource.raw_payload["channel"], label="Channel", properties={"external_id": resource.raw_payload["channel"]})
        ]
        edges = [
            GraphEdge(from_node_id=resource.external_id, to_node_id=resource.raw_payload["user"], label="AUTHORED_BY"),
            GraphEdge(from_node_id=resource.external_id, to_node_id=resource.raw_payload["channel"], label="POSTED_IN")
        ]
        return nodes, edges
