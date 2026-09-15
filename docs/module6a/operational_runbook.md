# Module 6A — Operational Runbook & Metrics

## SLA Targets & Monitoring
- **First Streamed Token**: `<300 ms`
- **Conversation Latency (P95)**: `<2 s`
- **Memory Lookup**: `<10 ms`
- **Prompt Compilation**: `<20 ms`
- **Citation Validation**: `<20 ms`
- **Grounding Guard**: `<30 ms`

## Troubleshooting Circuit Breakers
If a provider fails (>50% error rate), `ProviderHealthMonitor` circuit breaks the provider for 30s. Check logs for `ProviderChanged` events and verify downstream API availability.
