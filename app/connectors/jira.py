"""
Real Jira Cloud REST API v3 Connector.
=========================================
Auth: real OAuth 2.0 (3LO) — see app/api/jira_oauth_router.py. `code` passed to
authenticate() is the tenant's stored refresh_token; Atlassian ROTATES refresh tokens
on every use (verified live, 2026-08-20 — different from Google, whose refresh tokens
don't rotate), so authenticate() returns the NEW refresh_token in OAuthToken and
ingestion_router.py persists it generically after every sync.

Permission model: real Jira issue visibility is governed by project roles, not a
per-issue ACL — closer to Slack's "channel membership" shape than Drive's "per-file
permission" shape. Uses resource_group_id = project key, same resource_group_acls
architecture built for Slack.

Pragmatic, scoped choice: cloudId (which Jira site) is needed by every API call but
isn't part of the abstract Connector interface's fetch_group_permissions/extract_graph
signatures. Stashed on the instance during list_resources() and read back in
fetch_group_permissions() — safe because ConnectorRegistry.get_connector() returns a
fresh instance per sync (see registry.py), so there's no cross-tenant state leakage.
"""
import time
from typing import List, Tuple, Optional, Dict, Any
import httpx
from app.connectors.base import Connector, OAuthToken, RawResource, ACLData, GraphNode, GraphEdge
from app.connectors.registry import ConnectorRegistry
from app.config import settings

ATLASSIAN_TOKEN_ENDPOINT = "https://auth.atlassian.com/oauth/token"
ATLASSIAN_API_BASE = "https://api.atlassian.com/ex/jira"
MAX_ISSUES_PER_SYNC = 200


def _adf_to_text(node: Any) -> str:
    """Real recursive Atlassian Document Format -> plain text extractor. Jira API v3
    returns issue descriptions as structured ADF JSON, not plain text — this walks the
    node tree collecting real text content rather than dumping raw JSON as 'content'."""
    if not isinstance(node, dict):
        return ""
    parts = []
    if node.get("type") == "text":
        parts.append(node.get("text", ""))
    for child in node.get("content", []) or []:
        child_text = _adf_to_text(child)
        if child_text:
            parts.append(child_text)
    joiner = "\n" if node.get("type") in ("paragraph", "heading", "listItem") else " "
    return joiner.join(p for p in parts if p)


@ConnectorRegistry.register("jira")
class JiraConnector(Connector):
    """Real Jira Cloud connector: OAuth 2.0 (3LO) with rotating-refresh-token auth,
    real JQL search, real project-role-based ACLs. No mock/sample data on any error path."""

    def __init__(self):
        self._cloud_id: Optional[str] = None

    @property
    def source_app(self) -> str:
        return "jira"

    async def authenticate(self, tenant_id: str, code: str) -> OAuthToken:
        """`code` is the stored refresh_token. Returns the ROTATED refresh_token —
        the caller (ingestion_router.py) must persist it, or the next sync fails."""
        if not code:
            raise ValueError("JiraConnector.authenticate requires a real stored refresh_token — none provided.")
        if not settings.JIRA_OAUTH_CLIENT_ID or not settings.JIRA_OAUTH_CLIENT_SECRET:
            raise ValueError("Jira OAuth is not configured on this server (JIRA_OAUTH_CLIENT_ID/SECRET missing).")

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(ATLASSIAN_TOKEN_ENDPOINT, json={
                "grant_type": "refresh_token",
                "client_id": settings.JIRA_OAUTH_CLIENT_ID,
                "client_secret": settings.JIRA_OAUTH_CLIENT_SECRET,
                "refresh_token": code,
            })
            data = resp.json()

        if "access_token" not in data:
            raise ValueError(f"Jira token refresh failed: {data.get('error_description', data.get('error', 'unknown_error'))}")

        new_refresh_token = data.get("refresh_token", code)  # Atlassian always rotates in practice, but fall back honestly if a response ever omits it
        return OAuthToken(access_token=data["access_token"], refresh_token=new_refresh_token, token_type="Bearer")

    async def list_resources(
        self,
        token: OAuthToken,
        cursor: Optional[str] = None,
        limit: int = 50,
        cloud_id: Optional[str] = None,
    ) -> Tuple[List[RawResource], Optional[str]]:
        if not cloud_id:
            raise ValueError("JiraConnector.list_resources requires a real cloud_id — there is no default Jira site to fall back to.")
        self._cloud_id = cloud_id

        headers = {"Authorization": f"Bearer {token.access_token}", "Accept": "application/json"}
        resources: List[RawResource] = []
        start_at = int(cursor) if cursor else 0

        async with httpx.AsyncClient(timeout=30.0) as client:
            while len(resources) < MAX_ISSUES_PER_SYNC:
                params = {
                    "jql": "ORDER BY updated DESC",
                    "startAt": start_at,
                    "maxResults": min(50, MAX_ISSUES_PER_SYNC - len(resources)),
                    "fields": "summary,description,project,issuetype,status,assignee,reporter,updated,resolution,resolutiondate",
                }
                resp = await self.execute_request_with_retry(
                    client, f"{ATLASSIAN_API_BASE}/{cloud_id}/rest/api/3/search",
                    method="GET", headers=headers, params=params,
                )
                data = resp.json()
                issues = data.get("issues", [])
                if not issues:
                    break

                for issue in issues:
                    fields = issue.get("fields", {})
                    summary = fields.get("summary", "")
                    description_text = _adf_to_text(fields.get("description")) if fields.get("description") else ""
                    content = f"{summary}\n\n{description_text}".strip()
                    if not content:
                        continue

                    project = fields.get("project", {})
                    assignee = fields.get("assignee") or {}
                    reporter = fields.get("reporter") or {}
                    resolution = fields.get("resolution") or {}

                    resources.append(RawResource(
                        tenant_id="",
                        source_app="jira",
                        resource_category="ticket",
                        resource_type="issue",
                        external_id=issue["key"],
                        title=f"{issue['key']}: {summary}",
                        content=content,
                        resource_group_id=project.get("key"),
                        raw_payload={
                            "project_key": project.get("key"), "project_name": project.get("name"),
                            "status": (fields.get("status") or {}).get("name"),
                            "assignee_account_id": assignee.get("accountId"), "assignee_name": assignee.get("displayName"),
                            "reporter_account_id": reporter.get("accountId"), "reporter_name": reporter.get("displayName"),
                            "updated": fields.get("updated"),
                            "resolution_name": resolution.get("name"), "resolution_date": fields.get("resolutiondate"),
                            "description_text": description_text,
                        },
                    ))
                    if len(resources) >= MAX_ISSUES_PER_SYNC:
                        break

                start_at += len(issues)
                if start_at >= data.get("total", 0):
                    break

        return resources, None

    async def fetch_permissions(self, token: OAuthToken, resource: RawResource) -> List[ACLData]:
        """Jira issues use project-role-based ACLs (resource_group_id), not per-issue
        ACLs — see fetch_group_permissions. Returns [] so the ingestion pipeline routes
        this connector's resources through the group-ACL path instead."""
        return []

    async def fetch_group_permissions(self, token: OAuthToken, resource_group_id: str) -> List[ACLData]:
        """Real project role membership via /project/{key}/role -> per-role actors.
        Only expands user-type actors directly; group-type actors are skipped (would
        need a further real API call per group to expand membership — a deliberate,
        scoped boundary, not a silent gap) rather than guessed at."""
        if not self._cloud_id:
            raise RuntimeError("fetch_group_permissions called before list_resources established a real cloud_id.")
        headers = {"Authorization": f"Bearer {token.access_token}", "Accept": "application/json"}
        acls: List[ACLData] = []
        seen_account_ids = set()

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await self.execute_request_with_retry(
                client, f"{ATLASSIAN_API_BASE}/{self._cloud_id}/rest/api/3/project/{resource_group_id}/role",
                method="GET", headers=headers,
            )
            role_urls = resp.json()  # {"Administrators": "https://.../role/10002", ...}

            for role_url in role_urls.values():
                role_resp = await self.execute_request_with_retry(client, role_url, method="GET", headers=headers)
                role_data = role_resp.json()
                for actor in role_data.get("actors", []):
                    if actor.get("type") == "atlassian-user-role-actor":
                        account_id = (actor.get("actorUser") or {}).get("accountId")
                        if account_id and account_id not in seen_account_ids:
                            seen_account_ids.add(account_id)
                            acls.append(ACLData(principal_type="user", principal_external_id=account_id, permission="read"))
        return acls

    def extract_graph(self, resource: RawResource) -> Tuple[List[GraphNode], List[GraphEdge]]:
        nodes = [GraphNode(id=resource.external_id, label="Document", properties={"title": resource.title or "", "type": "issue"})]
        edges = []
        assignee_id = resource.raw_payload.get("assignee_account_id")
        if assignee_id:
            nodes.append(GraphNode(id=f"user_{assignee_id}", label="Person", properties={"account_id": assignee_id, "name": resource.raw_payload.get("assignee_name", "")}))
            edges.append(GraphEdge(from_node_id=resource.external_id, to_node_id=f"user_{assignee_id}", label="ASSIGNED_TO"))
        project_key = resource.raw_payload.get("project_key")
        if project_key:
            nodes.append(GraphNode(id=f"project_{project_key}", label="Project", properties={"key": project_key, "name": resource.raw_payload.get("project_name", "")}))
            edges.append(GraphEdge(from_node_id=resource.external_id, to_node_id=f"project_{project_key}", label="BELONGS_TO_PROJECT"))
        return nodes, edges

    def extract_facts_and_decisions(self, resource: RawResource) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """A resolved issue is a real decision record. Gated on Jira's own real
        `resolution` field being set — not guessed from the (per-project customizable)
        status name — since Jira only sets resolution once a real outcome has actually
        been applied. An unresolved issue isn't a decision yet, so it's skipped
        honestly rather than assumed.

        Outcome mapping is a deliberate simplification, not exhaustive: "Done"/"Fixed"
        count as adopted; every other real Jira resolution (Won't Fix, Duplicate,
        Cannot Reproduce, Incomplete, ...) counts as not-adopted. Good enough to be
        real and directionally correct; a finer-grained mapping is a genuine future
        improvement, not something to fake precision on now.
        """
        if resource.resource_type != "issue":
            return [], []

        payload = resource.raw_payload
        resolution_name = payload.get("resolution_name")
        if not resolution_name:
            return [], []  # not actually resolved yet — no decision made

        assignee_id = payload.get("assignee_account_id")
        decision = {
            "decision_title": resource.title or resource.external_id,
            "owner_id": assignee_id,
            "rationale": payload.get("description_text") or "No description was provided on this ticket.",
            "actual_outcome": resolution_name,
            "state": "Published" if resolution_name in ("Done", "Fixed") else "Rejected",
        }
        return [], [decision]
