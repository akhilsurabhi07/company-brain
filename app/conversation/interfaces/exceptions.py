class LLMProviderOfflineException(Exception):
    """Raised when an LLM provider is completely offline (e.g., 403 Forbidden, 401 Unauthorized, persistent 429 or 500+)."""
    pass
