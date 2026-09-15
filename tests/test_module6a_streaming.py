"""Test Suite 3: Module 6A Streaming Tests."""

import pytest
from app.conversation.interfaces.llm_provider import GenerationRequest
from app.conversation.runtime.orchestrator import RuntimeOrchestrator
from app.conversation.streaming.sse_engine import SSEStreamingEngine


@pytest.mark.asyncio
async def test_sse_streaming_engine():
    orchestrator = RuntimeOrchestrator()
    req = GenerationRequest(prompt="Stream test", persona="ENGINEER", mode="ASK")

    generator = orchestrator.execute_streaming(req)
    sse_packets = []
    async for sse_pkt in SSEStreamingEngine.format_sse_stream(generator):
        sse_packets.append(sse_pkt)

    assert len(sse_packets) > 0
    assert "event: token" in sse_packets[0]
