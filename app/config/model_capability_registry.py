"""
Embedding Model Capability Registry
===================================
Tracks model dimensions, token limits, quantization support, and latency classes.
"""
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field

class ModelCapability(BaseModel):
    model_name: str
    provider: str
    dimension: int
    max_tokens: int
    supports_quantization: bool = False
    gpu_memory_mb: int = 2048
    latency_class: str = "fast"  # 'ultra_fast', 'fast', 'balanced', 'deep'
    normalization_required: bool = True
    description: str = ""

MODEL_CAPABILITY_REGISTRY: Dict[str, ModelCapability] = {
    "BAAI/bge-large-en-v1.5": ModelCapability(
        model_name="BAAI/bge-large-en-v1.5",
        provider="sentence-transformers",
        dimension=1024,
        max_tokens=512,
        supports_quantization=True,
        gpu_memory_mb=2048,
        latency_class="fast",
        normalization_required=True,
        description="Self-hosted top-tier English embedding model (1024-dim)."
    ),
    "voyage-large-2": ModelCapability(
        model_name="voyage-large-2",
        provider="voyage",
        dimension=1536,
        max_tokens=4096,
        supports_quantization=False,
        gpu_memory_mb=0,
        latency_class="balanced",
        normalization_required=True,
        description="Voyage AI API embedding model."
    ),
    "text-embedding-3-large": ModelCapability(
        model_name="text-embedding-3-large",
        provider="openai",
        dimension=3072,
        max_tokens=8191,
        supports_quantization=False,
        gpu_memory_mb=0,
        latency_class="balanced",
        normalization_required=True,
        description="OpenAI 3rd generation large embedding model."
    ),
}

def get_model_capability(model_name: str = "BAAI/bge-large-en-v1.5") -> ModelCapability:
    """Retrieves capability specifications for a given model."""
    return MODEL_CAPABILITY_REGISTRY.get(model_name, MODEL_CAPABILITY_REGISTRY["BAAI/bge-large-en-v1.5"])
