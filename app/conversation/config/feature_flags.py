"""Feature Flags configuration for Module 6A."""

from typing import Dict, Any


class ConversationFeatureFlags:
    """Manages tenant and system-level feature flags for ECIP engine."""

    _FLAGS: Dict[str, bool] = {
        "multi_llm_consensus": True,
        "explanation_mode": True,
        "reasoning_traces": True,
        "output_guard_pii": True,
        "output_guard_secrets": True,
        "response_review_engine": True,
        "citation_validation": True,
        "grounding_guard": True,
        "conversation_cache": True,
    }

    @classmethod
    def is_enabled(cls, flag_name: str, tenant_id: str = "default") -> bool:
        return cls._FLAGS.get(flag_name, True)

    @classmethod
    def set_flag(cls, flag_name: str, enabled: bool) -> None:
        cls._FLAGS[flag_name] = enabled
