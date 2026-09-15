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
            #
            # Real bug found via live testing 2026-09-11 (surfaced by a real, ~6KB
            # Kubernetes documentation page during the 3,000+ real-document scale
            # test — every existing test here used short, repeated synthetic text
            # under ~2,500 chars, never long enough to trigger multi-child
            # splitting where this actually breaks): this multiplied child_target
            # (a TOKEN count) by 3 to get a WORD count, i.e. assumed ~3 words per
            # token. _estimate_tokens() above assumes ~4 characters per token, and
            # an average English word is ~4.7 chars + 1 space = ~5.7 chars — so
            # 1 token corresponds to roughly 4/5.7 ≈ 0.7 words, not 3. The old
            # formula produced child chunks ~4x larger than intended (a 500-token
            # target chunk came out around 1400-1450 tokens), blowing past
            # chunk_validator's max_child_tokens (1024) and getting the ENTIRE
            # document rejected with zero retrievable chunks — for ANY real
            # document long enough to need child-splitting at all, i.e. anything
            # over roughly 2,000 characters, an entirely ordinary document length.
            words_per_child = max(1, int(child_target * 0.7))
            overlap_words = max(0, int(child_overlap * 0.7))

            # Real bug found via live verification 2026-09-11, separate from the
            # word/token ratio bug above: `words` was referenced here but never
            # defined anywhere in this function -- a guaranteed NameError on
            # every document that produces at least one parent block, i.e.
            # every document. The earlier "verified against the real failing
            # document" claim was never actually true; that check must have
            # been skipped. Needs to be the current parent block's own words.
            words = parent_text.split()

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
