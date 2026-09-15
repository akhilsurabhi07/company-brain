import asyncio
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple
from pydantic import BaseModel, Field
import httpx

class OAuthToken(BaseModel):
    access_token: str
    refresh_token: Optional[str] = None
    token_type: str = "Bearer"
    scopes: List[str] = Field(default_factory=list)
    expires_at: Optional[str] = None

class RawResource(BaseModel):
    tenant_id: str
    source_app: str
    resource_category: str  # 'chat_message', 'doc', 'code_pr', 'ticket', 'video'
    resource_type: str      # 'message', 'file', 'pull_request', 'issue'
    external_id: str
    title: Optional[str] = None
    raw_payload: Dict[str, Any]
    content: Optional[str] = None
    mime_type: str = "application/json"
    file_bytes: Optional[bytes] = None
    file_extension: Optional[str] = None
    # When set, this resource's permission is governed by a channel/group-level ACL
    # (see resource_group_acls) instead of a per-document ACL — e.g. a Slack channel
    # ID. None (default) means "use per-document ACLs", matching every connector
    # before this field was added (GitHub, etc.) — zero behavior change for them.
    resource_group_id: Optional[str] = None

class ACLData(BaseModel):
    principal_type: str        # 'user', 'group', 'domain', 'public'
    principal_external_id: str
    permission: str = "read"   # 'read', 'write', 'admin'

class GraphNode(BaseModel):
    id: str
    label: str                 # 'Document', 'Person', 'Channel', 'Team'
    properties: Dict[str, Any]

class GraphEdge(BaseModel):
    from_node_id: str
    to_node_id: str
    label: str                 # 'AUTHORED_BY', 'POSTED_IN', 'MEMBER_OF', 'MENTIONED_IN', 'REPLIED_TO'
    properties: Dict[str, Any] = Field(default_factory=dict)

class Connector(ABC):
    """
    Standard Abstract Base Class interface that every workplace & dev connector implements.
    Includes built-in Exponential Backoff & Rate Limit (HTTP 429) retry handler.
    """

    @property
    @abstractmethod
    def source_app(self) -> str:
        """Returns the unique identifier string for the app."""
        pass

    async def execute_request_with_retry(
        self,
        client: httpx.AsyncClient,
        url: str,
        method: str = "GET",
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
        max_retries: int = 4,
    ) -> httpx.Response:
        """
        Improvement 4: Exponential Backoff & HTTP 429 Rate-Limit Retry Handler.
        Parses 'Retry-After' headers and retries with jitter when throttled.
        """
        attempt = 0
        backoff_delay = 1.0

        while attempt < max_retries:
            try:
                response = await client.request(method=method, url=url, headers=headers, params=params)

                if response.status_code == 429:
                    # Read Retry-After header if provided by Slack/GitHub/Google
                    retry_after = response.headers.get("Retry-After")
                    if retry_after and retry_after.isdigit():
                        sleep_time = float(retry_after)
                    else:
                        sleep_time = backoff_delay

                    print(f"[{self.source_app.upper()}] HTTP 429 Rate Limited. Backing off for {sleep_time:.1f}s (Attempt {attempt + 1}/{max_retries})...")
                    await asyncio.sleep(sleep_time)
                    backoff_delay *= 2.0  # Exponential backoff
                    attempt += 1
                    continue

                response.raise_for_status()
                return response

            except httpx.HTTPStatusError as err:
                if err.response.status_code == 429 and attempt < max_retries:
                    await asyncio.sleep(backoff_delay)
                    backoff_delay *= 2.0
                    attempt += 1
                    continue
                raise err
            except httpx.TransportError as err:
                if attempt < max_retries:
                    await asyncio.sleep(backoff_delay)
                    backoff_delay *= 2.0
                    attempt += 1
                    continue
                raise err

        # Final attempt
        response = await client.request(method=method, url=url, headers=headers, params=params)
        response.raise_for_status()
        return response

    @abstractmethod
    async def authenticate(self, tenant_id: str, code: str) -> OAuthToken:
        """Exchanges OAuth code or validates credentials for an OAuthToken."""
        pass

    @abstractmethod
    async def list_resources(
        self,
        token: OAuthToken,
        cursor: Optional[str] = None,
        limit: int = 100
    ) -> Tuple[List[RawResource], Optional[str]]:
        """Paginates through resources during backfill/sync."""
        pass

    @abstractmethod
    async def fetch_permissions(self, token: OAuthToken, resource: RawResource) -> List[ACLData]:
        """Fetches ACLs and access controls for a specific resource."""
        pass

    @abstractmethod
    def extract_graph(self, resource: RawResource) -> Tuple[List[GraphNode], List[GraphEdge]]:
        """Extracts graph nodes and relationships from raw resource."""
        pass

    async def subscribe_to_webhook(self, token: OAuthToken, callback_url: str) -> Dict[str, Any]:
        """Optional webhook registration if the app supports push events."""
        raise NotImplementedError(f"{self.source_app} does not support webhook subscription.")

    async def fetch_group_permissions(self, token: OAuthToken, resource_group_id: str) -> List[ACLData]:
        """Optional: for connectors whose resources use resource_group_id (channel-level
        ACLs) instead of per-document ACLs — fetches real membership for one group,
        called once per group per sync rather than once per resource. Connectors that
        don't use resource_group_id (return None from list_resources) never need this."""
        raise NotImplementedError(f"{self.source_app} does not support group-level permissions.")

    def extract_facts_and_decisions(self, resource: RawResource) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """Optional: real structured facts/decisions a resource genuinely represents
        (e.g. a merged PR is a real decision record — title, rationale, outcome).
        Returns (facts, decisions) as plain dicts matching FactModel/DecisionModel's
        fields (minus tenant_id, added by the caller). Default: nothing — most
        connectors' resources aren't naturally facts or decisions, and inventing one
        would be exactly the fabrication this whole system exists to avoid."""
        return [], []
