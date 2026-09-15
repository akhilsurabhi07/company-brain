import abc
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
from app.agents.agent_trace import AgentTraceTracker

class AgentTaskContext(BaseModel):
    """Execution context passed down to subagent workers."""
    task_id: str
    tenant_id: str
    user_id: str
    user_query: str
    subtask_query: str
    tenant_tier: str = "default"
    trace_tracker: Optional[Any] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    class Config:
        arbitrary_types_allowed = True

class AgentResult(BaseModel):
    """Structured result returned by a subagent worker."""
    agent_name: str
    success: bool
    retrieved_chunks: List[Dict[str, Any]] = Field(default_factory=list)
    citations: List[str] = Field(default_factory=list)
    summary_text: str = ""
    error_message: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

class BaseSubagent(abc.ABC):
    """Abstract base class for all isolated subagent workers."""

    @property
    @abc.abstractmethod
    def agent_name(self) -> str:
        pass

    @abc.abstractmethod
    async def execute(self, context: AgentTaskContext) -> AgentResult:
        pass
