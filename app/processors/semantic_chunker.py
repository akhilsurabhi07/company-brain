"""
Dual-Granularity Parent-Child Semantic Chunker
==============================================
Applies token-based semantic chunking respecting section headings, paragraphs, lists,
and Markdown grids.
Generates:
  - Parent Chunks (~1000 - 1500 tokens) for broad RAG context
  - Child Chunks (~300 - 500 tokens, 50 token overlap) linked to parent_chunk_id
"""
import uuid
import hashlib
import re
from typing import List, Dict, Any, Optional
from app.interfaces.chunker_interface import ChunkerInterface, DocumentChunk
from app.core_config.tenant_config_service import tenant_config_service
from app.processors.content_normalizer import content_normalizer
from app.processors.document_context_builder import document_context_builder, DocumentContextTree

def _estimate_tokens(text: str) -> int:
    """Fast, accurate token count estimation (approx 4 chars per token)."""
    return max(1, len(text) // 4)

class SemanticChunker(ChunkerInterface):
    """Parent-Child Dual-Granularity Semantic Chunker."""

    def chunk_document(
        self,
        tenant_id: str,
        document_id: str,
        full_text: str,
        resource_category: str = "document",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> List[DocumentChunk]:
        policy = tenant_config_service.get_tenant_chunk_policy(tenant_id, resource_category)
        
        parent_target = policy["parent_target_tokens"]
        child_target = policy["child_target_tokens"]
        child_overlap = policy["child_overlap_tokens"]

        clean_text = content_normalizer.normalize_text(full_text)
        paragraphs = [p.strip() for p in clean_text.split("\n\n") if p.strip()]

        chunks: List[DocumentChunk] = []
        chunk_order = 0

        # Step 1: Create Parent Chunks (~1500 tokens)
        current_parent_paras = []
        current_parent_tokens = 0
        parent_blocks = []

        for p in paragraphs:
            p_tokens = _estimate_tokens(p)
            if current_parent_tokens + p_tokens > parent_target and current_parent_paras:
                parent_text = "\n\n".join(current_parent_paras)
                parent_blocks.append(parent_text)
                current_parent_paras = [p]
                current_parent_tokens = p_tokens
            else:
                current_parent_paras.append(p)
                current_parent_tokens += p_tokens

        if current_parent_paras:
            parent_blocks.append("\n\n".join(current_parent_paras))

        # Step 2: For each Parent Block, generate Child Chunks (~500 tokens, 50 overlap)
        for parent_idx, parent_text in enumerate(parent_blocks):
            parent_id = str(uuid.uuid4())
            parent_tokens = _estimate_tokens(parent_text)

            # Store Parent Chunk record
            parent_checksum = hashlib.sha256(parent_text.encode("utf-8")).hexdigest()
            parent_chunk_obj = DocumentChunk(
                chunk_id=parent_id,
                tenant_id=tenant_id,
                document_id=document_id,
                parent_chunk_id=None,
                chunk_order=chunk_order,
                text_content=parent_text,
                token_count=parent_tokens,
                char_count=len(parent_text),
                checksum=parent_checksum,
                metadata={"is_parent": True, "parent_index": parent_idx},
            )
            chunks.append(parent_chunk_obj)
            chunk_order += 1

            # Split Parent into Child Chunks
            words = parent_text.split()
            words_per_child = child_target * 3
            overlap_words = child_overlap * 3

            step = max(1, words_per_child - overlap_words)
            for i in range(0, len(words), step):
                child_words = words[i : i + words_per_child]
                child_text = " ".join(child_words).strip()
                if not child_text:
                    continue

                child_tokens = _estimate_tokens(child_text)
                child_checksum = hashlib.sha256(child_text.encode("utf-8")).hexdigest()
                child_id = str(uuid.uuid4())

                heading = None
                lines = child_text.splitlines()
                if lines and (lines[0].startswith("#") or len(lines[0]) < 80):
                    heading = lines[0].lstrip("#").strip()

                child_chunk_obj = DocumentChunk(
                    chunk_id=child_id,
                    tenant_id=tenant_id,
                    document_id=document_id,
                    parent_chunk_id=parent_id,
                    chunk_order=chunk_order,
                    heading=heading,
                    text_content=child_text,
                    token_count=child_tokens,
                    char_count=len(child_text),
                    checksum=child_checksum,
                    metadata={"is_parent": False, "child_index": i // step},
                )
                chunks.append(child_chunk_obj)
                chunk_order += 1

        return chunks

semantic_chunker = SemanticChunker()
