"""Domain models for the real Module 7 Research Agent slice."""
from enum import Enum
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field


class AgentExecutionState(str, Enum):
    """Simplified subset of the master architecture's full state machine — this
    agent has no WAITING_FOR_APPROVAL state yet, since its tools are read-only."""
    CREATED = "CREATED"
    PLANNING = "PLANNING"
    EXECUTING = "EXECUTING"
    OBSERVING = "OBSERVING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class PlanStep(BaseModel):
    tool_id: str
    reasoning: str
    tool_input: Dict[str, Any] = Field(default_factory=dict)


class AgentPlan(BaseModel):
    steps: List[PlanStep]
    planning_method: str  # "llm" or "deterministic_fallback"


class ToolCallRecord(BaseModel):
    tool_id: str
    tool_input: Dict[str, Any]
    output_summary: str
    success: bool
    latency_ms: float


class AgentExecutionResult(BaseModel):
    execution_id: str
    state: AgentExecutionState
    plan: Optional[AgentPlan] = None
    steps: List[ToolCallRecord] = Field(default_factory=list)
    final_result: Optional[str] = None
    error_message: Optional[str] = None
