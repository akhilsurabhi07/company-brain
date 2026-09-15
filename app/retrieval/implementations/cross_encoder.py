"""
Cross-Encoder Reranker Implementation
=====================================
Uses sentence-transformers/cross-encoder (e.g. ms-marco-MiniLM-L-6-v2) to rerank top-K retrieved chunks.
Gracefully degrades to a no-op if sentence-transformers is not installed.
"""
import logging
from typing import List, Dict, Any

logger = logging.getLogger("company_brain.retrieval.cross_encoder")

try:
    from sentence_transformers import CrossEncoder
    _cross_encoder_available = True
except ImportError:
    _cross_encoder_available = False

class CrossEncoderReranker:
    MODEL_ID = "cross-encoder/ms-marco-MiniLM-L-6-v2"

    def __init__(self):
        self._model = None
        if _cross_encoder_available:
            try:
                self._model = CrossEncoder(self.MODEL_ID)
                logger.info(f"[CrossEncoderReranker] Successfully loaded {self.MODEL_ID}")
            except Exception as e:
                logger.warning(f"[CrossEncoderReranker] Failed to load {self.MODEL_ID}: {e}")
                self._model = None

    def rerank(self, query: str, chunks: List[Dict[str, Any]], top_n: int = 5) -> List[Dict[str, Any]]:
        """
        Reranks a list of chunk dictionaries using the cross-encoder model.
        Each chunk must have a 'content' key.
        Returns the top_n chunks sorted by cross-encoder score.
        """
        if not chunks:
            return []

        if self._model is None:
            # Graceful fallback: return top_n based on their existing hybrid score
            logger.info("[CrossEncoderReranker] Neural model unavailable, bypassing reranking.")
            return sorted(chunks, key=lambda x: x.get("score", 0.0), reverse=True)[:top_n]

        # Prepare pairs for the cross-encoder: (query, document_text)
        #
        # Real root cause found via live testing 2026-08-21: a real Jira ticket
        # ("PROJ-101: Configure Multi-Tenant Row Level Security in Postgres") was
        # rejected by the reranker (-10.95, well under the -5.0 threshold) despite
        # vector search correctly ranking it #1 by a wide margin (0.72 vs ~0.5 for
        # everything else) — because the chunk's actual body text is a terse
        # implementation note ("Ensure all database sessions execute SET LOCAL
        # app.current_tenant_id before running queries.") that shares zero words
        # with a natural question about it ("row level security", "Postgres",
        # "multi-tenant" all live only in the TITLE, never in the body). This is a
        # structural pattern across ticket/PR/meeting-style documents generally,
        # not a one-off: the title often carries the entity/topic keywords a real
        # question uses, while the body is terse implementation detail.
        #
        # Verified directly against the real model: content-only scored -10.95
        # (rejected); title+content scored +5.84 (clearly accepted) for the exact
        # same real query and chunk. A genuinely irrelevant control query against
        # the same chunk (with title prefixed) still scored -11.48 — unchanged
        # from -11.46 content-only — confirming this doesn't introduce false
        # positives, it only restores context the model was missing.
        def _passage_text(chunk: Dict[str, Any]) -> str:
            title = (chunk.get("doc_title") or "").strip()
            content = chunk.get("content", "") or ""
            if title and title.lower() not in ("ingested document", "untitled document"):
                return f"{title}. {content}"
            return content

        pairs = [[query, _passage_text(chunk)] for chunk in chunks]

        try:
            # Predict scores
            scores = self._model.predict(pairs)
            
            # Attach scores to chunks
            for idx, chunk in enumerate(chunks):
                chunk["rerank_score"] = float(scores[idx])

            # Sort by rerank score descending
            reranked_chunks = sorted(chunks, key=lambda x: x.get("rerank_score", 0.0), reverse=True)
            return reranked_chunks[:top_n]
        except Exception as e:
            logger.warning(f"[CrossEncoderReranker] Inference failed: {e}. Bypassing reranking.")
            return sorted(chunks, key=lambda x: x.get("score", 0.0), reverse=True)[:top_n]

reranker = CrossEncoderReranker()
