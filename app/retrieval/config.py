"""
Module 4 Retrieval Configuration
================================
"""
from pydantic_settings import BaseSettings

class RetrievalConfig(BaseSettings):
    EMBEDDING_MODEL: str = "BAAI/bge-large-en-v1.5"
    RERANKER_MODEL: str = "BAAI/bge-reranker-large"
    CACHE_TTL_SECONDS: int = 3600
    GRAPH_MAX_HOPS: int = 2
    TOP_K_CHUNKS: int = 20
    TOP_K_RERANKED: int = 10
    RESOURCE_BUDGET_MS: int = 500
    P50_TARGET_MS: int = 500
    P95_TARGET_MS: int = 1200

retrieval_config = RetrievalConfig()
