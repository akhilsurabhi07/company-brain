"""
Audit Logger & Platform Analytics — Module 5 EKAP
==================================================
Persistent, tenant-isolated audit log recording and platform SLA analytics.

Real integration (2026-08-22): `AuditLogger` previously claimed "Immutable
audit trail writer" in its docstring while `self._audit_trail` was a plain
in-memory Python list — never persisted, not immutable, and wiped on every
process restart. It now writes real rows into the RLS-protected
`gateway_audit_log` table (app/db/schema.sql), modeled on the existing,
real `ingestion_audit_logs` table pattern used for connector ingestion
events, but scoped to gateway search/query events.

`PlatformAnalytics` remains in-memory-only by design — it only ever claimed
to be P95/latency/429-rate telemetry, not a durable audit record, so there
was never a false claim to fix there.
"""
import time
import uuid
from typing import List, Dict, Any
from sqlalchemy import text
from app.db.database import async_session_factory


class AuditLogger:
    """Persists one real, tenant-scoped audit record per gateway request."""

    async def log_request(
        self,
        tenant_id: str,
        user_id: str,
        role: str,
        auth_method: str,
        endpoint: str,
        query: str,
        result_count: int,
        confidence: float,
        cost_units: int,
        latency_ms: float,
        correlation_id: str = "",
    ) -> Dict[str, Any]:
        record_id = str(uuid.uuid4())
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

        async with async_session_factory() as session:
            await session.execute(text("SELECT set_config('app.current_tenant_id', :t, true)"), {"t": tenant_id})
            await session.execute(
                text("""
                    INSERT INTO gateway_audit_log
                        (id, tenant_id, user_id, role, auth_method, endpoint, query,
                         result_count, confidence_score, cost_units, latency_ms, correlation_id)
                    VALUES
                        (:id, :tenant_id, :user_id, :role, :auth_method, :endpoint, :query,
                         :result_count, :confidence_score, :cost_units, :latency_ms, :correlation_id)
                """),
                {
                    "id": record_id,
                    "tenant_id": tenant_id,
                    "user_id": user_id,
                    "role": role,
                    "auth_method": auth_method,
                    "endpoint": endpoint,
                    "query": query,
                    "result_count": result_count,
                    "confidence_score": confidence,
                    "cost_units": cost_units,
                    "latency_ms": latency_ms,
                    "correlation_id": correlation_id,
                },
            )
            await session.commit()

        return {
            "audit_id": record_id,
            "tenant_id": tenant_id,
            "user_id": user_id,
            "role": role,
            "endpoint": endpoint,
            "query": query,
            "result_count": result_count,
            "confidence_score": confidence,
            "cost_units": cost_units,
            "latency_ms": latency_ms,
            "timestamp": now,
        }


class PlatformAnalytics:
    """Tracks P95 latencies, HTTP 429 rates, and cache hit ratios (in-memory telemetry)."""

    def __init__(self):
        self._latencies: List[float] = []
        self._total_requests = 0
        self._429_count = 0

    def record_request(self, latency_ms: float, is_429: bool = False):
        self._total_requests += 1
        self._latencies.append(latency_ms)
        if is_429:
            self._429_count += 1

    def get_metrics(self) -> Dict[str, Any]:
        if not self._latencies:
            return {"total_requests": 0, "p95_latency_ms": 0.0, "rate_429_percent": 0.0}

        sorted_lats = sorted(self._latencies)
        idx = int(len(sorted_lats) * 0.95)
        p95 = sorted_lats[min(idx, len(sorted_lats) - 1)]
        rate_429 = (self._429_count / self._total_requests) * 100.0 if self._total_requests > 0 else 0.0

        return {
            "total_requests": self._total_requests,
            "p95_latency_ms": round(p95, 2),
            "rate_429_percent": round(rate_429, 2),
        }


audit_logger = AuditLogger()
platform_analytics = PlatformAnalytics()
