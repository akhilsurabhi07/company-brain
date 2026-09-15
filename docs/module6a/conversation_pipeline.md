# Module 6A — Conversation Pipeline & Turn Execution

## Turn Execution Lifecycle

1. **Session Resolution**: Resolves or initializes session state (`CREATED` -> `ACTIVE`).
2. **Intent & Strategy Planning**: `ConversationPlanner` analyzes query intent and selects execution strategy.
3. **Prompt Compilation & Hashing**: `PromptCompiler` compiles System + Policy + Context + History into prompt string and calculates SHA-256 snapshot.
4. **Cache Lookup**: `ConversationCache` checks for existing hit using SHA-256 hash.
5. **Provider Health Check & Model Selection**: `ProviderHealthMonitor` verifies provider availability; `IntelligentModelRouter` selects target model.
6. **Execution & Consensus**: Executes single model or `MultiLLMConsensusEngine` (for Legal/Finance/Executive).
7. **Guardrail Validation**:
   - `OutputGuard` redacts secrets and PII.
   - `GroundingGuard` verifies factual support in `KnowledgeContext`.
   - `CitationValidator` maps claims to sentence-level citations.
   - `AIResponseReviewEngine` validates structure and completeness.
8. **Timeline & Analytics Recording**: Writes turn trace to `ConversationTimeline` and emits events to `EventPublisher`.
