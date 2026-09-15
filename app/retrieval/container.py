"""
Dependency Injection Container — Module 4
=========================================
Wires together interface abstractions, component registry, and implementations.
"""
from app.retrieval.component_registry import component_registry
from app.retrieval.implementations.query_understanding import QueryUnderstandingEngine
from app.retrieval.implementations.knowledge_execution_planner import KnowledgeExecutionPlanner
from app.retrieval.implementations.retrieval_policy_engine import retrieval_policy_engine
from app.retrieval.implementations.knowledge_graph_retriever import KnowledgeGraphRetriever
from app.retrieval.implementations.hybrid_retriever import hybrid_retriever
from app.retrieval.implementations.graphrag_reranker import graphrag_reranker
from app.retrieval.implementations.knowledge_context_builder import knowledge_context_builder

class Container:
    """Dependency Injection Container."""

    def __init__(self):
        self.query_intelligence = QueryUnderstandingEngine()
        self.execution_planner = KnowledgeExecutionPlanner()
        self.policy_engine = retrieval_policy_engine
        self.graph_retriever = KnowledgeGraphRetriever()
        self.reranker = graphrag_reranker
        self.context_builder = knowledge_context_builder

        # Register in registry
        component_registry.register_retriever("graph", self.graph_retriever)
        component_registry.register_reranker("cross_encoder", self.reranker)

container = Container()
