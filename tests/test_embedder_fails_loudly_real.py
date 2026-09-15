"""
Real test for the honest-failure fixes made 2026-08-21 after real-question
testing uncovered two silent-fabrication bugs in the self-hosted embedding
stack:

1. BGEEmbedder.embed_texts() used to catch ANY failure (missing
   sentence-transformers/fastembed, or a real inference error) and silently
   return deterministic hash-based "synthetic" vectors, with only a print()
   warning. Vector search would then return confident-looking but
   semantically meaningless results with no error anywhere. Confirmed this
   was not hypothetical: this project's own .venv is missing
   sentence-transformers/fastembed/torch entirely (they were never in
   pyproject.toml), so any script run against .venv hit this path for real.

2. BGEReranker.rerank() (used by the real, live GraphRAG Module 4 API) had
   `except Exception: return [0.85] * len(passages)` — fabricating an
   identical "high relevance" score for every candidate on any failure,
   which also silently prevented the caller's own honest fallback
   (graphrag_reranker.py's keep-existing-ranking `except: pass`) from ever
   running, since this never actually raised.

Both must now fail loudly by default, and only degrade if a test explicitly
opts in via ALLOW_SYNTHETIC_EMBEDDINGS=1.
"""
import os
import pytest
from app.embeddings.bge_embedder import BGEEmbedder, EmbeddingModelUnavailableError
from app.embeddings.bge_reranker import BGEReranker


class _BrokenEmbedder(BGEEmbedder):
    """Simulates the exact broken environment found in this project's .venv:
    no real engine could be loaded."""
    def __init__(self):
        self._model = None
        self._engine_name = None


def test_embedder_raises_instead_of_returning_fake_vectors_by_default(monkeypatch):
    monkeypatch.delenv("ALLOW_SYNTHETIC_EMBEDDINGS", raising=False)
    broken = _BrokenEmbedder()
    with pytest.raises(EmbeddingModelUnavailableError):
        broken.embed_texts(["some real company text"])


def test_embedder_synthetic_fallback_still_available_for_explicit_test_opt_in(monkeypatch):
    monkeypatch.setenv("ALLOW_SYNTHETIC_EMBEDDINGS", "1")
    broken = _BrokenEmbedder()
    vecs = broken.embed_texts(["some real company text"])
    assert len(vecs) == 1
    assert len(vecs[0]) == BGEEmbedder.DIMENSION


def test_reranker_raises_instead_of_fabricating_uniform_high_scores(monkeypatch):
    monkeypatch.delenv("ALLOW_SYNTHETIC_EMBEDDINGS", raising=False)
    from app.embeddings import bge_reranker as reranker_module

    broken = _BrokenEmbedder()
    monkeypatch.setattr(reranker_module, "bge_embedder", broken)

    reranker = BGEReranker()
    with pytest.raises(EmbeddingModelUnavailableError):
        reranker.rerank("irrelevant control query with zero real overlap", ["totally unrelated passage"])
