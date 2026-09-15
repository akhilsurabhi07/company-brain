"""Subsystem 2: Sliding Window Token Budget Manager."""

from typing import List, Tuple
from app.conversation.domain.context import ConversationTurn


class WindowManager:
    """Manages sliding window turn selection based on token budgeting constraints."""

    @staticmethod
    def estimate_tokens(text: str) -> int:
        return len(text.split()) + len(text) // 4

    @classmethod
    def apply_sliding_window(
        cls, turns: List[ConversationTurn], max_token_budget: int = 4000
    ) -> List[ConversationTurn]:
        selected = []
        accumulated_tokens = 0

        for turn in reversed(turns):
            turn_tokens = cls.estimate_tokens(turn.user_query)
            if turn.assistant_response:
                turn_tokens += cls.estimate_tokens(turn.assistant_response.text_content)

            if accumulated_tokens + turn_tokens > max_token_budget:
                break

            accumulated_tokens += turn_tokens
            selected.append(turn)

        return list(reversed(selected))
