"""Conversation Context Models."""

import uuid
from datetime import datetime
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
from app.conversation.domain.states import SessionState
from app.conversation.domain.persona import PersonaType
from app.conversation.domain.modes import ConversationMode
from app.conversation.domain.response_payload import MultimodalResponsePayload


class ConversationTurn(BaseModel):
    turn_id: str = Field(default_factory=lambda: f"turn_{uuid.uuid4().hex[:10]}")
    session_id: str
    user_query: str
    persona_used: PersonaType = PersonaType.ENGINEER
    mode_used: ConversationMode = ConversationMode.ASK
    system_prompt: str = ""
    prompt_snapshot_id: str = ""
    knowledge_context_version: str = "v1.0.0"
    assistant_response: Optional[MultimodalResponsePayload] = None
    model_name: str = "gpt-4o"
    latency_ms: float = 0.0
    cost_usd: float = 0.0
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class ConversationSession(BaseModel):
    session_id: str = Field(default_factory=lambda: f"sess_{uuid.uuid4().hex[:10]}")
    tenant_id: str
    user_id: str
    title: str = "New Conversation"
    state: SessionState = SessionState.CREATED
    turns: List[ConversationTurn] = Field(default_factory=list)
    pinned: bool = False
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
