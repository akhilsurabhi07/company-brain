from typing import List, Optional, Tuple
from app.connectors.base import Connector, OAuthToken, RawResource, ACLData, GraphNode, GraphEdge
from app.connectors.registry import ConnectorRegistry

@ConnectorRegistry.register("jira")
class JiraConnector(Connector):
    """Jira Issue & Ticket Connector."""

    @property
    def source_app(self) -> str:
        return "jira"

    async def authenticate(self, tenant_id: str, code: str) -> OAuthToken:
        return OAuthToken(
            access_token=f"jira_mock_token_{code}",
            scopes=["read:jira-work", "read:jira-user"]
        )

    async def list_resources(
        self,
        token: OAuthToken,
        cursor: Optional[str] = None,
        limit: int = 100
    ) -> Tuple[List[RawResource], Optional[str]]:
        mock_resource = RawResource(
            tenant_id="tenant_default",
            source_app="jira",
            resource_category="ticket",
            resource_type="issue",
            external_id="issue_PROJ-101",
            title="PROJ-101: Configure Multi-Tenant Row Level Security in Postgres",
            content="Ensure all database sessions execute SET LOCAL app.current_tenant_id before running queries.",
            raw_payload={
                "id": "issue_PROJ-101",
                "key": "PROJ-101",
                "summary": "Configure Multi-Tenant Row Level Security in Postgres",
                "creator": "reporter_dev",
                "assignee": "assignee_dev"
            }
        )
        return [mock_resource], None

    async def fetch_permissions(self, token: OAuthToken, resource: RawResource) -> List[ACLData]:
        return [
            ACLData(principal_type="group", principal_external_id="product_team", permission="read")
        ]

    def extract_graph(self, resource: RawResource) -> Tuple[List[GraphNode], List[GraphEdge]]:
        creator = resource.raw_payload.get("creator", "unknown")
        nodes = [
            GraphNode(id=resource.external_id, label="Document", properties={"title": resource.title, "app": "jira"}),
            GraphNode(id=creator, label="Person", properties={"handle": creator})
        ]
        edges = [
            GraphEdge(from_node_id=resource.external_id, to_node_id=creator, label="AUTHORED_BY")
        ]
        return nodes, edges
