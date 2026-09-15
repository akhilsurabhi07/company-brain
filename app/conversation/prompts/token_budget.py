"""Subsystem 6: Token Budget Optimizer."""

from typing import List, Dict, Any


class TokenBudgetOptimizer:
    """Optimizes evidence ranking, context compression, and chunk prioritization to fit token limits."""

    @staticmethod
    def count_tokens(text: str) -> int:
        return len(text.split()) + len(text) // 4

    @classmethod
    def optimize_evidence_chunks(
        cls, chunks: List[Dict[str, Any]], max_tokens: int = 2048
    ) -> List[Dict[str, Any]]:
        # Sort chunks by relevance/score descending
        sorted_chunks = sorted(chunks, key=lambda c: c.get("score", 1.0), reverse=True)
        selected = []
        tokens_used = 0

        for chunk in sorted_chunks:
            text = chunk.get("content", chunk.get("text", ""))
            c_tokens = cls.count_tokens(text)
            if tokens_used + c_tokens > max_tokens:
                break
            tokens_used += c_tokens
            selected.append(chunk)

        return selected
