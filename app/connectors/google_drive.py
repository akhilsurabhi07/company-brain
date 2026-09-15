"""
Real Google Drive API v3 Connector.
=====================================
Auth: real OAuth 2.0 (see app/api/google_oauth_router.py — no PAT-style shortcut
exists for Drive, confirmed against Google's own docs 2026-08-20). The `code` param
authenticate() receives is the tenant's stored REFRESH TOKEN (long-lived, from the
one-time OAuth consent), which is exchanged here for a fresh short-lived access token
on every sync — access tokens expire in ~1 hour, refresh tokens don't, matching how
GitHub's PAT / Slack's bot token are "the stable credential re-validated every sync."

Bounded scope (same philosophy as the Slack connector): MAX_FILES_PER_SYNC caps a
single run rather than attempting a full historical backfill of an entire
organization's Drive in one pass.
"""
import io
import time
from typing import List, Tuple, Optional, Dict, Any
import httpx
from app.connectors.base import Connector, OAuthToken, RawResource, ACLData, GraphNode, GraphEdge
from app.connectors.registry import ConnectorRegistry
from app.config import settings

DRIVE_API_BASE = "https://www.googleapis.com/drive/v3"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
MAX_FILES_PER_SYNC = 200

# Native Google formats need a real export call with an explicit target mimeType —
# they have no raw file bytes to download directly.
GOOGLE_NATIVE_EXPORT_MIME = {
    "application/vnd.google-apps.document": "text/plain",
    "application/vnd.google-apps.spreadsheet": "text/csv",
    "application/vnd.google-apps.presentation": "text/plain",
}


@ConnectorRegistry.register("google_drive")
class GoogleDriveConnector(Connector):
    """Real Google Drive connector: OAuth refresh-token auth, real files.list/export/
    get, real permissions.list ACLs. No mock/sample data on any error path."""

    @property
    def source_app(self) -> str:
        return "google_drive"

    async def authenticate(self, tenant_id: str, code: str) -> OAuthToken:
        """`code` here is the stored refresh_token (see module docstring) — exchanged
        for a fresh access_token via Google's real token endpoint."""
        if not code:
            raise ValueError("GoogleDriveConnector.authenticate requires a real stored refresh_token — none provided.")
        if not settings.GOOGLE_OAUTH_CLIENT_ID or not settings.GOOGLE_OAUTH_CLIENT_SECRET:
            raise ValueError("Google OAuth is not configured on this server (GOOGLE_OAUTH_CLIENT_ID/SECRET missing).")

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(GOOGLE_TOKEN_ENDPOINT, data={
                "client_id": settings.GOOGLE_OAUTH_CLIENT_ID,
                "client_secret": settings.GOOGLE_OAUTH_CLIENT_SECRET,
                "refresh_token": code,
                "grant_type": "refresh_token",
            })
            data = resp.json()

        if "error" in data:
            raise ValueError(f"Google token refresh failed: {data.get('error_description', data['error'])}")

        return OAuthToken(access_token=data["access_token"], refresh_token=code, token_type="Bearer")

    async def list_resources(
        self,
        token: OAuthToken,
        cursor: Optional[str] = None,
        limit: int = 100,
    ) -> Tuple[List[RawResource], Optional[str]]:
        headers = {"Authorization": f"Bearer {token.access_token}"}
        resources: List[RawResource] = []

        async with httpx.AsyncClient(timeout=30.0) as client:
            page_token = None
            while len(resources) < MAX_FILES_PER_SYNC:
                params: Dict[str, Any] = {
                    "q": "trashed = false",
                    "pageSize": min(100, MAX_FILES_PER_SYNC - len(resources)),
                    "fields": "nextPageToken, files(id, name, mimeType, owners, modifiedTime, webViewLink, parents)",
                    "orderBy": "modifiedTime desc",
                }
                if page_token:
                    params["pageToken"] = page_token
                resp = await self.execute_request_with_retry(
                    client, f"{DRIVE_API_BASE}/files", method="GET", headers=headers, params=params,
                )
                data = resp.json()
                files = data.get("files", [])

                for f in files:
                    mime_type = f.get("mimeType", "")
                    export_mime = GOOGLE_NATIVE_EXPORT_MIME.get(mime_type)
                    text_content = ""
                    try:
                        if export_mime:
                            export_resp = await self.execute_request_with_retry(
                                client, f"{DRIVE_API_BASE}/files/{f['id']}/export",
                                method="GET", headers=headers, params={"mimeType": export_mime},
                            )
                            text_content = export_resp.text
                        elif mime_type.startswith("application/vnd.google-apps."):
                            # Other native types (forms, drawings, sites, ...) have no
                            # plain-text export path worth building yet — skip honestly
                            # rather than guess at a conversion.
                            continue
                        else:
                            # Real file — download raw bytes and reuse the same real
                            # extraction already proven in upload_router.py (PDF/DOCX/
                            # XLSX/images via OCR) instead of a third re-implementation.
                            media_resp = await self.execute_request_with_retry(
                                client, f"{DRIVE_API_BASE}/files/{f['id']}", method="GET",
                                headers=headers, params={"alt": "media"},
                            )
                            from app.api.upload_router import extract_text_from_file
                            text_content = extract_text_from_file(f.get("name", "file"), media_resp.content)
                    except Exception as ex:
                        print(f"[GoogleDrive] Failed to extract content for file {f.get('id')} ({f.get('name')}): {ex}")
                        continue

                    if not text_content.strip():
                        continue

                    owner = (f.get("owners") or [{}])[0]
                    resources.append(RawResource(
                        tenant_id="",
                        source_app="google_drive",
                        resource_category="doc",
                        resource_type="file",
                        external_id=f["id"],
                        title=f.get("name", "Untitled"),
                        content=text_content,
                        raw_payload={
                            "owner_email": owner.get("emailAddress"), "owner_name": owner.get("displayName"),
                            "mime_type": mime_type, "modified_time": f.get("modifiedTime"),
                            "parents": f.get("parents", []), "web_view_link": f.get("webViewLink"),
                        },
                    ))
                    if len(resources) >= MAX_FILES_PER_SYNC:
                        break

                page_token = data.get("nextPageToken")
                if not page_token or not files:
                    break

        return resources, None

    async def fetch_permissions(self, token: OAuthToken, resource: RawResource) -> List[ACLData]:
        """Real per-file permissions via permissions.list — Drive files (unlike Slack
        channels) genuinely do carry per-document ACLs, so this uses the existing
        document_acls per-document model directly, no resource_group_id needed."""
        headers = {"Authorization": f"Bearer {token.access_token}"}
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await self.execute_request_with_retry(
                client, f"{DRIVE_API_BASE}/files/{resource.external_id}/permissions",
                method="GET", headers=headers,
                params={"fields": "permissions(type, emailAddress, domain, role)"},
            )
            data = resp.json()

        acls: List[ACLData] = []
        for p in data.get("permissions", []):
            ptype = p.get("type")
            if ptype == "user" and p.get("emailAddress"):
                acls.append(ACLData(principal_type="user", principal_external_id=p["emailAddress"], permission="read"))
            elif ptype == "domain" and p.get("domain"):
                acls.append(ACLData(principal_type="domain", principal_external_id=p["domain"], permission="read"))
            # type == "anyone": genuinely public — deliberately return no ACL row for it
            # so the file falls through to the existing "no rows = open" default rather
            # than inventing a principal_type the enforcement logic doesn't check.
        return acls

    def extract_graph(self, resource: RawResource) -> Tuple[List[GraphNode], List[GraphEdge]]:
        nodes = [GraphNode(id=resource.external_id, label="Document", properties={"title": resource.title or "", "type": resource.resource_type})]
        edges = []
        owner_email = resource.raw_payload.get("owner_email")
        if owner_email:
            nodes.append(GraphNode(id=f"user_{owner_email}", label="Person", properties={"email": owner_email, "name": resource.raw_payload.get("owner_name", "")}))
            edges.append(GraphEdge(from_node_id=resource.external_id, to_node_id=f"user_{owner_email}", label="AUTHORED_BY"))
        for parent_id in resource.raw_payload.get("parents", []):
            nodes.append(GraphNode(id=f"folder_{parent_id}", label="Folder", properties={"external_id": parent_id}))
            edges.append(GraphEdge(from_node_id=f"folder_{parent_id}", to_node_id=resource.external_id, label="CONTAINS"))
        return nodes, edges
