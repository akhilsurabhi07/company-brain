import httpx
from typing import List, Tuple, Optional, Dict, Any
from app.connectors.base import Connector, OAuthToken, RawResource, ACLData, GraphNode, GraphEdge
from app.connectors.registry import ConnectorRegistry

GITHUB_API_BASE = "https://api.github.com"

@ConnectorRegistry.register("github")
class GitHubConnector(Connector):
    """
    Real GitHub REST API Connector.
    Pulls Pull Requests, Issues, Commits, and Code files from real repositories.
    Uses GitHub Personal Access Token (PAT) or OAuth App tokens.
    """

    @property
    def source_app(self) -> str:
        return "github"

    async def authenticate(self, tenant_id: str, code: str) -> OAuthToken:
        """
        In production: Exchange OAuth code for real access token via GitHub Apps.
        In development/testing: Treat 'code' as a pre-issued PAT token directly.
        """
        return OAuthToken(
            access_token=code,          # PAT is passed directly as the code
            refresh_token=None,
            token_type="Bearer",
        )

    async def list_resources(
        self,
        token: OAuthToken,
        cursor: Optional[str] = None,
        limit: int = 50,
        owner: Optional[str] = None,
        repo: Optional[str] = None,
    ) -> Tuple[List[RawResource], Optional[str]]:
        """
        Phase 1: Historical API Sync.
        Pulls Pull Requests from a real GitHub repository using the PAT token.
        Returns StandardResource list for compression + S3 + PostgreSQL storage.
        """
        if not owner or not repo:
            raise ValueError(
                "GitHubConnector.list_resources requires a real owner/repo to sync — "
                "there is no default repository to fall back to."
            )

        headers = {
            "Authorization": f"Bearer {token.access_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

        page = int(cursor) if cursor else 1
        url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/pulls"
        params = {"state": "all", "per_page": min(limit, 100), "page": page}

        # No fallback to sample/fake data here on purpose — a failed real API call (bad
        # token, repo not found, rate limited) must be reported honestly so the caller
        # can surface it, not silently replaced with a fabricated pull request.
        async with httpx.AsyncClient(timeout=10) as client:
            response = await self.execute_request_with_retry(client, url, headers=headers, params=params)
            pulls = response.json()

        resources = []
        for pr in pulls:
            raw_payload = {
                "id": pr.get("id"),
                "number": pr.get("number"),
                "title": pr.get("title"),
                "state": pr.get("state"),
                "body": pr.get("body"),
                "user": {
                    "login": pr.get("user", {}).get("login"),
                    "avatar_url": pr.get("user", {}).get("avatar_url"),
                },
                "head": {
                    "ref": pr.get("head", {}).get("ref"),
                    "sha": pr.get("head", {}).get("sha"),
                },
                "base": {"ref": pr.get("base", {}).get("ref")},
                "created_at": pr.get("created_at"),
                "updated_at": pr.get("updated_at"),
                "merged_at": pr.get("merged_at"),
                "html_url": pr.get("html_url"),
                "repo": f"{owner}/{repo}",
            }

            resource = RawResource(
                tenant_id=token.tenant_id if hasattr(token, 'tenant_id') and token.tenant_id else "default",
                source_app=self.source_app,
                resource_category="code_pr",
                resource_type="pull_request",
                external_id=f"pr_{owner}_{repo}_{pr.get('number')}",
                title=f"PR #{pr.get('number')}: {pr.get('title', '')}",
                content=pr.get("body") or "",
                raw_payload=raw_payload,
            )
            resources.append(resource)

        next_cursor = str(page + 1) if len(pulls) == limit else None
        return resources, next_cursor

    async def get_repo_readme(self, token: OAuthToken, owner: str, repo: str) -> Optional[RawResource]:
        """Fetch a repository's real README as an indexable document resource. Many
        repos (especially solo-developer ones with no PR/issue review workflow) have
        zero PRs or issues but do have real README content worth surfacing."""
        import base64

        headers = {
            "Authorization": f"Bearer {token.access_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/readme"

        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(url, headers=headers)
            if response.status_code == 404:
                return None
            response.raise_for_status()
            data = response.json()

        try:
            decoded = base64.b64decode(data.get("content", "")).decode("utf-8", errors="ignore")
        except Exception:
            decoded = ""
        if not decoded.strip():
            return None

        return RawResource(
            tenant_id="default",
            source_app=self.source_app,
            resource_category="doc",
            resource_type="readme",
            external_id=f"readme_{owner}_{repo}",
            title=f"{owner}/{repo} — README",
            content=decoded,
            raw_payload={
                "path": data.get("path"), "sha": data.get("sha"),
                "html_url": data.get("html_url"), "repo": f"{owner}/{repo}",
            },
        )

    async def list_issues(
        self,
        token: OAuthToken,
        owner: str,
        repo: str,
        page: int = 1,
        limit: int = 50,
    ) -> Tuple[List[RawResource], Optional[str]]:
        """Pull real GitHub Issues from a repository."""
        headers = {
            "Authorization": f"Bearer {token.access_token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/issues"
        params = {"state": "all", "per_page": min(limit, 100), "page": page}

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(url, headers=headers, params=params)
            response.raise_for_status()
            issues = response.json()

        resources = []
        for issue in issues:
            if "pull_request" in issue:
                continue  # Skip PRs that show up in issues endpoint
            raw_payload = {
                "id": issue.get("id"),
                "number": issue.get("number"),
                "title": issue.get("title"),
                "state": issue.get("state"),
                "body": issue.get("body"),
                "user": {"login": issue.get("user", {}).get("login")},
                "labels": [l.get("name") for l in issue.get("labels", [])],
                "created_at": issue.get("created_at"),
                "updated_at": issue.get("updated_at"),
                "html_url": issue.get("html_url"),
                "repo": f"{owner}/{repo}",
            }
            resource = RawResource(
                tenant_id="00000000-0000-0000-0000-000000000001",
                source_app=self.source_app,
                resource_category="code_issue",
                resource_type="issue",
                external_id=f"issue_{owner}_{repo}_{issue.get('number')}",
                title=f"Issue #{issue.get('number')}: {issue.get('title', '')}",
                content=issue.get("body") or "",
                raw_payload=raw_payload,
            )
            resources.append(resource)

        next_cursor = str(page + 1) if len(issues) == limit else None
        return resources, next_cursor

    async def fetch_permissions(self, token: OAuthToken, resource: RawResource) -> List[ACLData]:
        return [ACLData(principal_type="domain", principal_external_id="github.com", permission="read")]

    def extract_graph(self, resource: RawResource) -> Tuple[List[GraphNode], List[GraphEdge]]:
        node = GraphNode(
            id=resource.external_id,
            label="Document",
            properties={"title": resource.title or "", "type": resource.resource_type},
        )
        nodes, edges = [node], []
        user_login = resource.raw_payload.get("user", {}).get("login")
        if user_login:
            author_node = GraphNode(id=f"user_{user_login}", label="Person", properties={"login": user_login})
            nodes.append(author_node)
            edges.append(GraphEdge(
                from_node_id=resource.external_id,
                to_node_id=f"user_{user_login}",
                label="AUTHORED_BY",
                properties={},
            ))
        return nodes, edges

    def extract_facts_and_decisions(self, resource: RawResource) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """A closed pull request is a real decision record: it was proposed (rationale
        = the real PR description), and it was either merged (adopted) or closed
        without merging (rejected) — a real, verifiable outcome, not inferred. An open
        PR isn't a decision yet, so it's honestly skipped rather than guessed at."""
        if resource.resource_type != "pull_request":
            return [], []

        payload = resource.raw_payload
        state = payload.get("state")
        if state not in ("closed", "merged"):
            return [], []  # still open — no decision has actually been made yet

        merged_at = payload.get("merged_at")
        owner_login = payload.get("user", {}).get("login")

        decision = {
            "decision_title": resource.title or f"PR #{payload.get('number')}",
            "owner_id": owner_login,
            "rationale": payload.get("body") or "No description was provided in this pull request.",
            "actual_outcome": "Merged" if merged_at else "Closed without merging",
            "state": "Published" if merged_at else "Rejected",
        }
        return [], [decision]
