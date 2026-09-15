"""
Health & Telemetry HTTP Router — Module 5 EKAP
==============================================
"""
from fastapi import APIRouter
from app.gateway.metrics.platform_analytics import get_platform_telemetry

health_router = APIRouter(prefix="/api/v1", tags=["Health"])

@health_router.get("/health")
async def get_health():
    return {"status": "HEALTHY", "module": "Module 5 EKAP", "version": "v1.0"}

@health_router.get("/metrics")
async def get_metrics():
    return {"telemetry": get_platform_telemetry()}
