"""Memory Compressor & Summary Store."""

from typing import List, Dict
from app.conversation.domain.context import ConversationTurn


class MemoryCompressor:
    """Summarizes older conversation turns into concise topic bullet points."""

    @staticmethod
    def compress_history(turns: List[ConversationTurn]) -> str:
        if not turns:
            return ""
        topics = [f"- Turn {idx+1}: {t.user_query[:50]}..." for idx, t in enumerate(turns)]
        return "Prior Conversation Summary:\n" + "\n".join(topics)


class SummaryStore:
    """Stores session summaries for compressed history access."""

    _SUMMARIES: Dict[str, str] = {}

    @classmethod
    def set_summary(cls, session_id: str, summary: str) -> None:
        cls._SUMMARIES[session_id] = summary

    @classmethod
    def get_summary(cls, session_id: str) -> str:
        return cls._SUMMARIES.get(session_id, "")
