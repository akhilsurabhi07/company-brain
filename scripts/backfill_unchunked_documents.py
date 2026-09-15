"""
Real, reusable safeguard for a bug pattern found twice this session: documents can
land in the `documents` table with zero chunks/embeddings — either from a seed/test
script's raw INSERT bypassing the real ingestion pipeline (found in the default
tenant AND in a real user's own live tenant, `reshire.in`), or from any future bug
that does the same. When that happens, every question about that document silently
gets "I don't have that information" or, worse, a hallucinated answer — with no
visible signal that anything is wrong.

This is not a one-off fix — it's a real, safe, idempotent tool: run with --dry-run
to see what's affected before touching anything, run without it to actually backfill
using the exact same real pipeline (SemanticChunker + BGEEmbedder + ChunkVectorRepository)
every real upload/connector path already uses.

Usage:
    python scripts/backfill_unchunked_documents.py --dry-run          # report only
    python scripts/backfill_unchunked_documents.py                    # backfill all tenants
    python scripts/backfill_unchunked_documents.py --tenant-id <uuid>  # one tenant only
"""
import argparse
import asyncio
import sys

from sqlalchemy import text
from app.db.database import async_session_factory
from app.processors.semantic_chunker import SemanticChunker
from app.embeddings.bge_embedder import bge_embedder
from app.db.chunk_vector_repo import chunk_vector_repo

semantic_chunker = SemanticChunker()


async def find_unchunked_documents(tenant_id: str = None):
    """Returns [(tenant_id, doc_id, resource_category, content), ...] for every
    document that has zero rows in document_chunks. Scoped by explicit tenant_id
    filters throughout — never relies on RLS alone, since this needs to run
    correctly regardless of RLS enforcement status."""
    async with async_session_factory() as session:
        if tenant_id:
            await session.execute(text("SELECT set_config('app.current_tenant_id', :tid, true)"), {"tid": tenant_id})
            res = await session.execute(
                text("""
                    SELECT tenant_id, id, resource_category, content FROM documents d
                    WHERE d.tenant_id = :tid
                      AND d.id NOT IN (SELECT DISTINCT document_id FROM document_chunks WHERE tenant_id = :tid)
                """),
                {"tid": tenant_id},
            )
        else:
            res = await session.execute(
                text("""
                    SELECT tenant_id, id, resource_category, content FROM documents d
                    WHERE d.id NOT IN (SELECT DISTINCT document_id FROM document_chunks)
                """)
            )
        return res.fetchall()


async def backfill_one(row) -> bool:
    tenant_id, doc_id, resource_category, content = str(row[0]), str(row[1]), row[2], row[3]
    if not content or not content.strip():
        print(f"  ! {doc_id} (tenant {tenant_id}): empty content, cannot chunk — skipping")
        return False

    chunks = semantic_chunker.chunk_document(
        tenant_id=tenant_id, document_id=doc_id, full_text=content, resource_category=resource_category or "document",
    )
    if not chunks:
        print(f"  ! {doc_id} (tenant {tenant_id}): chunker produced 0 chunks — skipping")
        return False

    embeddings = bge_embedder.embed_texts([c.text_content for c in chunks])
    await chunk_vector_repo.save_chunks_and_embeddings(tenant_id=tenant_id, document_id=doc_id, chunks=chunks, embeddings=embeddings)
    print(f"  + {doc_id} (tenant {tenant_id}): {len(chunks)} chunk(s) created and embedded")
    return True


async def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--tenant-id", default=None, help="Only check/backfill this tenant (default: all tenants)")
    parser.add_argument("--dry-run", action="store_true", help="Report affected documents without changing anything")
    args = parser.parse_args()

    rows = await find_unchunked_documents(args.tenant_id)
    scope = f"tenant {args.tenant_id}" if args.tenant_id else "ALL tenants"
    print(f"Found {len(rows)} unchunked document(s) across {scope}.")

    if args.dry_run:
        for row in rows:
            print(f"  - tenant={row[0]} doc={row[1]} category={row[2]}")
        print("\nDry run — nothing changed. Re-run without --dry-run to backfill.")
        return

    fixed = 0
    for row in rows:
        if await backfill_one(row):
            fixed += 1
    print(f"\nBackfill complete: {fixed}/{len(rows)} document(s) fixed.")


if __name__ == "__main__":
    asyncio.run(main())
