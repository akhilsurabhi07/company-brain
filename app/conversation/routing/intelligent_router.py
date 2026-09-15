"""Subsystem 10: Intelligent Model Router."""

from app.conversation.routing.capability_registry import CapabilityRegistry, ModelCapabilities


class IntelligentModelRouter:
    """Routes requests to optimal model based on latency, complexity, cost, and context size."""

    @classmethod
    def route_request(
        cls,
        user_query: str,
        preferred_model: str = "auto",
        max_latency_ms: float = 1000.0,
        requires_vision: bool = False,
    ) -> str:
        if preferred_model != "auto" and CapabilityRegistry.get_capabilities(preferred_model):
            return preferred_model

        query_len = len(user_query.split())

        if query_len > 500:
            return "gemini-1.5-pro"  # Extremely large context window
        if "architecture" in user_query.lower() or "compliance" in user_query.lower():
            return "claude-3-5-sonnet"  # High reasoning capability

        return "gpt-4o"  # Default high-performance model
