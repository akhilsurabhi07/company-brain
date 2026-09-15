"""
Real Microsoft Graph API SharePoint Connector.
=================================================
Auth: real OAuth 2.0 delegated permissions — see app/api/microsoft_oauth_router.py.
`code` passed to authenticate() is the tenant's stored refresh_token.

Honesty note: unlike Atlassian (verified to rotate refresh tokens) and Google
(verified NOT to), I did not find explicit live documentation confirming Microsoft's
exact rotation behavior for this flow. Rather than assert either way, authenticate()
defensively returns whatever refresh_token comes back in the response (falling back
to the original if the response omits one) — ingestion_router.py's existing generic
"persist if it changed" logic (built for Jira) handles either case safely.

Bounded scope (same philosophy as Drive/Slack): MAX_FILES_PER_SYNC caps a single run;
folder traversal is capped at one level of recursion, not a full deep crawl.
"""
from typing import List, Tuple, Optional, Dict, Any
import httpx
from app.connectors.base import Connector, OAuthToken, RawResource, ACLData, GraphNode, GraphEdge
from app.connectors.registry import ConnectorRegistry
from app.config import settings

MS_TOKEN_ENDPOINT = "https://login.microsoftonline.com/common/oauth2/v2.0/token"
GRAPH_API_BASE = "https://graph.microsoft.com/v1.0"
MAX_FILES_PER_SYNC = 200


@ConnectorRegistry.register("sharepoint")
class SharePointConnector(Connector):
    """Real SharePoint connector via Microsoft Graph: OAuth refresh-token auth, real
    site discovery + drive traversal, real per-file permissions. No mock/sample data
    on any error path."""

    @property
    def source_app(self) -> str:
        return "sharepoint"

    async def authenticate(self, tenant_id: str, code: str) -> OAuthToken:
        if not code:
            raise ValueError("SharePointConnector.authenticate requires a real stored refresh_token — none provided.")
        if not settings.MICROSOFT_OAUTH_CLIENT_ID or not settings.MICROSOFT_OAUTH_CLIENT_SECRET:
            raise ValueError("Microsoft OAuth is not configured on this server (MICROSOFT_OAUTH_CLIENT_ID/SECRET missing).")

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(MS_TOKEN_ENDPOINT, data={
                "client_id": settings.MICROSOFT_OAUTH_CLIENT_ID,
                "client_secret": settings.MICROSOFT_OAUTH_CLIENT_SECRET,
                "refresh_token": code,
                "grant_type": "refresh_token",
                "scope": "offline_access Files.Read.All Sites.Read.All",
            })
            data = resp.json()

        if "access_token" not in data:
            raise ValueError(f"Microsoft token refresh failed: {data.get('error_description', data.get('error', 'unknown_error'))}")

        # See module docstring — defensive either-way handling of refresh_token rotation.
        new_refresh_token = data.get("refresh_token", code)
        return OAuthToken(access_token=data["access_token"], refresh_token=new_refresh_token, token_type="Bearer")

    async def _list_drive_children(self, client: httpx.AsyncClient, headers: dict, site_id: str, item_url: str, depth: int) -> List[Dict[str, Any]]:
        """One bounded level of real recursion into subfolders."""
        resp = await self.execute_request_with_retry(client, item_url, method="GET", headers=headers)
        data = resp.json()
        items = data.get("value", [])
        files = [it for it in items if "file" in it]
        if depth > 0:
            for folder_item in items:
                if "folder" in folder_item:
                    children_url = f"{GRAPH_API_BASE}/sites/{site_id}/drive/items/{folder_item['id']}/children"
                    files.extend(await self._list_drive_children(client, headers, site_id, children_url, depth - 1))
        return files

    async def list_resources(
        self,
        token: OAuthToken,
        cursor: Optional[str] = None,
        limit: int = 100,
    ) -> Tuple[List[RawResource], Optional[str]]:
        headers = {"Authorization": f"Bearer {token.access_token}"}
        resources: List[RawResource] = []

        async with httpx.AsyncClient(timeout=30.0) as client:
            sites_resp = await self.execute_request_with_retry(
                client, f"{GRAPH_API_BASE}/sites", method="GET", headers=headers, params={"search": "*"},
            )
            sites = sites_resp.json().get("value", [])

            for site in sites:
                if len(resources) >= MAX_FILES_PER_SYNC:
                    break
                site_id = site["id"]
                try:
                    files = await self._list_drive_children(
                        client, headers, site_id, f"{GRAPH_API_BASE}/sites/{site_id}/drive/root/children", depth=1,
                    )
                except Exception as ex:
                    print(f"[SharePoint] Failed to list drive for site {site.get('displayName', site_id)}: {ex}")
                    continue

                for f in files:
                    if len(resources) >= MAX_FILES_PER_SYNC:
                        break
                    try:
                        content_resp = await self.execute_request_with_retry(
                            client, f"{GRAPH_API_BASE}/sites/{site_id}/drive/items/{f['id']}/content",
                            method="GET", headers=headers,
                        )
                        from app.api.upload_router import extract_text_from_file
                        text_content = extract_text_from_file(f.get("name", "file"), content_resp.content)
                    except Exception as ex:
                        print(f"[SharePoint] Failed to download/extract file {f.get('id')} ({f.get('name')}): {ex}")
                        continue

                    if not text_content.strip():
                        continue

                    last_modified_by = ((f.get("lastModifiedBy") or {}).get("user")) or {}
                    resources.append(RawResource(
                        tenant_id="",
                        source_app="sharepoint",
                        resource_category="doc",
                        resource_type="file",
                        external_id=f["id"],
                        title=f.get("name", "Untitled"),
                        content=text_content,
                        raw_payload={
                            "site_id": site_id, "site_name": site.get("displayName", ""),
                            "modified_by_id": last_modified_by.get("id"), "modified_by_name": last_modified_by.get("displayName"),
                            "web_url": f.get("webUrl"),
                        },
                    ))

        return resources, None

    async def fetch_permissions(self, token: OAuthToken, resource: RawResource) -> List[ACLData]:
        """Real per-file permissions via driveItem permissions — SharePoint files
        genuinely have per-file ACLs (like Drive), so this uses document_acls directly."""
        headers = {"Authorization": f"Bearer {token.access_token}"}
        site_id = resource.raw_payload.get("site_id")
        if not site_id:
            return []

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await self.execute_request_with_retry(
                client, f"{GRAPH_API_BASE}/sites/{site_id}/drive/items/{resource.external_id}/permissions",
                method="GET", headers=headers,
            )
            data = resp.json()

        acls: List[ACLData] = []
        for p in data.get("value", []):
            granted = p.get("grantedToV2") or {}
            user = granted.get("user") or {}
            site_user = granted.get("siteUser") or {}
            principal_id = user.get("id") or site_user.get("loginName")
            if principal_id:
                acls.append(ACLData(principal_type="user", principal_external_id=principal_id, permission="read"))
            # A permission with only `link` (no grantedToV2) is link-based sharing —
            # skipped deliberately, same as Drive's "anyone" case, so the file falls
            # through to the default-open path rather than inventing a principal.
        return acls

    def extract_graph(self, resource: RawResource) -> Tuple[List[GraphNode], List[GraphEdge]]:
        nodes = [GraphNode(id=resource.external_id, label="Document", properties={"title": resource.title or "", "type": resource.resource_type})]
        edges = []
        modified_by_id = resource.raw_payload.get("modified_by_id")
        if modified_by_id:
            nodes.append(GraphNode(id=f"user_{modified_by_id}", label="Person", properties={"external_id": modified_by_id, "name": resource.raw_payload.get("modified_by_name", "")}))
            edges.append(GraphEdge(from_node_id=resource.external_id, to_node_id=f"user_{modified_by_id}", label="AUTHORED_BY"))
        site_id = resource.raw_payload.get("site_id")
        if site_id:
            nodes.append(GraphNode(id=f"site_{site_id}", label="Site", properties={"name": resource.raw_payload.get("site_name", "")}))
            edges.append(GraphEdge(from_node_id=f"site_{site_id}", to_node_id=resource.external_id, label="CONTAINS"))
        return nodes, edges
