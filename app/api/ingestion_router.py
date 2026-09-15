import asyncio
import uuid
from typing import Dict, Any, List
from fastapi import APIRouter, HTTPException, BackgroundTasks, Depends
from app.security.auth_dependency import require_authenticated_tenant, verify_tenant_matches_token
from pydantic import BaseModel
from sqlalchemy import text
from app.db.database import async_session_factory
from app.storage.s3_storage import s3_storage
from app.storage.compressor import zstd_compressor
from app.processors.pii_redactor import pii_redactor
from app.processors.ingestion_pipeline import chunk_embed_and_store
from app.connectors.registry import ConnectorRegistry
from app.security.crypto import token_crypto
from app.db.postgres_knowledge_repo import postgres_knowledge_repo
from app.domain.graph_models import EntityModel, RelationshipModel, DecisionModel, FactModel
from app.core_config.tenant_config_service import tenant_config_service

router = APIRouter(prefix="/api/v1/ingestion", tags=["Data Ingestion & Live Sync"])

class StartIngestionRequest(BaseModel):
    tenant_id: str

async def run_tenant_ingestion_pipeline(tenant_id: str):
    """
    High-Performance Parallel Ingestion Pipeline (Optimized):
    1. Fetches connected apps for tenant.
    2. Runs parallel batch S3 uploads via asyncio.gather().
    3. Executes bulk SQL upserts in single transaction statements.
    4. Updates live sync status telemetry counters.
    """
    # Pre-load this tenant's real persisted config (embedding model / chunk overrides /
    # feature flags) into TenantConfigService's cache before the synchronous chunking
    # pipeline runs and reads it — see tenant_config_service.py's module docstring.
    await tenant_config_service.load_tenant_config(tenant_id)

    async with async_session_factory() as session:
        await session.execute(
            text("SELECT set_config('app.current_tenant_id', :__tid, true)"), {"__tid": str(tenant_id)}
        )
        res = await session.execute(
            text("SELECT source_app, encrypted_access_token, config FROM oauth_tokens WHERE tenant_id = :tenant_id"),
            {"tenant_id": tenant_id},
        )
        connected_apps = {row[0]: (row[1], row[2] or {}) for row in res.fetchall()}

        if not connected_apps:
            return

        for source_app, (encrypted_token, app_config) in connected_apps.items():
            # Update status to syncing
            await session.execute(
                text("""
                    UPDATE sync_statuses 
                    SET status = 'syncing', updated_at = now()
                    WHERE tenant_id = :tenant_id AND source_app = :source_app
                """),
                {"tenant_id": tenant_id, "source_app": source_app},
            )
            await session.commit()

            try:
                connector = ConnectorRegistry.get_connector(source_app)
                # Use the tenant's REAL stored credential (decrypted here, in-process,
                # never logged) — not a hardcoded literal. Connectors that are still
                # fake stubs (see each connector's authenticate()) ignore this value
                # today, but real ones (e.g. GitHub, which treats it as a PAT) need it
                # to make genuine API calls instead of falling back to sample data.
                real_credential = token_crypto.decrypt_token(encrypted_token, tenant_id)
                token = await connector.authenticate(tenant_id, real_credential)

                # Some OAuth providers rotate refresh tokens on every use (Jira/
                # Atlassian does; Google's don't) — the old one is invalidated the
                # moment the new one is issued. If authenticate() returned a different
                # refresh_token than what's stored, that update MUST be persisted now,
                # or the very next sync would fail with an already-invalidated token.
                if token.refresh_token and token.refresh_token != real_credential:
                    new_encrypted = token_crypto.encrypt_token(token.refresh_token, tenant_id)
                    await session.execute(
                        text("UPDATE oauth_tokens SET encrypted_access_token = :tok, updated_at = now() WHERE tenant_id = :tid AND source_app = :src"),
                        {"tok": new_encrypted, "tid": tenant_id, "src": source_app},
                    )
                    await session.commit()

                # GitHub has no sensible default repo — it must be told which one to
                # sync via the connection's stored config (set at /connect time).
                if source_app == "github":
                    owner, repo = app_config.get("owner"), app_config.get("repo")
                    resources, _ = await connector.list_resources(token, owner=owner, repo=repo)
                    issue_resources, _ = await connector.list_issues(token, owner=owner, repo=repo)
                    resources = list(resources) + list(issue_resources)
                    # Many real repos (especially solo-developer ones with no PR/issue
                    # review workflow) have zero PRs or issues but do have real README
                    # content — without this, such a repo would sync "successfully"
                    # with nothing actually ingested, which isn't useful to anyone.
                    readme = await connector.get_repo_readme(token, owner, repo)
                    if readme:
                        resources.append(readme)
                elif source_app == "jira":
                    # Jira has no sensible default site — the real cloudId (discovered
                    # once at OAuth-connect time via accessible-resources) must come
                    # from the connection's stored config.
                    cloud_id = app_config.get("cloud_id")
                    resources, _ = await connector.list_resources(token, cloud_id=cloud_id)
                else:
                    resources, _ = await connector.list_resources(token)

                if not resources:
                    # A real sync that genuinely found nothing to ingest is still a
                    # completed sync, not one stuck "syncing" forever — that stuck state
                    # was indistinguishable from a hung/failed sync to anyone watching.
                    await session.execute(
                        text("""
                            UPDATE sync_statuses
                            SET status = 'synced', last_synced_at = now(), updated_at = now()
                            WHERE tenant_id = :tenant_id AND source_app = :source_app
                        """),
                        {"tenant_id": tenant_id, "source_app": source_app},
                    )
                    await session.commit()
                    continue

                # Prepare items for parallel processing
                items_to_upload = []
                docs_metadata_batch = []

                for res_item in resources:
                    clean_content = pii_redactor.redact_secrets(res_item.content or "")
                    items_to_upload.append({
                        "resource_type": res_item.resource_type,
                        "external_id": res_item.external_id,
                        "raw_payload": res_item.raw_payload,
                        "res_item": res_item,
                        "clean_content": clean_content,
                    })

                # Optimization 1: Parallel Batch S3 Uploads
                s3_results = await s3_storage.save_batch_parallel(
                    tenant_id=tenant_id,
                    source_app=source_app,
                    items=items_to_upload,
                    concurrency=10,
                )

                # Prepare bulk SQL params
                res_item_by_ext_id = {}
                for item, (s3_key, file_bytes_len) in zip(items_to_upload, s3_results):
                    res_item = item["res_item"]
                    res_item_by_ext_id[res_item.external_id] = res_item
                    docs_metadata_batch.append({
                        "id": str(uuid.uuid4()),
                        "tenant_id": tenant_id,
                        "source_app": source_app,
                        "category": res_item.resource_category,
                        "type": res_item.resource_type,
                        "ext_id": res_item.external_id,
                        "title": res_item.title or f"{source_app.title()} Resource",
                        "content": item["clean_content"],
                        "s3_bucket": s3_storage.bucket_name,
                        "s3_key": s3_key,
                        "bytes_len": file_bytes_len,
                        "resource_group_id": res_item.resource_group_id,  # None for every
                        # connector except ones using channel-level ACLs (Slack) — see
                        # hybrid_retriever.py's ACL clause and resource_group_acls below.
                    })

                # Upsert each document, capturing back its REAL id via RETURNING — when a
                # document already exists (ON CONFLICT DO UPDATE), Postgres keeps the
                # existing row's id, not the freshly generated one in VALUES. Chunking
                # against the wrong id would violate document_chunks' FK to documents, so
                # this can't be a fire-and-forget bulk insert; each id must be confirmed.
                await session.execute(
                    text("SELECT set_config('app.current_tenant_id', :__tid, true)"), {"__tid": str(tenant_id)}
                )
                for doc_meta in docs_metadata_batch:
                    row = await session.execute(
                        text("""
                            INSERT INTO documents (
                                id, tenant_id, source_app, resource_category, resource_type, external_id,
                                title, content, s3_bucket, s3_key, is_compressed, file_size_bytes, resource_group_id
                            ) VALUES (
                                :id, :tenant_id, :source_app, :category, :type, :ext_id,
                                :title, :content, :s3_bucket, :s3_key, TRUE, :bytes_len, :resource_group_id
                            ) ON CONFLICT (tenant_id, source_app, external_id) DO UPDATE
                            SET content = EXCLUDED.content,
                                file_size_bytes = EXCLUDED.file_size_bytes,
                                resource_group_id = EXCLUDED.resource_group_id,
                                updated_at = now()
                            RETURNING id
                        """),
                        doc_meta,
                    )
                    doc_meta["id"] = str(row.scalar_one())
                await session.commit()

                # Persist real ACLs so retrieval can enforce them (see HybridRetriever's
                # ACL filter). Two shapes, chosen per-document by whether
                # resource_group_id is set — GitHub (and anything else with
                # resource_group_id=None) keeps the exact original per-document path;
                # nothing about that branch changed.
                unique_group_ids = set()
                for doc_meta in docs_metadata_batch:
                    res_item = res_item_by_ext_id.get(doc_meta["ext_id"])
                    if res_item is None:
                        continue

                    if doc_meta["resource_group_id"] is not None:
                        unique_group_ids.add(doc_meta["resource_group_id"])
                        continue  # handled once per group below, not per document

                    try:
                        acls = await connector.fetch_permissions(token, res_item)
                    except Exception as acl_ex:
                        print(f"[Ingestion] ACL fetch failed for doc {doc_meta['id']}: {acl_ex}")
                        continue
                    # Idempotent on resync — replace rather than accumulate duplicates.
                    await session.execute(
                        text("DELETE FROM document_acls WHERE document_id = :document_id"),
                        {"document_id": doc_meta["id"]},
                    )
                    for acl in acls:
                        await session.execute(
                            text("""
                                INSERT INTO document_acls (document_id, tenant_id, principal_type, principal_external_id, permission)
                                VALUES (:document_id, :tenant_id, :principal_type, :principal_external_id, :permission)
                            """),
                            {
                                "document_id": doc_meta["id"], "tenant_id": tenant_id,
                                "principal_type": acl.principal_type,
                                "principal_external_id": acl.principal_external_id,
                                "permission": acl.permission,
                            },
                        )

                # Channel-level ACLs (Slack): one real membership fetch per unique
                # channel in this batch, not per message — this is the whole point of
                # resource_group_acls existing instead of fanning out document_acls.
                for group_id in unique_group_ids:
                    try:
                        group_acls = await connector.fetch_group_permissions(token, group_id)
                    except Exception as acl_ex:
                        print(f"[Ingestion] Group ACL fetch failed for {source_app}:{group_id}: {acl_ex}")
                        continue
                    # Idempotent on resync — membership changes over time.
                    await session.execute(
                        text("DELETE FROM resource_group_acls WHERE tenant_id = :tid AND source_app = :src AND resource_group_id = :gid"),
                        {"tid": tenant_id, "src": source_app, "gid": group_id},
                    )
                    for acl in group_acls:
                        await session.execute(
                            text("""
                                INSERT INTO resource_group_acls (tenant_id, source_app, resource_group_id, principal_type, principal_external_id, permission)
                                VALUES (:tid, :src, :gid, :principal_type, :principal_external_id, :permission)
                                ON CONFLICT (tenant_id, source_app, resource_group_id, principal_type, principal_external_id) DO NOTHING
                            """),
                            {
                                "tid": tenant_id, "src": source_app, "gid": group_id,
                                "principal_type": acl.principal_type,
                                "principal_external_id": acl.principal_external_id,
                                "permission": acl.permission,
                            },
                        )
                await session.commit()

                # Real Module 2 chain: chunk -> score -> embed -> persist, so this data
                # actually becomes retrievable in chat instead of just sitting stored.
                # Best-effort per document — one bad document shouldn't abort the sync.
                for doc_meta in docs_metadata_batch:
                    try:
                        pipeline_result = await chunk_embed_and_store(
                            tenant_id=tenant_id,
                            document_id=doc_meta["id"],
                            full_text=doc_meta["content"],
                            resource_category=doc_meta["category"],
                        )
                        if pipeline_result["status"] != "completed":
                            print(f"[Ingestion] doc {doc_meta['id']} ({doc_meta['title']}): {pipeline_result}")
                    except Exception as embed_ex:
                        print(f"[Ingestion] Chunk/embed failed for doc {doc_meta['id']} ({doc_meta['title']}): {embed_ex}")

                # Real Module 3 chain: each connector already implements extract_graph()
                # (entities + relationships from the raw resource) but nothing has ever
                # called it — graph_entities/graph_relationships were always empty, which
                # is why /api/v1/knowledge/health and /impact had to be fed fake sample
                # data. Idempotent on resync: look up existing entities/relationships by
                # their real natural keys instead of blindly re-inserting duplicates.
                for doc_meta in docs_metadata_batch:
                    res_item = res_item_by_ext_id.get(doc_meta["ext_id"])
                    if res_item is None:
                        continue
                    try:
                        nodes, edges = connector.extract_graph(res_item)
                    except Exception as graph_ex:
                        print(f"[Ingestion] Graph extraction failed for doc {doc_meta['id']}: {graph_ex}")
                        continue

                    node_id_to_entity_id: Dict[str, str] = {}
                    for node in nodes:
                        # Real gap found 2026-08-20: Drive/Jira/SharePoint's real Person
                        # nodes carry a real display name under "name" (Slack/WhatsApp
                        # genuinely don't have one available from their raw payload —
                        # falling through to node.id for those is correct, not a bug),
                        # but this fallback chain never checked it, so those three
                        # connectors' people entities all got an opaque "user_<id>"
                        # canonical_name instead of a real readable one.
                        canonical_name = (
                            node.properties.get("title") or node.properties.get("name")
                            or node.properties.get("login") or node.id
                        )
                        entity_type = node.label.lower()
                        existing = await postgres_knowledge_repo.get_entity_by_canonical_name(tenant_id, canonical_name)
                        if existing and existing["entity_type"] == entity_type:
                            entity_id = existing["id"]
                        else:
                            entity_id = await postgres_knowledge_repo.create_entity(EntityModel(
                                tenant_id=tenant_id, entity_type=entity_type, canonical_name=canonical_name,
                                attributes=node.properties,
                            ))
                        node_id_to_entity_id[node.id] = entity_id

                    for edge in edges:
                        src_id = node_id_to_entity_id.get(edge.from_node_id)
                        tgt_id = node_id_to_entity_id.get(edge.to_node_id)
                        if not src_id or not tgt_id:
                            continue
                        if await postgres_knowledge_repo.relationship_exists(tenant_id, src_id, tgt_id, edge.label):
                            continue
                        await postgres_knowledge_repo.create_relationship(
                            RelationshipModel(
                                tenant_id=tenant_id, source_entity_id=src_id, target_entity_id=tgt_id,
                                relation_type=edge.label, attributes=edge.properties,
                            ),
                            document_id=doc_meta["id"],
                        )

                    # Real facts/decisions (2026-08-20): graph_facts/graph_decisions have
                    # real repo write methods (postgres_knowledge_repo.create_fact/
                    # create_decision) but nothing in the live path ever called them —
                    # permanently empty tables, same root cause as the entities/
                    # relationships gap above. Idempotency check runs here (raw SQL, not
                    # a new postgres_knowledge_repo.py method) so the frozen repo file
                    # itself stays untouched — only its existing create_decision/
                    # create_fact methods are consumed, unmodified.
                    try:
                        facts, decisions = connector.extract_facts_and_decisions(res_item)
                    except Exception as fd_ex:
                        print(f"[Ingestion] Facts/decisions extraction failed for doc {doc_meta['id']}: {fd_ex}")
                        facts, decisions = [], []

                    for dec in decisions:
                        existing_dec = await session.execute(
                            text("SELECT id FROM graph_decisions WHERE tenant_id = :tid AND decision_title = :title"),
                            {"tid": tenant_id, "title": dec["decision_title"]},
                        )
                        if existing_dec.fetchone():
                            continue  # already recorded on a prior sync — don't duplicate

                        # Real bug found and fixed 2026-08-20: graph_decisions.owner_id
                        # is a real UUID foreign key into graph_entities, not a free-text
                        # login string — the connector only knows the raw login (e.g.
                        # "octocat"), so it's resolved here against the real Person
                        # entity UUID already created for this same resource's author a
                        # few lines above (node_id_to_entity_id), honestly falling back
                        # to NULL if no such entity exists rather than guessing an id.
                        resolved_dec = dict(dec)
                        raw_owner = resolved_dec.get("owner_id")
                        resolved_dec["owner_id"] = node_id_to_entity_id.get(f"user_{raw_owner}") if raw_owner else None
                        await postgres_knowledge_repo.create_decision(DecisionModel(tenant_id=tenant_id, **resolved_dec))

                    for fact in facts:
                        existing_fact = await session.execute(
                            text("SELECT id FROM graph_facts WHERE tenant_id = :tid AND metric_name = :m AND period = :p"),
                            {"tid": tenant_id, "m": fact.get("metric_name"), "p": fact.get("period")},
                        )
                        if existing_fact.fetchone():
                            continue
                        await postgres_knowledge_repo.create_fact(FactModel(tenant_id=tenant_id, **fact), document_id=doc_meta["id"])

                # Update sync status counter
                await session.execute(
                    text("""
                        UPDATE sync_statuses 
                        SET status = 'synced', 
                            total_items_synced = total_items_synced + :synced_count,
                            last_synced_at = now(),
                            updated_at = now()
                        WHERE tenant_id = :tenant_id AND source_app = :source_app
                    """),
                    {"tenant_id": tenant_id, "source_app": source_app, "synced_count": len(resources)},
                )
                await session.commit()

            except Exception as e:
                await session.execute(
                    text("""
                        UPDATE sync_statuses 
                        SET status = 'error', error_message = :err, updated_at = now()
                        WHERE tenant_id = :tenant_id AND source_app = :source_app
                    """),
                    {"tenant_id": tenant_id, "source_app": source_app, "err": str(e)},
                )
                await session.commit()

@router.post("/start")
async def start_ingestion(req: StartIngestionRequest, background_tasks: BackgroundTasks, token=Depends(require_authenticated_tenant)):
    """
    Step 3: Trigger Ingestion Engine
    Kicks off parallel data pulling & compression pipeline in background for connected apps.
    """
    req.tenant_id = verify_tenant_matches_token(req.tenant_id, token)
    background_tasks.add_task(run_tenant_ingestion_pipeline, req.tenant_id)
    return {"status": "success", "message": "High-performance ingestion pipeline started", "tenant_id": req.tenant_id}

@router.get("/status")
async def get_ingestion_status(tenant_id: str, token=Depends(require_authenticated_tenant)):
    """
    Step 4: Live Sync Progress Telemetry
    Polled every few seconds by frontend to display real-time counters & status bars.
    """
    tenant_id = verify_tenant_matches_token(tenant_id, token)
    async with async_session_factory() as session:
        await session.execute(
            text("SELECT set_config('app.current_tenant_id', :__tid, true)"), {"__tid": str(tenant_id)}
        )
        
        # Count total documents & bytes in S3
        res_totals = await session.execute(
            text("""
                SELECT COUNT(*), COALESCE(SUM(file_size_bytes), 0)
                FROM documents
                WHERE tenant_id = :tenant_id
            """),
            {"tenant_id": tenant_id},
        )
        totals = res_totals.fetchone()
        total_docs = totals[0] if totals else 0
        total_bytes = totals[1] if totals else 0

        # App status breakdown
        res_apps = await session.execute(
            text("""
                SELECT source_app, status, total_items_synced, last_synced_at, error_message
                FROM sync_statuses
                WHERE tenant_id = :tenant_id
            """),
            {"tenant_id": tenant_id},
        )
        apps_status = []
        for row in res_apps.fetchall():
            apps_status.append({
                "source_app": row[0],
                "status": row[1],
                "items_synced": row[2],
                "last_synced_at": row[3],
                "error": row[4],
            })

        # Recent activity log
        res_docs = await session.execute(
            text("""
                SELECT source_app, title, file_size_bytes, ingested_at, s3_key
                FROM documents
                WHERE tenant_id = :tenant_id
                ORDER BY ingested_at DESC LIMIT 5
            """),
            {"tenant_id": tenant_id},
        )
        recent_logs = []
        for d in res_docs.fetchall():
            recent_logs.append({
                "app": d[0],
                "title": d[1],
                "bytes": d[2],
                "timestamp": d[3],
                "s3_key": d[4],
            })

        return {
            "tenant_id": tenant_id,
            "total_documents_synced": total_docs,
            "total_s3_bytes": total_bytes,
            "apps_status": apps_status,
            "recent_activity": recent_logs,
        }
