"""
Module 7 — AI Agent Platform (real slice started 2026-08-21).

This is deliberately NOT the full multi-agent/tool-approval/memory-system platform
from the Module 7-10 master architecture doc (see that memory file) — that remains a
documented future build. This is the smallest genuinely real, safe starting slice:
one read-only Research Agent, a real 2-tool registry, real LLM-based planning with a
deterministic fallback, real execution-state tracking, and real per-run persistence.

Read-only by construction: neither tool this agent can call writes anything or takes
an external action, so there is no approval-gate requirement yet (per the master
spec, approval is mandatory once a tool can act — that's future scope, not this).
"""
