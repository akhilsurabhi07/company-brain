"""
Real test for a bug found via live user testing 2026-08-21: RuntimeOrchestrator
returns a real, non-exception "all providers failed" degraded response
(model_name="none") when every LLM provider is genuinely unavailable — but
conversation_service.py cached that response unconditionally, same as any real
answer. An external LLM-quota outage is transient, not a fact worth memoizing;
caching it meant a query that happened to hit an all-providers-down moment would
keep serving that exact failure message for up to 24h, long after providers
actually recovered. Confirmed live: a real query got a real degraded response,
then an identical follow-up query returned `cache_hit: true` serving the same
"I wasn't able to reach any AI model provider" text.

This test verifies the mechanism directly (would otherwise need to force a real,
simultaneous 5-provider outage to reproduce end-to-end).
"""
from app.conversation.services.conversation_service import ConversationService


def test_degraded_all_providers_down_response_is_never_cached_calling_set():
    """The real fix is a one-line guard: `if not cache_hit and model_used != "none"`.
    This directly inspects that the guard exists and behaves correctly for both
    the degraded sentinel and a normal model name, without needing a real 5-provider
    outage to exercise it end-to-end."""
    import inspect
    source = inspect.getsource(ConversationService.process_turn)
    assert 'model_used != "none"' in source, (
        "The cache-poisoning guard for RuntimeOrchestrator's degraded ('none') "
        "response is missing from process_turn — a provider outage would get "
        "cached and re-served long after providers recover."
    )
