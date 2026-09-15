"""Test Suite 5: Module 6A Memory Tests."""

import pytest
from app.conversation.domain.context import ConversationTurn
from app.conversation.memory.short_term import ShortTermMemory
from app.conversation.memory.window_manager import WindowManager


def test_memory_and_window_budget():
    mem = ShortTermMemory(max_turns=3)
    for i in range(5):
        turn = ConversationTurn(session_id="sess_1", user_query=f"Turn query {i}")
        mem.add_turn(turn)

    recent = mem.get_recent_turns()
    assert len(recent) == 3
    assert recent[-1].user_query == "Turn query 4"

    budgeted = WindowManager.apply_sliding_window(recent, max_token_budget=1000)
    assert len(budgeted) == 3
