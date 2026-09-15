# Module 6A — Grounding Guard & Citation Validation

## Factual Grounding Verification
`GroundingGuard` evaluates whether all generated claims in assistant responses exist within the supplied `KnowledgeContext v1`. Unsubstantiated claims trigger a `GroundingRejected` event and fallback grounding handling.

## Sentence-Level Citation Mapping
`CitationValidator` maps response sentences directly to evidence citations (`[1]`, `[2]`). Citations lacking underlying context verification are rejected.

## Explanation Engine
When users query "Why?", the `ExplanationEngine` synthesizes:
- Reasoning summary
- Evidence nodes & chunks
- Grounding confidence score
- Citation references
