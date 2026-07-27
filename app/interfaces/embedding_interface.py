"""
Embedding Provider Interface
============================
Provider-agnostic interface for generating vector embeddings.
"""
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from pydantic import BaseModel

class VectorEmbedding(BaseModel):
    chunk_id: str
    tenant_id: str
    document_id: str
    model_name: str
    dimension: int
    vector: List[float]
    checksum: str
    version: int = 1

class EmbeddingProviderInterface(ABC):
    """Abstract interface for embedding generation models."""

    @property
    @abstractmethod
    def model_name(self) -> str:
        pass

    @property
    @abstractmethod
    def dimension(self) -> int:
        pass

    @abstractmethod
    def embed_texts(self, texts: List[str]) -> List[List[float]]:
        """Batch embedding generation interface."""
        pass
