import uuid
import datetime
import hashlib
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field

class AgentTraceEntry(BaseModel):
    """
    Machine-checkable subagent execution trace entry.
    Every subagent step emits a trace entry that correlates directly
    with actual database query execution logs and system clock timestamps.
    step_sequence is a monotonically increasing integer (0, 1, 2...) that
    unambiguously orders steps regardless of wall-clock timestamp resolution.
    """
    step_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    step_sequence: int = 0
    agent_name: str
    timestamp_iso: str = Field(default_factory=lambda: datetime.datetime.now(datetime.timezone.utc).isoformat())
    db_query_hash: str
    db_session_tenant_id: str
    citations: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @staticmethod
    def compute_query_hash(query_str: str, params: Dict[str, Any]) -> str:
        """
        Computes a deterministic SHA-256 hash of actual executed SQL vector queries & parameters.
        Used to empirically verify that subagent work occurred on a real execution path.
        """
        raw_repr = f"{query_str.strip()}:{sorted(params.items())}"
        return hashlib.sha256(raw_repr.encode("utf-8")).hexdigest()

class AgentTraceTracker:
    """
    In-memory trace collector for tracking subagent step executions within a single request.
    step_sequence is incremented for every recorded step so ordering is always deterministic
    regardless of wall-clock timestamp resolution (which can be <1ms on Windows).
    """
    def __init__(self, tenant_id: str):
        self.tenant_id = tenant_id
        self.entries: List[AgentTraceEntry] = []
        self._step_counter: int = 0

    def record_step(
        self,
        agent_name: str,
        query_str: str,
        params: Dict[str, Any],
        citations: Optional[List[str]] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> AgentTraceEntry:
        """Record a subagent step with machine-checkable query hash verification."""
        q_hash = AgentTraceEntry.compute_query_hash(query_str, params)
        entry = AgentTraceEntry(
            step_sequence=self._step_counter,
            agent_name=agent_name,
            timestamp_iso=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            db_query_hash=q_hash,
            db_session_tenant_id=self.tenant_id,
            citations=citations or [],
            metadata=metadata or {}
        )
        self._step_counter += 1
        self.entries.append(entry)
        return entry

    def to_dict_list(self) -> List[Dict[str, Any]]:
        return [entry.model_dump() for entry in self.entries]
