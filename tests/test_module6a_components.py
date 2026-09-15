"""Test Suite 1: Module 6A Subsystem Component Tests."""

import pytest
from app.conversation.domain.states import SessionState, SessionStateMachine
from app.conversation.prompts.compiler import PromptCompiler
from app.conversation.prompts.registry import PromptRegistry
from app.conversation.routing.capability_registry import CapabilityRegistry
from app.conversation.routing.intelligent_router import IntelligentModelRouter


def test_session_state_machine():
    curr = SessionState.CREATED
    nxt = SessionStateMachine.transition(curr, SessionState.ACTIVE)
    assert nxt == SessionState.ACTIVE


def test_prompt_registry():
    tmpl = PromptRegistry.get_template("ARCHITECTURE_REVIEW")
    assert tmpl is not None
    assert tmpl.version == "v2.1.0"


def test_prompt_compiler():
    compiled = PromptCompiler.compile(
        prompt_name="ARCHITECTURE_REVIEW",
        user_query="How does Redis caching improve throughput?",
        knowledge_context="Redis reduces latency by 45%",
        persona="ENGINEER",
    )
    assert compiled.prompt_hash is not None
    assert "Redis" in compiled.compiled_text


def test_capability_registry_and_router():
    caps = CapabilityRegistry.get_capabilities("gpt-4o")
    assert caps.context_window_tokens == 128000

    model = IntelligentModelRouter.route_request("Review architecture of database")
    assert model == "claude-3-5-sonnet"
