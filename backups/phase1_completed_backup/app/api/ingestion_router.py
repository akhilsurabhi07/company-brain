import asyncio
from typing import Dict, Any, List
from fastapi import APIRouter, HTTPException, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy import text
from app.db.database import async_session_factory
from app.storage.s3_storage import s3_storage
from app.storage.compressor import zstd_compressor
from app.processors.pii_redactor import pii_redactor
from app.connectors.registry import ConnectorRegistry

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
    async with async_session_factory() as session:
        await session.execute(
            text(f"SET LOCAL app.current_tenant_id = '{tenant_id}'")
        )
        res = await session.execute(
            text("SELECT source_app FROM oauth_tokens WHERE tenant_id = :tenant_id"),
            {"tenant_id": tenant_id},
        )
        connected_apps = [row[0] for row in res.fetchall()]

        if not connected_apps:
            return

        for source_app in connected_apps:
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
                token_mock = await connector.authenticate(tenant_id, "mock_code")
                resources, _ = await connector.list_resources(token_mock)

                if not resources:
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
                for item, (s3_key, file_bytes_len) in zip(items_to_upload, s3_results):
                    res_item = item["res_item"]
                    docs_metadata_batch.append({
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
                    })

                # Optimization 2: Bulk SQL Upsert in a single transaction
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
                    docs_metadata_batch,
                )

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
async def start_ingestion(req: StartIngestionRequest, background_tasks: BackgroundTasks):
    """
    Step 3: Trigger Ingestion Engine
    Kicks off parallel data pulling & compression pipeline in background for connected apps.
    """
    background_tasks.add_task(run_tenant_ingestion_pipeline, req.tenant_id)
    return {"status": "success", "message": "High-performance ingestion pipeline started", "tenant_id": req.tenant_id}

@router.get("/status")
async def get_ingestion_status(tenant_id: str):
    """
    Step 4: Live Sync Progress Telemetry
    Polled every few seconds by frontend to display real-time counters & status bars.
    """
    async with async_session_factory() as session:
        await session.execute(
            text(f"SET LOCAL app.current_tenant_id = '{tenant_id}'")
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
