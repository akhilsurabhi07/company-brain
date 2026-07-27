"""
Multi-Signal Enterprise Trust Engine — Module 3
===============================================
Calculates multi-signal Trust Score incorporating:
  - Source Authority Weight (HR Policy = 1.0, Contract = 0.95, PR = 0.85, Meeting = 0.65, Slack = 0.40)
  - Evidence Count Corroboration
  - Recency Decay
  - User Feedback Signals
  - Conflict Penalty
"""
import math
from typing import Dict, Any

class TrustEngine:
    """Calculates composite enterprise trust scores."""

    def calculate_trust_score(
        self,
        source_authority: float,
        evidence_count: int,
        recency_days: float,
        user_feedback_score: float = 1.0,
        has_active_conflict: bool = False
    ) -> float:
        """
        Calculates composite Trust Score between 0.00 and 1.00.
        """
        authority_weight = 0.25 * source_authority
        evidence_weight = 0.20 * min(1.0, math.log2(evidence_count + 1) / 3.0)
        recency_weight = 0.15 * max(0.2, math.exp(-0.005 * recency_days))
        feedback_weight = 0.20 * user_feedback_score
        conflict_penalty = 0.20 if has_active_conflict else 0.0

        total = authority_weight + evidence_weight + recency_weight + feedback_weight - conflict_penalty
        return max(0.0, min(1.0, round(total, 4)))

trust_engine = TrustEngine()
