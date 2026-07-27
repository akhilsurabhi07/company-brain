"""
Phase 1: Real GitHub API Sync Script
=====================================
This script connects to the real GitHub API using a Personal Access Token (PAT),
pulls real Pull Requests and Issues from your repository,
compresses each payload with Zstandard (.json.zst),
uploads to AWS S3, and indexes the metadata in AWS RDS PostgreSQL.

Usage:
    python -m scripts.sync_real_github \
        --token YOUR_GITHUB_PAT \
        --owner YOUR_GITHUB_USERNAME \
        --repo YOUR_REPO_NAME \
        --tenant_id YOUR_TENANT_UUID_FROM_SIGNUP
"""
import argparse
import asyncio
import json
import sys
import uuid
from datetime import datetime
from sqlalchemy import text

from app.connectors.github import GitHubConnector
from app.connectors.base import OAuthToken
from app.storage.s3_storage import s3_storage
from app.processors.pii_redactor import pii_redactor
from app.db.database import async_session_factory


def fmt(n):
    """Format bytes nicely."""
    for unit in ["B", "KB", "MB", "GB"]:
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


async def run_github_api_sync(token_str: str, owner: str, repo: str, tenant_id: str):
    print("=" * 65)
    print("  PHASE 1: REAL GITHUB API HISTORICAL SYNC")
    print("=" * 65)
    print(f"  Repository : https://github.com/{owner}/{repo}")
    print(f"  Tenant ID  : {tenant_id}")
    print(f"  AWS S3     : {s3_storage.bucket_name}")
    print(f"  Started At : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 65)

    connector = GitHubConnector()
    token = OAuthToken(access_token=token_str, token_type="Bearer")

    total_synced = 0
    total_bytes = 0
    all_resources = []

    # --- PULL REQUESTS ---
    print("\n[1/2] Fetching Pull Requests from GitHub API...")
    page = 1
    while True:
        prs, next_cursor = await connector.list_resources(
            token, cursor=str(page), limit=30, owner=owner, repo=repo
        )
        if not prs:
            break
        all_resources.extend(prs)
        print(f"    Fetched page {page}: {len(prs)} PRs")
        if not next_cursor:
            break
        page += 1

    # --- ISSUES ---
    print("\n[2/2] Fetching Issues from GitHub API...")
    page = 1
    while True:
        issues, next_cursor = await connector.list_issues(
            token, owner=owner, repo=repo, page=page, limit=30
        )
        if not issues:
            break
        all_resources.extend(issues)
        print(f"    Fetched page {page}: {len(issues)} Issues")
        if not next_cursor:
            break
        page += 1

    print(f"\n  Total resources fetched from GitHub API: {len(all_resources)}")

    if not all_resources:
        print("\n  [Notice] Repo has no PRs/Issues open. Syncing repo metadata payload...")
        # Create a repo metadata resource so we ingest the real repository payload
        import httpx
        async with httpx.AsyncClient(timeout=30) as client:
            res_repo = await client.get(
                f"https://api.github.com/repos/{owner}/{repo}",
                headers={"Authorization": f"Bearer {token_str}", "Accept": "application/vnd.github+json"}
            )
            repo_json = res_repo.json()
        
        from app.connectors.base import RawResource
        all_resources.append(RawResource(
            tenant_id=tenant_id,
            source_app="github",
            resource_category="code_repo",
            resource_type="repository",
            external_id=f"repo_{owner}_{repo}",
            title=f"GitHub Repository: {owner}/{repo}",
            content=f"Repository {owner}/{repo}: {repo_json.get('description', '')}",
            raw_payload=repo_json,
        ))

    # --- PROCESS, COMPRESS, UPLOAD, INDEX ---
    print("\n  Processing, compressing, and uploading to AWS S3 + RDS...")
    print("-" * 65)

    async with async_session_factory() as session:
        # Ensure tenant exists
        await session.execute(
            text("""
                INSERT INTO tenants (id, name, domain)
                VALUES (:id, :name, :domain)
                ON CONFLICT (id) DO NOTHING
            """),
            {"id": tenant_id, "name": f"GitHub:{owner}", "domain": f"{owner}.github.com"},
        )
        await session.commit()

        for idx, resource in enumerate(all_resources, 1):
            resource.tenant_id = tenant_id

            # 1. Redact PII from content
            clean_content = pii_redactor.redact_secrets(resource.content or "")

            # 2. Compress + Upload to AWS S3
            s3_key, file_bytes_len = s3_storage.save_raw_json(
                tenant_id=tenant_id,
                source_app=resource.source_app,
                resource_type=resource.resource_type,
                external_id=resource.external_id,
                raw_payload=resource.raw_payload,
                compress=True,
            )
            total_bytes += file_bytes_len

            # 3. Index metadata in PostgreSQL
            await session.execute(
                text(f"SET LOCAL app.current_tenant_id = '{tenant_id}'")
            )
            await session.execute(
                text("""
                    INSERT INTO documents (
                        tenant_id, source_app, resource_category, resource_type, external_id,
                        title, content, s3_bucket, s3_key, is_compressed, file_size_bytes
                    ) VALUES (
                        :tenant_id, :source_app, :category, :type, :ext_id,
                        :title, :content, :s3_bucket, :s3_key, TRUE, :bytes_len
                    ) ON CONFLICT (tenant_id, source_app, external_id) DO UPDATE
                    SET content = EXCLUDED.content,
                        file_size_bytes = EXCLUDED.file_size_bytes,
                        updated_at = now()
                """),
                {
                    "tenant_id": tenant_id,
                    "source_app": resource.source_app,
                    "category": resource.resource_category,
                    "type": resource.resource_type,
                    "ext_id": resource.external_id,
                    "title": resource.title or "",
                    "content": clean_content,
                    "s3_bucket": s3_storage.bucket_name,
                    "s3_key": s3_key,
                    "bytes_len": file_bytes_len,
                },
            )
            await session.commit()

            total_synced += 1
            print(f"  [{idx:>3}] {resource.resource_type:<14} | {resource.title[:52]}")
            print(f"         S3 Key : {s3_key}")
            print(f"         Size   : {fmt(file_bytes_len)} compressed")
            print()

    print("=" * 65)
    print("  PHASE 1 SYNC COMPLETE!")
    print(f"  Total Items Synced : {total_synced}")
    print(f"  Total AWS S3 Usage : {fmt(total_bytes)} (Zstandard compressed)")
    print(f"  Repository         : https://github.com/{owner}/{repo}")
    print(f"  Tenant UUID        : {tenant_id}")
    print("=" * 65)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Real GitHub API Historical Sync")
    parser.add_argument("--token",     required=True,  help="GitHub Personal Access Token (PAT)")
    parser.add_argument("--owner",     required=True,  help="GitHub repo owner (username or org)")
    parser.add_argument("--repo",      required=True,  help="GitHub repository name")
    parser.add_argument("--tenant_id", required=False, help="Tenant UUID (auto-generated if omitted)",
                        default=str(uuid.uuid4()))
    args = parser.parse_args()

    asyncio.run(run_github_api_sync(args.token, args.owner, args.repo, args.tenant_id))
