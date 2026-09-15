"""Subsystem 18: Server-Sent Events (SSE) Streaming Engine."""

import json
from typing import AsyncGenerator, Dict, Any


class SSEStreamingEngine:
    """Formats event stream dictionaries into Server-Sent Events (SSE) standard protocol data packets."""

    @classmethod
    async def format_sse_stream(
        cls, generator: AsyncGenerator[Dict[str, Any], None]
    ) -> AsyncGenerator[str, None]:
        async for event in generator:
            event_type = event.get("type", "message")
            data_str = json.dumps(event)
            yield f"event: {event_type}\ndata: {data_str}\n\n"
