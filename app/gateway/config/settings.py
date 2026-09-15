"""
Gateway Settings — Module 5 EKAP
================================
Environment configuration settings for the Enterprise Knowledge Access Platform.
"""
import os
from pydantic import BaseModel, Field

class GatewaySettings(BaseModel):
    environment: str = Field(default_factory=lambda: os.getenv("PCB_ENV", "production"))
    debug: bool = Field(default_factory=lambda: os.getenv("PCB_DEBUG", "false").lower() == "true")
    api_prefix: str = "/api/v1"
    default_tenant_id: str = "default_tenant"
    max_request_payload_bytes: int = 10 * 1024 * 1024  # 10 MB limit
    default_timeout_ms: int = 10000  # 10s default timeout
    sse_ping_interval_seconds: int = 15

gateway_settings = GatewaySettings()
