"""
Knowledge Lifecycle Manager — Module 3
======================================
Manages explicit state machine transitions for entities and facts:
  [Candidate] -> [Validated] -> [Published] -> [Deprecated] -> [Archived]
"""
class KnowledgeLifecycleManager:
    """Enforces valid state machine transitions."""

    VALID_TRANSITIONS = {
        "Candidate": ["Validated", "Rejected", "Pending Verification"],
        "Validated": ["Published", "Pending Verification"],
        "Pending Verification": ["Published", "Rejected"],
        "Published": ["Deprecated", "Deleted"],
        "Deprecated": ["Archived", "Published"],
    }

    def transition_state(self, current_state: str, target_state: str) -> str:
        """Transitions state if allowed, else raises ValueError."""
        allowed = self.VALID_TRANSITIONS.get(current_state, [])
        if target_state not in allowed:
            raise ValueError(f"Invalid state transition from '{current_state}' to '{target_state}'. Allowed: {allowed}")
        return target_state

knowledge_lifecycle_manager = KnowledgeLifecycleManager()
