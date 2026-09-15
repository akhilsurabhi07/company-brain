"""
Platform Telemetry & SLA Analytics — Module 5 EKAP
====================================================
"""
from typing import Dict, Any
from app.gateway.audit.audit_logger import platform_analytics

def get_platform_telemetry() -> Dict[str, Any]:
    return platform_analytics.get_metrics()
