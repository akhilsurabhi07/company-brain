"""
Self-Hosted BGE Large Embedder Engine
=====================================
Uses sentence-transformers BAAI/bge-large-en-v1.5 model (1024 dimensions).
Includes CPU/GPU batching optimization and local model caching.
"""
import math
import hashlib
from typing import List
from app.interfaces.embedding_interface import EmbeddingProviderInterface

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
        if _sentence_transformers_available:
            try:
                self._model = SentenceTransformer(self.MODEL_ID)
            except Exception as e:
                print(f"[BGEEmbedder Warning] Could not load SentenceTransformer locally: {e}")
                self._model = None

    @property
    def model_name(self) -> str:
        return self.MODEL_ID

    @property
    def dimension(self) -> int:
        return self.DIMENSION

    def _generate_synthetic_vector(self, text: str) -> List[float]:
        """High-entropy deterministic 1024-dim fallback vector for testing/environments without PyTorch."""
        vec = []
        for i in range(self.DIMENSION):
            h = hashlib.sha256(f"{text}_{i}".encode("utf-8")).digest()
            val = (int.from_bytes(h[:4], "big") / (2**32 - 1)) * 2.0 - 1.0
            vec.append(val)
        norm = math.sqrt(sum(x * x for x in vec))
        return [x / norm for x in vec]

    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        """Generates 1024-dimensional normalized vector embeddings in batches."""
        if not texts:
            return []

        if self._model is not None:
            try:
                embeddings = self._model.encode(
                    texts,
                    batch_size=32,
                    show_progress_bar=False,
                    normalize_embeddings=True,
                )
                return [emb.tolist() for emb in embeddings]
            except Exception as e:
                print(f"[BGEEmbedder Error] Batch inference failed, falling back to deterministic: {e}")

        return [self._generate_synthetic_vector(t) for t in texts]

bge_embedder = BGEEmbedder()
