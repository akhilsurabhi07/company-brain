# Module 6A — Runtime Orchestrator & Provider Health Monitor

## Runtime Orchestration
The `RuntimeOrchestrator` manages execution lifecycle across diverse LLM providers, ensuring high availability, failover, retries, and cancellation handling.

## Provider Health Monitoring
The `ProviderHealthMonitor` continuously records:
- P95 Latency (`latency_ms_p95`)
- Error Rate (`error_rate`)
- Circuit Breaker State (`circuit_broken`)

When a provider's error rate exceeds 50%, the circuit breaker opens, marking the provider as unavailable for 30 seconds before attempting half-open recovery. `IntelligentModelRouter` automatically routes requests to alternative healthy providers.
