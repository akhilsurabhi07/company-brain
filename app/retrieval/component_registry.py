"""
Component Registry — Module 4
=============================
Registry for registering and looking up retrievers, fusion strategies, and rerankers.
"""
from typing import Dict, Any, Type
from app.retrieval.interfaces.retriever import IRetriever
from app.retrieval.interfaces.fusion import IFusionEngine
from app.retrieval.interfaces.reranker import IReranker

class ComponentRegistry:
    """Enterprise registry for retrieving component implementations."""

    def __init__(self):
        self._retrievers: Dict[str, IRetriever] = {}
        self._fusion_engines: Dict[str, IFusionEngine] = {}
        self._rerankers: Dict[str, IReranker] = {}

    def register_retriever(self, name: str, retriever: IRetriever) -> None:
        self._retrievers[name] = retriever

    def get_retriever(self, name: str) -> IRetriever:
        return self._retrievers.get(name)

    def register_fusion_engine(self, name: str, engine: IFusionEngine) -> None:
        self._fusion_engines[name] = engine

    def get_fusion_engine(self, name: str) -> IFusionEngine:
        return self._fusion_engines.get(name)

    def register_reranker(self, name: str, reranker: IReranker) -> None:
        self._rerankers[name] = reranker

    def get_reranker(self, name: str) -> IReranker:
        return self._rerankers.get(name)

component_registry = ComponentRegistry()
