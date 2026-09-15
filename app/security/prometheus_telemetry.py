import time
from typing import Dict, Tuple
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST

# Model USD Pricing per 1k tokens (Input, Output)
MODEL_PRICING: Dict[str, Tuple[float, float]] = {
    "gpt-4o": (0.005, 0.015),
    "gpt-4-turbo": (0.010, 0.030),
    "claude-3-5-sonnet": (0.003, 0.015),
    "gemini-1.5-pro": (0.00125, 0.005),
    "default": (0.002, 0.008)
}

# 1. HTTP Request Metrics
HTTP_REQUESTS_TOTAL = Counter(
    "company_brain_http_requests_total",
    "Total HTTP requests handled by Company Brain API",
    ["tenant_id", "endpoint", "status_code"]
)

# 2. LLM Token Usage Counter
LLM_TOKENS_TOTAL = Counter(
    "company_brain_llm_tokens_total",
    "Total LLM tokens consumed",
    ["tenant_id", "provider", "model", "token_type"]
)

# 3. LLM Cost USD Counter (Tokens x Provider Pricing Rate)
LLM_COST_USD_TOTAL = Counter(
    "company_brain_llm_cost_usd_total",
    "Total estimated USD cost for LLM usage",
    ["tenant_id", "provider", "model"]
)

# 4. Retrieval & Turn Latency Histogram
RETRIEVAL_LATENCY_SECONDS = Histogram(
    "company_brain_retrieval_latency_seconds",
    "Latency of GraphRAG retrieval and answer generation in seconds",
    ["tenant_id", "stage"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)
)

class TelemetryTracker:
    @staticmethod
    def record_request(tenant_id: str, endpoint: str, status_code: int):
        HTTP_REQUESTS_TOTAL.labels(
            tenant_id=tenant_id or "unknown",
            endpoint=endpoint,
            status_code=str(status_code)
        ).inc()

    @staticmethod
    def record_llm_usage(tenant_id: str, provider: str, model: str, prompt_tokens: int, completion_tokens: int):
        tid = tenant_id or "unknown"
        p = provider or "openai"
        m = model or "gpt-4o"

        LLM_TOKENS_TOTAL.labels(tenant_id=tid, provider=p, model=m, token_type="prompt").inc(prompt_tokens)
        LLM_TOKENS_TOTAL.labels(tenant_id=tid, provider=p, model=m, token_type="completion").inc(completion_tokens)

        # Calculate estimated USD cost
        rates = MODEL_PRICING.get(m.lower(), MODEL_PRICING["default"])
        cost = ((prompt_tokens / 1000.0) * rates[0]) + ((completion_tokens / 1000.0) * rates[1])
        LLM_COST_USD_TOTAL.labels(tenant_id=tid, provider=p, model=m).inc(cost)

    @staticmethod
    def record_latency(tenant_id: str, stage: str, duration_seconds: float):
        RETRIEVAL_LATENCY_SECONDS.labels(
            tenant_id=tenant_id or "unknown",
            stage=stage
        ).observe(duration_seconds)

def get_prometheus_metrics() -> Tuple[bytes, str]:
    """Generate Prometheus exposition format output."""
    return generate_latest(), CONTENT_TYPE_LATEST
