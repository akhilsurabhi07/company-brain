"""Shared ToolResult Schema for future Module 7/8 compatibility."""

from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field


class ToolResult(BaseModel):
    tool_name: str
    status: str = Field(description="SUCCESS, FAILED, TIMED_OUT")
    execution_time_ms: float = 0.0
    artifacts: List[Dict[str, Any]] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    error_message: Optional[str] = None
