"""Session Lifecycle State Machine — Subsystem 1."""

from enum import Enum


class SessionState(str, Enum):
    CREATED = "CREATED"
    ACTIVE = "ACTIVE"
    SUMMARIZED = "SUMMARIZED"
    ARCHIVED = "ARCHIVED"
    EXPIRED = "EXPIRED"


class StateTransitionError(Exception):
    """Raised when invalid state machine transition is attempted."""
    pass


class SessionStateMachine:
    """Enforces state transitions: CREATED -> ACTIVE -> SUMMARIZED/ARCHIVED -> EXPIRED."""

    VALID_TRANSITIONS = {
        SessionState.CREATED: {SessionState.ACTIVE, SessionState.EXPIRED},
        SessionState.ACTIVE: {SessionState.SUMMARIZED, SessionState.ARCHIVED, SessionState.EXPIRED},
        SessionState.SUMMARIZED: {SessionState.ACTIVE, SessionState.ARCHIVED, SessionState.EXPIRED},
        SessionState.ARCHIVED: {SessionState.ACTIVE, SessionState.EXPIRED},
        SessionState.EXPIRED: set(),
    }

    @classmethod
    def transition(cls, current: SessionState, target: SessionState) -> SessionState:
        allowed = cls.VALID_TRANSITIONS.get(current, set())
        if target not in allowed:
            raise StateTransitionError(f"Invalid state transition from {current} to {target}. Allowed: {allowed}")
        return target
