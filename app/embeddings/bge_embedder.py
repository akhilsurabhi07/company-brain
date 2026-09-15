"""
Self-Hosted BGE Large Embedder Engine (ONNX FastEmbed / SentenceTransformers)
=============================================================================
Uses BAAI/bge-large-en-v1.5 model (1024 dimensions) via fastembed ONNX or sentence-transformers.
"""
import math
import os
import hashlib
import logging
from typing import List
from app.interfaces.embedding_interface import EmbeddingProviderInterface

logger = logging.getLogger(__name__)


class EmbeddingModelUnavailableError(RuntimeError):
    """Raised when neither real embedding engine (sentence-transformers,
    fastembed) is available and no explicit test opt-in is set. Real-question
    testing 2026-08-21 found this path silently returning deterministic
    hash-based "synthetic" vectors on any failure, with only a print()
    warning — meaning a broken environment (or a transient real-model
    failure) would make vector search silently return semantically
    meaningless results, indistinguishable from a real degraded-but-honest
    answer. Failing loudly here matches the same principle already applied
    to RuntimeOrchestrator's provider cascade: never fabricate a result that
    looks real."""

try:
    from fastembed import TextEmbedding
    _fastembed_available = True
except ImportError:
    _fastembed_available = False

try:
    from sentence_transformers import SentenceTransformer
    _sentence_transformers_available = True
except ImportError:
    _sentence_transformers_available = False

class BGEEmbedder(EmbeddingProviderInterface):
    """Self-Hosted BAAI/bge-large-en-v1.5 Embedding Engine."""

    MODEL_ID = "BAAI/bge-large-en-v1.5"
    DIMENSION = 1024

    def __init__(self):
        self._model = None
        self._engine_name = None

        if _sentence_transformers_available:
            try:
                self._model = SentenceTransformer(self.MODEL_ID)
                self._engine_name = "sentence_transformers"
                print(f"[BGEEmbedder] Successfully loaded {self.MODEL_ID} via SentenceTransformers PyTorch engine.")
            except Exception as e:
                print(f"[BGEEmbedder Warning] Could not load SentenceTransformer model: {e}")
                self._model = None

        if self._model is None and _fastembed_available:
            try:
                self._model = TextEmbedding(model_name=self.MODEL_ID)
                self._engine_name = "fastembed_onnx"
                print(f"[BGEEmbedder] Successfully loaded {self.MODEL_ID} via fastembed ONNX engine.")
            except Exception as e:
                print(f"[BGEEmbedder Warning] Could not load fastembed ONNX model: {e}")
                self._model = None

    @property
    def model_name(self) -> str:
        return self.MODEL_ID

    @property
    def dimension(self) -> int:
        return self.DIMENSION

    def _generate_synthetic_vector(self, text: str) -> List[float]:
        """High-entropy deterministic 1024-dim fallback vector. ONLY used when
        ALLOW_SYNTHETIC_EMBEDDINGS=1 is explicitly set (unit tests without the
        real model installed) — never a silent production fallback."""
        vec = []
        for i in range(self.DIMENSION):
            h = hashlib.sha256(f"{text}_{i}".encode("utf-8")).digest()
            val = (int.from_bytes(h[:4], "big") / (2**32 - 1)) * 2.0 - 1.0
            vec.append(val)
        norm = math.sqrt(sum(x * x for x in vec))
        return [x / norm for x in vec]

    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        """Generates 1024-dimensional normalized vector embeddings in batches.

        Raises EmbeddingModelUnavailableError instead of silently degrading to
        fake vectors when the real model can't load or inference fails — a
        broken/incomplete environment must surface as a loud, honest error,
        not as vector search that quietly returns garbage with no indication
        anything is wrong. See EmbeddingModelUnavailableError docstring.
        """
        if not texts:
            return []

        if self._model is not None:
            try:
                if self._engine_name == "fastembed_onnx":
                    embeddings = list(self._model.embed(texts))
                    return [emb.tolist() for emb in embeddings]
                elif self._engine_name == "sentence_transformers":
                    embeddings = self._model.encode(
                        texts,
                        batch_size=32,
                        show_progress_bar=False,
                        normalize_embeddings=True,
                    )
                    return [emb.tolist() for emb in embeddings]
            except Exception as e:
                logger.error(f"[BGEEmbedder] Real model inference failed: {e}", exc_info=True)
                if os.environ.get("ALLOW_SYNTHETIC_EMBEDDINGS") == "1":
                    return [self._generate_synthetic_vector(t) for t in texts]
                raise EmbeddingModelUnavailableError(
                    f"BGE embedding inference failed ({e}). Refusing to return fake "
                    "vectors for real production data. Set ALLOW_SYNTHETIC_EMBEDDINGS=1 "
                    "only for tests that don't have the real model installed."
                ) from e

        logger.error(
            "[BGEEmbedder] Neither sentence-transformers nor fastembed could load "
            f"{self.MODEL_ID} — embedding model is unavailable."
        )
        if os.environ.get("ALLOW_SYNTHETIC_EMBEDDINGS") == "1":
            return [self._generate_synthetic_vector(t) for t in texts]
        raise EmbeddingModelUnavailableError(
            f"Neither sentence-transformers nor fastembed could load {self.MODEL_ID}. "
            "Install one of them (see pyproject.toml) — refusing to silently return "
            "fake vectors for real production data. Set ALLOW_SYNTHETIC_EMBEDDINGS=1 "
            "only for tests that don't have the real model installed."
        )

bge_embedder = BGEEmbedder()
