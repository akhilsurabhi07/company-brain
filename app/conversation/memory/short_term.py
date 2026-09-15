"""Subsystem 2: Short-Term Memory."""

from typing import List
from app.conversation.domain.context import ConversationTurn


class ShortTermMemory:
    """Manages short-term multi-turn conversation memory for active turns."""

    def __init__(self, max_turns: int = 10):
        self.max_turns = max_turns
        self.turns: List[ConversationTurn] = []

    def add_turn(self, turn: ConversationTurn) -> None:
        self.turns.append(turn)
        if len(self.turns) > self.max_turns:
            self.turns = self.turns[-self.max_turns:]

    def get_recent_turns(self) -> List[ConversationTurn]:
        return list(self.turns)
