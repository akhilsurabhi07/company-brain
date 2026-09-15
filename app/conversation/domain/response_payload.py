"""Multimodal Response Payload Models."""

from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field


class ResponseArtifact(BaseModel):
    artifact_id: str
    artifact_type: str = Field(description="code, mermaid, table, chart, document")
    title: str
    content: str
    metadata: Dict[str, Any] = Field(default_factory=dict)


class MultimodalResponsePayload(BaseModel):
    text_content: str
    citations: List[Dict[str, Any]] = Field(default_factory=list)
    artifacts: List[ResponseArtifact] = Field(default_factory=list)
    suggested_followups: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
