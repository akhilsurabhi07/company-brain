"""Conversation Planner Subsystem for Module 6A."""

from typing import Dict, Any, List, Optional
from app.conversation.planner.conversation_plan import ConversationPlan, PlanningStrategy


class ConversationPlanner:
    """Evaluates query intent and produces a formal ConversationPlan object before prompt compilation."""

    def plan_conversation(self, query: str, mode: str, persona: str, history: Optional[List[Dict[str, Any]]] = None) -> ConversationPlan:
        query_lower = query.lower().strip()
        strategy = PlanningStrategy.DIRECT_ANSWER
        requires_consensus = False
        requires_explanation = False
        reasoning_depth = "STANDARD"
        temperature = 0.7
        budget = 4096
        
        # Follow-up detection
        is_follow_up = False
        narrowed_query = None
        if history and len(history) > 0:
            followup_words = ["what about", "how about", "tell me more", "explain that", "and also", "why", "who", "where"]
            if any(query_lower.startswith(w) for w in followup_words) or len(query_lower.split()) <= 4:
                is_follow_up = True
                last_turn = history[-1].get("content", "") if isinstance(history[-1], dict) else getattr(history[-1], "content", "")
                narrowed_query = f"{last_turn[:150]} -> {query}"

        # Retrieval routing
        greetings = {"hi", "hello", "hey", "good morning", "good evening"}
        retrieval_needed = True
        sources_to_query = ["vector", "keyword", "graph"]

        if query_lower in greetings or query_lower.startswith(("hi ", "hello ", "hey ")):
            retrieval_needed = False
            sources_to_query = []
        elif "graph" in query_lower or "relation" in query_lower or "entity" in query_lower:
            sources_to_query = ["graph", "vector"]

        if "audit" in query_lower or "compliance" in query_lower or "ear99" in query_lower:
            strategy = PlanningStrategy.COMPLIANCE_AUDIT
            requires_consensus = True
            requires_explanation = True
            reasoning_depth = "DEEP"
            temperature = 0.2
            budget = 8192
        elif "root cause" in query_lower or "incident" in query_lower or "why did" in query_lower:
            strategy = PlanningStrategy.ROOT_CAUSE_ANALYSIS
            requires_explanation = True
            reasoning_depth = "DEEP"
            budget = 6144
        elif "explain" in query_lower or "how to" in query_lower or "teach" in query_lower:
            strategy = PlanningStrategy.TEACHING_EXPLANATION
            requires_explanation = True
        elif "executive" in query_lower or "summary" in query_lower or "status" in query_lower:
            strategy = PlanningStrategy.EXECUTIVE_SUMMARY
            reasoning_depth = "LIGHT"
            temperature = 0.5

        return ConversationPlan(
            query_intent=query,
            strategy=strategy,
            persona=persona,
            conversation_mode=mode,
            reasoning_depth=reasoning_depth,
            temperature=temperature,
            recommended_personas=[persona],
            max_token_budget=budget,
            requires_consensus=requires_consensus,
            requires_explanation=requires_explanation,
            retrieval_needed=retrieval_needed,
            sources_to_query=sources_to_query,
            is_follow_up=is_follow_up,
            narrowed_query=narrowed_query,
        )

