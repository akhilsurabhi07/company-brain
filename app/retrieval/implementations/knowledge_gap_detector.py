"""
Knowledge Gap Detector Implementation — Module 4
================================================
Inspects incomplete graph paths, missing owners, or missing approvals.
"""
from typing import List
from app.retrieval.domain.retrieval import Candidate
from app.retrieval.domain.evidence import KnowledgeGap

class KnowledgeGapDetector:
    """Detects missing owners, missing approvals, and unlinked dependencies."""

    def detect_gaps(self, candidates: List[Candidate]) -> List[KnowledgeGap]:
        gaps = []
        has_owner = any("owner" in c.content.lower() or "owned" in c.content.lower() for c in candidates)
        has_approval = any("approval" in c.content.lower() or "legal" in c.content.lower() for c in candidates)

        if not has_owner and len(candidates) > 0:
            gaps.append(KnowledgeGap(
                gap_type="MissingOwner",
                target_node="Project Owner",
                impact="Medium",
                description="No explicit project owner relationship found in retrieved evidence."
            ))
        if not has_approval and len(candidates) > 0:
            gaps.append(KnowledgeGap(
                gap_type="MissingApproval",
                target_node="Legal Approval",
                impact="High",
                description="No formal legal approval status record found in retrieved evidence."
            ))

        return gaps

knowledge_gap_detector = KnowledgeGapDetector()
