"""Conversation Timeline and Replay Engine for Module 6A."""

import time
import hashlib
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field
from app.conversation.domain.response_state import ResponseState


class TurnTrace(BaseModel):
    turn_id: str
    session_id: str
    user_query: str
    prompt_hash_sha256: str
    provider_used: str
    state: ResponseState
    latency_ms: float
    token_count: int
    response_text: str
    timestamp: float = Field(default_factory=time.time)


class ConversationTimeline:
    """Records turn-by-turn detailed execution trace and prompt SHA256 snapshots for audit and replay."""

    def __init__(self):
        self._traces: List[TurnTrace] = []

    def record_turn(
        self,
        turn_id: str,
        session_id: str,
        user_query: str,
        compiled_prompt: str,
        provider_used: str,
        state: ResponseState,
        latency_ms: float,
        token_count: int,
        response_text: str,
    ) -> TurnTrace:
        prompt_hash = hashlib.sha256(compiled_prompt.encode("utf-8")).hexdigest()
        trace = TurnTrace(
            turn_id=turn_id,
            session_id=session_id,
            user_query=user_query,
            prompt_hash_sha256=prompt_hash,
            provider_used=provider_used,
            state=state,
            latency_ms=latency_ms,
            token_count=token_count,
            response_text=response_text,
        )
        self._traces.append(trace)
        return trace

    def get_timeline(self, session_id: str) -> List[TurnTrace]:
        return [t for t in self._traces if t.session_id == session_id]

    def replay_turn(self, turn_id: str) -> Optional[TurnTrace]:
        for t in self._traces:
            if t.turn_id == turn_id:
                return t
        return None
