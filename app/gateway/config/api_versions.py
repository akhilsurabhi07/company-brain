"""
API Version Registry Settings — Module 5 EKAP
============================================
"""
from typing import Dict
from pydantic import BaseModel, Field

class APIVersionMetadata(BaseModel):
    version: str
    status: str  # ACTIVE, DEPRECATED, SUNSET
    sunset_date: str = ""

class APIVersionRegistryConfig(BaseModel):
    versions: Dict[str, APIVersionMetadata] = Field(default_factory=lambda: {
        "v1": APIVersionMetadata(version="v1", status="ACTIVE"),
        "v2": APIVersionMetadata(version="v2", status="ACTIVE")
    })

api_version_config = APIVersionRegistryConfig()
