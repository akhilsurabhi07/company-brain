"""
Telemetry Logging Module
========================
Separates:
  - Operational Metrics (queue_depth, latency_ms, gpu_memory_mb, failures, retries)
  - Business Metrics (documents_indexed, vectors_generated, searches_performed, avg_quality)
"""
import time
from typing import Dict, Any, Optional

class TelemetryLogger:
    """Enterprise Operational & Business Telemetry Logger."""

    def log_operational_metrics(
        self,
        stage: str,
        duration_ms: float,
        queue_depth: int = 0,
        gpu_utilization_pct: float = 0.0,
        success: bool = True,
        error_type: Optional[str] = None,
    ):
        print(
            f"[OPERATIONAL METRICS] Stage='{stage}' | Duration={duration_ms:.2f}ms | "
            f"QueueDepth={queue_depth} | GPU={gpu_utilization_pct}% | Success={success}"
        )

    def log_business_metrics(self, tenant_id: str, document_id: str, chunks_count: int, vectors_count: int):
        print(
            f"[BUSINESS METRICS] Tenant='{tenant_id[:8]}' | Doc='{document_id[:8]}' | "
            f"Chunks={chunks_count} | Vectors={vectors_count}"
        )

telemetry_logger = TelemetryLogger()
