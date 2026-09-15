"""Telemetry & Traces Engine."""

import time
import uuid
from typing import Dict, Any, List
from pydantic import BaseModel, Field


class TraceSpan(BaseModel):
    span_id: str = Field(default_factory=lambda: f"span_{uuid.uuid4().hex[:8]}")
    name: str
    start_time: float
    duration_ms: float = 0.0
    metadata: Dict[str, Any] = Field(default_factory=dict)


class RuntimeTracer:
    """Manages spans and trace logs for execution diagnostics."""

    def __init__(self, trace_id: str = ""):
        self.trace_id = trace_id or f"trace_{uuid.uuid4().hex[:10]}"
        self.spans: List[TraceSpan] = []

    def start_span(self, name: str) -> TraceSpan:
        span = TraceSpan(name=name, start_time=time.time())
        self.spans.append(span)
        return span

    def end_span(self, span: TraceSpan, metadata: Dict[str, Any] = None) -> None:
        span.duration_ms = round((time.time() - span.start_time) * 1000.0, 2)
        if metadata:
            span.metadata.update(metadata)
