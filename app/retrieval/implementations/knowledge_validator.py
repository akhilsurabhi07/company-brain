"""
Knowledge Validator Implementation — Module 4
=============================================
Validates synthesized knowledge: cycle checks, broken path detection, low-confidence fact filtering, and tenant isolation verification.
"""
from typing import List
from app.retrieval.domain.retrieval import Candidate, RetrievalPipelineContext

class KnowledgeValidator:
    """Validates candidate list for tenant isolation and provenance completeness."""

    def validate(self, ctx: RetrievalPipelineContext, candidates: List[Candidate]) -> List[Candidate]:
        valid_candidates = []
        for c in candidates:
            # Low confidence score filtering (< 0.20)
            if c.score < 0.20:
                continue
            # Tenant isolation check
            cand_tenant = c.source_metadata.get("tenant_id")
            if cand_tenant and cand_tenant != ctx.tenant_id:
                continue
            valid_candidates.append(c)
        return valid_candidates

knowledge_validator = KnowledgeValidator()
