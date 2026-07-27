from typing import List, Tuple, Dict, Any, Optional
from app.connectors.base import Connector, OAuthToken, RawResource, ACLData, GraphNode, GraphEdge
from app.connectors.registry import ConnectorRegistry

@ConnectorRegistry.register("whatsapp")
class WhatsAppConnector(Connector):
    """WhatsApp Business API Connector Archetype Plugin."""

    @property
    def source_app(self) -> str:
        return "whatsapp"

    async def authenticate(self, tenant_id: str, code: str) -> OAuthToken:
        return OAuthToken(
            access_token=f"whatsapp_token_{code[:8]}",
            refresh_token="whatsapp_refresh_mock",
        )

    async def list_resources(
        self,
        token: OAuthToken,
        cursor: Optional[str] = None,
        limit: int = 100
    ) -> Tuple[List[RawResource], Optional[str]]:
        raw_msg = {
            "entry": [{"id": "wa_biz_101", "changes": [{"value": {"messages": [{"id": "wamid.HBgL1001", "text": {"body": "Client requested proposal update via WhatsApp."}}]}}]}]
        }
        res = RawResource(
            tenant_id="default",
            source_app=self.source_app,
            resource_category="chat_message",
            resource_type="message",
            external_id="wamid_1001",
            title="WhatsApp Business Message from Client",
            content="Client requested proposal update via WhatsApp.",
            raw_payload=raw_msg,
        )
        return [res], None

    async def fetch_permissions(self, token: OAuthToken, resource: RawResource) -> List[ACLData]:
        return [ACLData(principal_type="public", principal_external_id="everyone", permission="read")]

    def extract_graph(self, resource: RawResource) -> Tuple[List[GraphNode], List[GraphEdge]]:
        node = GraphNode(id=resource.external_id, label="Document", properties={"title": resource.title or ""})
        return [node], []
