"""
Hybrid Vector + Full-Text + Rerank Retriever Implementation — Module 4
========================================================================
Query
  |-- Semantic Search (pgvector cosine, top-N)
  |-- Keyword Search   (Postgres full-text search / ts_rank_cd, top-N)
  `-- Metadata + ACL filter (tenant RLS + document_acls, applied in-SQL)
       v
  Candidate Pool (union, deduped by chunk_id)
       v
  Score Normalization  (rank-based, via Reciprocal Rank Fusion)
       v
  Candidate Fusion     (RRF-fused score)
       v
  Reranker             (real self-hosted cross-encoder, ms-marco-MiniLM-L-6-v2)
       v
  Top-K Evidence (with full provenance + every component score, for observability)

Replaces the previous substring-`LIKE` keyword layer and the brittle dual AND-threshold
(`combined_score >= 0.78 AND raw_cosine >= 0.50`) that rejected a genuinely relevant,
correctly keyword-matched document purely because its raw cosine similarity landed at
0.496 — 0.004 below an arbitrary floor. See tests/test_retrieval_real_data.py for the
real-data regression suite that pins this behavior down.
"""
import asyncio
import re
import time
import logging
from typing import List, Dict, Any, Optional
from sqlalchemy import text
from app.db.database import async_session_factory
from app.embeddings.bge_embedder import bge_embedder
from app.retrieval.implementations.cross_encoder import reranker as cross_encoder_reranker

logger = logging.getLogger("company_brain.retrieval.hybrid")

# Recalibrated 2026-08-21 after a real failure found via live user testing: the
# original 0.0 threshold was calibrated only against precise factual queries
# ("who is the lead architect on X"), which this cross-encoder scores strongly
# positive (~+5.5) when correct. But broad "summarize X" / "tell me about X" style
# queries score their genuinely correct match far lower (~-2.9 measured live against
# a real document whose actual content matched the question) — this model's score
# range shifts with query *style*, not just relevance, and 0.0 silently rejected
# correct matches for the entire "summarize/describe" query family.
# Real, controlled evidence for the new value (all measured live, same tenant/model):
#   genuinely irrelevant query, best candidate:         ~-11.3
#   real document with no actual answer to the question: ~-11.2  (correctly rejected)
#   real, correct match for a broad "summarize" query:    ~-2.9  (previously, wrongly, rejected)
#   real, correct match for a precise factual query:      ~+1.9 to +5.5
# -5.0 sits in the gap between "genuinely irrelevant" (~-11) and "genuinely relevant,
# broadly phrased" (~-2.9) with margin on both sides — not a guessed number, and it
# does not change acceptance for any of the original precise-factual-query evidence.
RERANK_ACCEPT_THRESHOLD = -5.0

# RRF constant — standard value used by Elasticsearch/OpenSearch/Weaviate hybrid search;
# not sensitive to the exact value, just needs to de-emphasize very low ranks.
RRF_K = 60

VECTOR_CANDIDATE_POOL = 20
KEYWORD_CANDIDATE_POOL = 20
RERANK_CANDIDATE_POOL = 40  # cap on how many fused candidates get sent to the reranker


class HybridRetriever:
    """Real hybrid retrieval: pgvector semantic search + Postgres full-text keyword
    search, fused via Reciprocal Rank Fusion, reranked with a genuine self-hosted
    cross-encoder, filtered by tenant RLS + document ACLs before anything reaches the LLM.
    """

    async def search(
        self,
        tenant_id: str,
        query: str,
        top_k: int = 6,
        user_id: str = "",
        debug: bool = False,
    ) -> Dict[str, Any]:
        t0 = time.time()
        query_vec = (await asyncio.to_thread(bge_embedder.embed_texts, [query]))[0]
        vec_str = f"[{','.join(str(x) for x in query_vec)}]"

        # ACL check, widened 2026-08-20 to also support channel-level ACLs (Slack) without
        # changing existing per-document ACL behavior (GitHub) at all:
        #   1. No document_acls row AND no resource_group -> default-open, same as before.
        #   2. A matching document_acls row (domain, or this user) -> visible, same as before.
        #   3. NEW: document belongs to a resource_group (e.g. Slack channel) -> visible only
        #      if this user has a resource_group_acls row for that group. A document with a
        #      resource_group set is deliberately excluded from the default-open case (1),
        #      so a channel document with no matching membership row is NOT visible by default.
        # See tests/test_retrieval_real_data.py::test_i_* for the regression proof that (1)
        # and (2) are unchanged, and tests/test_channel_acl_real.py for (3).
        acl_clause = """
            AND (
                (
                    NOT EXISTS (SELECT 1 FROM document_acls a WHERE a.document_id = d.id)
                    AND d.resource_group_id IS NULL
                )
                OR EXISTS (
                    SELECT 1 FROM document_acls a
                    WHERE a.document_id = d.id
                      AND (a.principal_type = 'domain' OR (a.principal_type = 'user' AND a.principal_external_id = :user_id))
                )
                OR (
                    d.resource_group_id IS NOT NULL
                    AND EXISTS (
                        SELECT 1 FROM resource_group_acls g
                        WHERE g.tenant_id = d.tenant_id
                          AND g.source_app = d.source_app
                          AND g.resource_group_id = d.resource_group_id
                          AND g.principal_type = 'user'
                          AND g.principal_external_id = :user_id
                    )
                )
            )
        """

        async with async_session_factory() as session:
            await session.execute(text("SELECT set_config('app.current_tenant_id', :tid, true)"), {"tid": tenant_id})

            # ── Channel 1: Semantic vector search (pgvector cosine similarity) ──
            vec_rows = (await session.execute(
                text(f"""
                    SELECT c.id, c.document_id, c.chunk_index, c.text_content, d.title as doc_title,
                           d.source_app, d.resource_category, d.resource_type, d.external_id,
                           (1 - (e.embedding <=> CAST(:vec AS vector))) as raw_score
                    FROM document_chunks c
                    JOIN embeddings e ON e.chunk_id = c.id
                    JOIN documents d ON c.document_id = d.id
                    WHERE c.tenant_id = :tid
                    {acl_clause}
                    ORDER BY e.embedding <=> CAST(:vec AS vector) ASC
                    LIMIT :pool
                """),
                {"tid": tenant_id, "vec": vec_str, "user_id": user_id, "pool": VECTOR_CANDIDATE_POOL},
            )).fetchall()

            # ── Channel 2: Real Postgres full-text keyword search (ts_rank_cd) ──
            # plainto_tsquery on an all-stopword/empty query yields an empty tsquery,
            # which matches nothing (honest — not an error, just zero keyword candidates).
            kw_rows = (await session.execute(
                text(f"""
                    SELECT c.id, c.document_id, c.chunk_index, c.text_content, d.title as doc_title,
                           d.source_app, d.resource_category, d.resource_type, d.external_id,
                           GREATEST(
                               ts_rank_cd(c.text_search_vector, plainto_tsquery('english', :query)),
                               ts_rank_cd(d.title_search_vector, plainto_tsquery('english', :query)) * 1.5
                           ) as fts_rank
                    FROM document_chunks c
                    JOIN documents d ON c.document_id = d.id
                    WHERE c.tenant_id = :tid
                      {acl_clause}
                      AND (
                          c.text_search_vector @@ plainto_tsquery('english', :query)
                          OR d.title_search_vector @@ plainto_tsquery('english', :query)
                      )
                    ORDER BY fts_rank DESC
                    LIMIT :pool
                """),
                {"tid": tenant_id, "query": query, "user_id": user_id, "pool": KEYWORD_CANDIDATE_POOL},
            )).fetchall()

        # ── Candidate fusion via Reciprocal Rank Fusion (rank-based normalization —
        # avoids comparing cosine similarity and ts_rank on incompatible raw scales) ──
        candidates: Dict[str, Dict[str, Any]] = {}

        def _base_row(r) -> Dict[str, Any]:
            return {
                "id": str(r.id), "document_id": str(r.document_id), "chunk_index": r.chunk_index,
                "content": r.text_content, "doc_title": r.doc_title or "Ingested Document",
                "source_app": r.source_app, "resource_category": r.resource_category,
                "resource_type": r.resource_type, "external_id": r.external_id,
                "vector_score": None, "vector_rank": None,
                "keyword_score": None, "keyword_rank": None,
                "rrf_score": 0.0,
            }

        for rank, r in enumerate(vec_rows, start=1):
            c = candidates.setdefault(str(r.id), _base_row(r))
            c["vector_score"] = round(float(r.raw_score), 4)
            c["vector_rank"] = rank
            c["rrf_score"] += 1.0 / (RRF_K + rank)

        for rank, r in enumerate(kw_rows, start=1):
            c = candidates.setdefault(str(r.id), _base_row(r))
            c["keyword_score"] = round(float(r.fts_rank), 4)
            c["keyword_rank"] = rank
            c["rrf_score"] += 1.0 / (RRF_K + rank)

        fused = sorted(candidates.values(), key=lambda c: c["rrf_score"], reverse=True)[:RERANK_CANDIDATE_POOL]

        # ── Reranking: genuine cross-encoder scoring on the fused candidate pool only
        # (not the whole table) — this is the signal that actually decides relevance. ──
        rerank_latency_ms = 0.0
        if fused:
            t_rerank = time.time()
            reranked = cross_encoder_reranker.rerank(query, fused, top_n=len(fused))
            rerank_latency_ms = round((time.time() - t_rerank) * 1000.0, 2)
        else:
            reranked = []

        selected = [c for c in reranked if c.get("rerank_score", -999) >= RERANK_ACCEPT_THRESHOLD][:top_k]

        chunks = []
        for c in selected:
            chunks.append({
                "id": c["id"],
                "document_id": c["document_id"],
                "doc_title": c["doc_title"],
                "chunk_index": c["chunk_index"],
                "content": c["content"],
                "source_app": c["source_app"],
                "resource_category": c["resource_category"],
                "resource_type": c["resource_type"],
                "external_id": c["external_id"],
                "score": round(float(c.get("rerank_score", 0.0)), 4),
                "raw_score": c.get("vector_score") if c.get("vector_score") is not None else 0.0,
                "kw_boost": c.get("keyword_score") if c.get("keyword_score") is not None else 0.0,
                "vector_rank": c.get("vector_rank"),
                "keyword_rank": c.get("keyword_rank"),
                "rrf_score": round(c.get("rrf_score", 0.0), 5),
                "rerank_score": round(float(c.get("rerank_score", 0.0)), 4),
                "selection_reason": (
                    ("vector" if c.get("vector_rank") else "") +
                    ("+keyword" if c.get("keyword_rank") else "") +
                    "+reranker"
                ).lstrip("+"),
            })

        total_latency_ms = round((time.time() - t0) * 1000.0, 2)
        result: Dict[str, Any] = {"chunks": chunks}

        if debug:
            result["debug"] = {
                "query": query,
                "embedding_model": bge_embedder.model_name,
                "embedding_dimension": bge_embedder.dimension,
                "vector_candidate_count": len(vec_rows),
                "keyword_candidate_count": len(kw_rows),
                "fused_candidate_count": len(fused),
                "reranked_candidate_count": len(reranked),
                "selected_count": len(selected),
                "rerank_accept_threshold": RERANK_ACCEPT_THRESHOLD,
                "rerank_latency_ms": rerank_latency_ms,
                "total_latency_ms": total_latency_ms,
                "all_fused_candidates": [
                    {
                        "doc_title": c["doc_title"], "chunk_index": c["chunk_index"],
                        "vector_score": c.get("vector_score"), "vector_rank": c.get("vector_rank"),
                        "keyword_score": c.get("keyword_score"), "keyword_rank": c.get("keyword_rank"),
                        "rrf_score": round(c.get("rrf_score", 0.0), 5),
                        "rerank_score": c.get("rerank_score"),
                        "selected": c in selected,
                    }
                    for c in reranked
                ],
            }

        return result


hybrid_retriever = HybridRetriever()
