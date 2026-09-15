# Module 6A — Enterprise Conversational Intelligence Platform (ECIP) Architecture

## Overview
Module 6A is the backend conversational intelligence engine for Company Brain. It consumes `KnowledgeContext v1` from Modules 1–5 and transforms it into grounded multi-turn enterprise conversations.

## Architecture Topology
```text
User Message -> Session Manager -> Memory -> Conversation Planner -> Prompt Compiler
  -> Runtime Orchestrator -> Provider Health Monitor -> Model Router -> Provider Layer
  -> Multi-LLM Consensus -> Grounding Guard -> Citation Validator -> Review Engine
  -> Output Guard -> Streaming -> Analytics -> Event Publisher -> Timeline / Replay -> Response
```

## Subsystems Map (1 to 20)
1. **Session State Machine**: `CREATED` -> `ACTIVE` -> `SUMMARIZED` -> `ARCHIVED` -> `EXPIRED`
2. **Conversation Memory**: Sliding window token budgeting & short-term memory
3. **Conversation Planner**: Evaluates query intent & strategy (`EXECUTIVE`, `TECHNICAL`, `ROOT_CAUSE`, `COMPLIANCE`)
4. **Prompt Compiler**: Assembles system prompt, policy, history, context, schema, and style with SHA-256 snapshot hashing
5. **Prompt Registry**: Versioned prompt templates across 10 enterprise personas and modes
6. **KnowledgeContext Composer**: Consumes `KnowledgeContext v1` without contract mutation
7. **Token Budget Optimizer**: Evidence ranking and token optimization
8. **Runtime Orchestrator**: Handles retries, failover, cancellation, and provider timeouts
9. **Provider Health Monitor**: Real-time availability, latency, error rate, and circuit breaking
10. **Provider Layer**: Adapters for OpenAI, Anthropic, Gemini, Azure, Ollama, vLLM
11. **Capability Registry**: Tracks model specifications (context window, cost, latency, vision)
12. **Intelligent Model Router**: Dynamic model routing based on query complexity, cost, and provider health
13. **Multi-LLM Consensus Engine**: Synthesizes agreement across GPT + Claude + Gemini
14. **Grounding Guard**: Validates that all generated claims exist in `KnowledgeContext`
15. **Citation Validator**: Sentence-level citation mapping `[1]`
16. **AI Response Review Engine**: Validates completeness, missing sections, and formatting
17. **Output Guard**: Scans and redacts leaked secrets, API keys, passwords, and PII
18. **Explanation Engine**: Generates reasoning summaries for "Why?" questions
19. **SSE Streaming Engine**: Standard Server-Sent Events token & status packet streaming
20. **Event Publisher**: Emits structured conversation events (`ConversationStarted`, `GroundingRejected`, `ProviderChanged`)
21. **Conversation Timeline & Replay**: SHA-256 prompt snapshots, turn-by-turn trace recording, and deterministic replay
