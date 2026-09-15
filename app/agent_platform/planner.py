"""
Real Agent Planner — Module 7.

Real planning step before any tool call, per the master architecture spec ("the
agent should not immediately call tools... it should create an internal plan").
Uses the same real LLM provider cascade (OpenAI -> Groq -> Gemini -> Anthropic ->
HuggingFace) already built and tested in Module 6A — no new LLM plumbing here.

Deterministic fallback exists because this session has repeatedly hit genuine,
simultaneous quota exhaustion across all 5 providers — a planner that hard-fails
whenever that happens would make the whole agent unusable exactly when it's needed.
The fallback is a real, sensible default plan (search knowledge, then check
decisions if the request sounds decision-related), not a fake "success".
"""
import json
import re
from app.agent_platform.domain import AgentPlan, PlanStep
from app.agent_platform.tool_registry import tool_registry
from app.conversation.runtime.orchestrator import RuntimeOrchestrator
from app.conversation.interfaces.llm_provider import GenerationRequest

_orchestrator = RuntimeOrchestrator()

_PLANNER_SYSTEM_PROMPT = """You are a research agent planner. Given a user's research \
request, produce a JSON plan: a list of steps, each with "tool_id", "reasoning", and \
"tool_input" (an object of keyword arguments for that tool).

Available tools:
- search_company_knowledge(query: str): searches the company's real ingested documents.
- get_decisions(topic: str): looks up real recorded decisions, optionally filtered by topic.

Respond with ONLY a JSON array, nothing else. Example:
[{"tool_id": "search_company_knowledge", "reasoning": "find relevant documents", "tool_input": {"query": "..."}}]
"""


def _deterministic_plan(user_request: str) -> AgentPlan:
    steps = [PlanStep(tool_id="search_company_knowledge", reasoning="Always start with a real knowledge search.", tool_input={"query": user_request})]
    if any(w in user_request.lower() for w in ["decision", "decided", "chose", "why did we", "outcome"]):
        steps.append(PlanStep(tool_id="get_decisions", reasoning="Request references a decision — check real recorded decisions too.", tool_input={"topic": user_request}))
    return AgentPlan(steps=steps, planning_method="deterministic_fallback")


async def create_plan(user_request: str, tenant_id: str, user_id: str) -> AgentPlan:
    tool_names = {t.tool_id for t in tool_registry.list_tools()}
    try:
        gen_req = GenerationRequest(
            prompt=user_request,
            raw_query=user_request,
            system_prompt=_PLANNER_SYSTEM_PROMPT,
            model_name="gpt-4o",
            temperature=0.2,
            max_tokens=500,
            tenant_id=tenant_id,
            user_id=user_id,
        )
        gen_res = await _orchestrator.execute_generation(gen_req)
        raw_text = gen_res.payload.text_content.strip()

        match = re.search(r"\[.*\]", raw_text, re.DOTALL)
        if not match:
            raise ValueError("planner LLM did not return a JSON array")
        parsed = json.loads(match.group(0))

        steps = []
        for item in parsed:
            tool_id = item.get("tool_id")
            if tool_id not in tool_names:
                continue  # never let the planner invent a tool that doesn't exist
            steps.append(PlanStep(tool_id=tool_id, reasoning=item.get("reasoning", ""), tool_input=item.get("tool_input", {})))

        if not steps:
            raise ValueError("planner LLM produced no valid steps")
        return AgentPlan(steps=steps, planning_method="llm")
    except Exception:
        return _deterministic_plan(user_request)
