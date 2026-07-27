"""
Chunker Clean Interface
======================
Abstract base interface for semantic document chunkers.
"""
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field

class DocumentChunk(BaseModel):
    chunk_id: str
    tenant_id: str
    document_id: str
    parent_chunk_id: Optional[str] = None  # Parent chunk ID for dual-granularity RAG
    page_id: Optional[str] = None
    section_id: Optional[str] = None
    chunk_order: int
    heading: Optional[str] = None
    text_content: str
    token_count: int
    char_count: int
    language_code: str = "en"
    checksum: str
    # Multi-dimensional scores
    structural_score: float = 1.0
    semantic_score: float = 1.0
    business_score: float = 1.0
    importance_score: float = 1.0
    metadata: Dict[str, Any] = Field(default_factory=dict)

class ChunkerInterface(ABC):
    """Abstract interface for document chunking engines."""

    @abstractmethod
    def chunk_document(
        self,
        tenant_id: str,
        document_id: str,
        full_text: str,
        resource_category: str = "document",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> List[DocumentChunk]:
        pass
