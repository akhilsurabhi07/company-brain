"""
Server-Sent Events (SSE) Stream Engine — Module 5 EKAP
======================================================
Streams real-time pipeline execution events to UI clients.
"""
import json
import asyncio
from typing import AsyncGenerator, Dict, Any
from app.retrieval.domain.context import KnowledgeContext

class SSEStreamer:
    """Generates Server-Sent Events (SSE) formatted text streams."""

    async def stream_pipeline_progress(self, query: str, context: KnowledgeContext) -> AsyncGenerator[str, None]:
        events = [
            ("query_received", {"query": query, "status": "RECEIVED"}),
            ("intent_analyzed", {"intent": context.intent, "confidence": context.confidence.overall}),
            ("evidence_retrieved", {"count": len(context.retrieved_chunks)}),
            ("facts_synthesized", {"facts_count": len(context.derived_facts)}),
            ("context_finalized", {"schema_version": context.schema_version, "status": "COMPLETE"})
        ]

        for event_name, payload in events:
            data = json.dumps(payload)
            yield f"event: {event_name}\ndata: {data}\n\n"
            await asyncio.sleep(0.05)  # Simulate real-time streaming cadence

sse_streamer = SSEStreamer()
