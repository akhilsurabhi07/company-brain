"""
Multi-Dimensional Chunk Validator & Scorer
==========================================
Evaluates 3 explicit sub-scores for each chunk:
  - structural_score: Heading vs paragraph vs footer
  - semantic_score: Dense information ratio vs noise
  - business_score: Presence of financial figures, dates, tables, entities
Computes overall importance_score and filters junk/empty/oversized chunks.
"""
import re
from typing import List, Tuple
from app.interfaces.chunker_interface import DocumentChunk

class ChunkValidator:
    """Multi-Dimensional Chunk Validator & Scorer."""

    @staticmethod
    def compute_scores(chunk: DocumentChunk) -> DocumentChunk:
        text = chunk.text_content
        
        # 1. Structural Score (Headings & Tables get higher structural weight)
        struct_score = 1.0
        if chunk.heading or text.startswith("#"):
            struct_score += 0.3
        if "|" in text and "---" in text:  # Markdown Grid Table
            struct_score += 0.4
        if len(text) < 50 and not chunk.heading:  # Short footnote/footer
            struct_score -= 0.5

        # 2. Semantic Score (Information density / unique words ratio)
        words = text.split()
        if not words:
            sem_score = 0.0
        else:
            unique_ratio = len(set(words)) / len(words)
            sem_score = min(1.5, max(0.2, unique_ratio * 1.2))

        # 3. Business Score (Presence of numbers, currencies, dates, key entities)
        bus_score = 1.0
        if re.search(r"\$\d+|\b\d+(\.\d+)?%|\b20\d{2}\b", text):  # Financials / Percentages / Years
            bus_score += 0.5
        if re.search(r"\b(Revenue|Growth|Target|Quarter|Executive|Contract|API|Database)\b", text, re.IGNORECASE):
            bus_score += 0.3

        # Normalize scores to range [0.0, 1.0]
        chunk.structural_score = round(min(1.0, max(0.0, struct_score / 1.7)), 3)
        chunk.semantic_score = round(min(1.0, max(0.0, sem_score / 1.5)), 3)
        chunk.business_score = round(min(1.0, max(0.0, bus_score / 1.8)), 3)

        # Weighted importance score
        chunk.importance_score = round(
            0.3 * chunk.structural_score + 0.3 * chunk.semantic_score + 0.4 * chunk.business_score,
            3,
        )
        return chunk

    def validate_and_score_chunks(
        self, chunks: List[DocumentChunk], min_tokens: int = 10, max_tokens: int = 1024
    ) -> Tuple[List[DocumentChunk], List[str]]:
        """
        Validates chunks and computes scores.
        Returns (valid_chunks, rejection_reasons).
        """
        valid_chunks: List[DocumentChunk] = []
        reasons: List[str] = []
        seen_checksums = set()

        for chunk in chunks:
            # 1. Reject Empty Chunks
            if not chunk.text_content or not chunk.text_content.strip():
                reasons.append(f"Rejected chunk {chunk.chunk_id}: Empty content")
                continue

            # 2. Reject Short Junk Chunks (< min_tokens unless it's a parent)
            if chunk.token_count < min_tokens and not chunk.metadata.get("is_parent"):
                reasons.append(f"Rejected chunk {chunk.chunk_id}: Token count ({chunk.token_count}) below min threshold ({min_tokens})")
                continue

            # 3. Reject Over-sized Chunks (parents exempt, same as the min-token
            # rule above — real bug found the same session as the word/token
            # ratio fix in semantic_chunker.py: max_tokens=1024 is a CHILD-chunk
            # ceiling (matches chunking_config.py's own max_child_tokens), but
            # this was applied uniformly to parent chunks too, even though every
            # resource category's parent_target_tokens (800-2000) legitimately
            # exceeds 1024 by design ("document": 1500, "legal": 2000). A
            # correctly-sized parent chunk working exactly as intended was being
            # rejected purely for being a parent, on every document that produced
            # one — not a hypothetical, reproduced on a real Kubernetes doc.
            if chunk.token_count > max_tokens and not chunk.metadata.get("is_parent"):
                reasons.append(f"Rejected chunk {chunk.chunk_id}: Token count ({chunk.token_count}) exceeds max threshold ({max_tokens})")
                continue

            # 4. Deduplicate Identical Chunks within Document
            if chunk.checksum in seen_checksums and not chunk.metadata.get("is_parent"):
                reasons.append(f"Rejected chunk {chunk.chunk_id}: Duplicate checksum in document")
                continue
            seen_checksums.add(chunk.checksum)

            # 5. Compute Multi-Dimensional Scores
            scored_chunk = self.compute_scores(chunk)
            valid_chunks.append(scored_chunk)

        return valid_chunks, reasons

chunk_validator = ChunkValidator()
