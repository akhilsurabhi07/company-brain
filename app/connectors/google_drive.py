from typing import List, Optional, Tuple
from app.connectors.base import Connector, OAuthToken, RawResource, ACLData, GraphNode, GraphEdge
from app.connectors.registry import ConnectorRegistry

@ConnectorRegistry.register("google_drive")
class GoogleDriveConnector(Connector):
    """Google Drive Workplace Connector."""

    @property
    def source_app(self) -> str:
        return "google_drive"

    async def authenticate(self, tenant_id: str, code: str) -> OAuthToken:
        return OAuthToken(
            access_token=f"ya29.mock-drive-token-{code}",
            scopes=["https://www.googleapis.com/auth/drive.readonly"]
        )

    async def list_resources(
        self,
        token: OAuthToken,
        cursor: Optional[str] = None,
        limit: int = 100
    ) -> Tuple[List[RawResource], Optional[str]]:
        mock_resource = RawResource(
            tenant_id="tenant_default",
            source_app="google_drive",
            resource_category="doc",
            resource_type="file",
            external_id="file_gdrive_2002",
            title="Q3 Strategy Roadmap.pdf",
            content="Q3 Company Goals: Scale data ingestion to 10+ workplace connectors and ensure SOC 2 compliance.",
            mime_type="application/pdf",
            raw_payload={
                "id": "file_gdrive_2002",
                "name": "Q3 Strategy Roadmap.pdf",
                "mimeType": "application/pdf",
                "owners": [{"emailAddress": "alice@company.com"}]
            }
        )
        return [mock_resource], None

    async def fetch_permissions(self, token: OAuthToken, resource: RawResource) -> List[ACLData]:
        return [
            ACLData(principal_type="domain", principal_external_id="company.com", permission="read")
        ]

    def extract_graph(self, resource: RawResource) -> Tuple[List[GraphNode], List[GraphEdge]]:
        owner_email = resource.raw_payload.get("owners", [{}])[0].get("emailAddress", "unknown")
        nodes = [
            GraphNode(id=resource.external_id, label="Document", properties={"title": resource.title, "app": "google_drive"}),
            GraphNode(id=owner_email, label="Person", properties={"email": owner_email})
        ]
        edges = [
            GraphEdge(from_node_id=resource.external_id, to_node_id=owner_email, label="AUTHORED_BY")
        ]
        return nodes, edges
