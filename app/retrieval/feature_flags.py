"""
Module 4 Retrieval Feature Flags
================================
"""
from pydantic import BaseModel

class RetrievalFeatureFlags(BaseModel):
    enable_graph: bool = True
    enable_timeline: bool = True
    enable_cache: bool = True
    enable_reranker: bool = True
    enable_gap_detection: bool = True

default_feature_flags = RetrievalFeatureFlags()
