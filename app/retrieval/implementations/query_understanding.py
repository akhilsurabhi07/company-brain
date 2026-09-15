"""
Query Intelligence Engine Implementation — Module 4
===================================================
Extensible Multi-Candidate Intent Classifier powered by Pluggable IntentRegistry.
Scores all candidate intents across 25+ enterprise intents, categorizes into confidence tiers
(HIGH >= 0.85, MEDIUM 0.60-0.85, LOW < 0.60), and constructs ranked candidate lists.
"""
import re
from typing import List, Dict, Any
from app.retrieval.interfaces.query import IQueryIntelligence
from app.retrieval.domain.query import QueryAnalysis, IntentCandidate, IntentConfidence
from app.retrieval.domain.intent_registry import intent_registry
from app.retrieval.domain.retrieval import RetrievalPipelineContext

class QueryUnderstandingEngine(IQueryIntelligence):
    """Analyzes incoming query text and outputs multi-candidate QueryAnalysis."""

    async def analyze(self, ctx: RetrievalPipelineContext) -> QueryAnalysis:
        q_lower = ctx.query.lower().strip()
        words = q_lower.split()

        # Step 1: Pluggable Scoring from Pluggable Intent Registry
        ranked_candidates = intent_registry.score_query(ctx.query)

        primary_candidate = ranked_candidates[0]
        primary_intent = primary_candidate.intent_name

        secondary_intents = [
            c.intent_name for c in ranked_candidates[1:] if c.tier in ["HIGH", "MEDIUM"]
        ]

        # Fetch intent metadata for default reasoning & constraints
        top_intent_def = intent_registry.get_intent(primary_intent)
        reasoning_type = top_intent_def.default_reasoning if top_intent_def else "Lookup"
        output_constraints = []
        if top_intent_def and top_intent_def.default_output_constraint:
            output_constraints.append(top_intent_def.default_output_constraint)

        output_preference = "Summary" if primary_intent == "Summarization" else "Detailed"

        # Step 2: Named Entity Recognition (NER)
        entities = []
        proj_match = re.findall(r'project\s+([a-zA-Z0-9_]+)', ctx.query, re.IGNORECASE)
        if proj_match:
            for p in proj_match:
                entities.append(f"Project {p.capitalize()}")
        else:
            capitalized_words = [w for w in ctx.query.split() if w[0].isupper() and len(w) > 2]
            if capitalized_words:
                entities.append(" ".join(capitalized_words[:2]))

        # Step 3: Department Scope Detection
        department = None
        if "legal" in q_lower:
            department = "Legal"
        elif "finance" in q_lower:
            department = "Finance"
        elif "engineering" in q_lower:
            department = "Engineering"

        # Step 4: Multi-Signal Hybrid Confidence Calculation
        intent_score = primary_candidate.confidence
        entity_score = 0.96 if len(entities) > 0 else 0.60
        graph_score = 0.92 if len(entities) > 0 else 0.50
        rules_score = 0.94 if (department or secondary_intents) else 0.70

        overall_conf = round(
            0.35 * intent_score + 0.25 * entity_score + 0.20 * graph_score + 0.20 * rules_score,
            2
        )

        confidence_obj = IntentConfidence(
            intent=intent_score,
            entities=entity_score,
            graph_match=graph_score,
            rules_match=rules_score,
            overall=overall_conf
        )

        return QueryAnalysis(
            query=ctx.query,
            primary_intent=primary_intent,
            secondary_intents=secondary_intents,
            ranked_intents=ranked_candidates,
            reasoning_type=reasoning_type,
            entities=entities,
            department_scope=department,
            output_constraints=output_constraints,
            output_preference=output_preference,
            is_ambiguous=len(words) < 3,
            confidence=confidence_obj
        )

query_understanding_engine = QueryUnderstandingEngine()
