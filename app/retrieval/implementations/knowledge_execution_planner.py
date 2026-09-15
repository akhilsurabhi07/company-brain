"""
Knowledge Execution Planner Implementation — Module 4
======================================================
Multi-Signal Query Optimizer generating RetrievalPlan based on QueryAnalysis,
Candidate Confidence Tiers, Cost Model, Entities, Department Scope, and Constraints.
"""
import uuid
from app.retrieval.interfaces.planner import IExecutionPlanner
from app.retrieval.domain.query import QueryAnalysis, RetrievalPlan
from app.retrieval.domain.retrieval import RetrievalPipelineContext

class KnowledgeExecutionPlanner(IExecutionPlanner):
    """Generates execution plan specifying retrieval strategies, hop depth, cost units, and budgets."""

    async def plan(self, ctx: RetrievalPipelineContext, analysis: QueryAnalysis) -> RetrievalPlan:
        strategies = ["dense", "bm25"]
        hop_depth = 2
        resource_budget_ms = 500

        # High/Medium Candidate Intent Signals
        high_medium_intents = [
            c.intent_name for c in analysis.ranked_intents if c.tier in ["HIGH", "MEDIUM"]
        ]

        # Multi-Signal Rule 1: Include Graph Search if graph-heavy intent or entities exist
        if any(i in high_medium_intents for i in ["RiskAnalysis", "DependencyLookup", "EntityOwnership", "ProjectStatus", "Comparison"]) or analysis.entities:
            if "graph" not in strategies:
                strategies.append("graph")

        # Multi-Signal Rule 2: Deep Hop Traversal for timelines or multi-entity comparisons
        if "timeline" in analysis.output_constraints or len(analysis.entities) > 1 or "Comparison" in high_medium_intents:
            hop_depth = 3

        # Multi-Signal Rule 3: Low-Confidence Fallback (Top candidate tier is LOW < 0.60)
        top_tier = analysis.ranked_intents[0].tier if analysis.ranked_intents else "LOW"
        if top_tier == "LOW":
            # Broad fallback: trigger all 3 retrievers and allocate higher latency budget
            strategies = ["dense", "bm25", "graph"]
            resource_budget_ms = 750

        # Planner Cost Model Computation
        cost_units = 1  # BM25 baseline
        if "dense" in strategies:
            cost_units += 2
        if "graph" in strategies:
            cost_units += 3
        if hop_depth >= 3:
            cost_units += 2  # Multi-hop traversal cost

        return RetrievalPlan(
            plan_id=str(uuid.uuid4()),
            strategies=strategies,
            hop_depth=hop_depth,
            confidentiality_level="Internal",
            resource_budget_ms=resource_budget_ms,
            estimated_cost_units=cost_units,
            retrieval_engine_version="v1.0"
        )

execution_planner = KnowledgeExecutionPlanner()
