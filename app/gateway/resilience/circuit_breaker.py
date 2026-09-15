"""
Circuit Breaker Pattern Subsystem — Module 5 EKAP
================================================
Protects downstream services against cascading failures.
"""
import time
import asyncio
from typing import Callable, Any

class CircuitBreakerOpenException(Exception):
    pass

class CircuitBreaker:
    def __init__(self, failure_threshold: int = 5, recovery_timeout_seconds: int = 10):
        self.failure_threshold = failure_threshold
        self.recovery_timeout_seconds = recovery_timeout_seconds
        self.failure_count = 0
        self.state = "CLOSED"  # CLOSED, OPEN, HALF_OPEN
        self.last_state_change = time.time()

    async def call(self, func: Callable, *args, **kwargs) -> Any:
        now = time.time()
        if self.state == "OPEN":
            if now - self.last_state_change > self.recovery_timeout_seconds:
                self.state = "HALF_OPEN"
                self.last_state_change = now
            else:
                raise CircuitBreakerOpenException("Circuit Breaker is OPEN. Downstream call blocked.")

        try:
            res = await func(*args, **kwargs)
            if self.state == "HALF_OPEN":
                self.state = "CLOSED"
                self.failure_count = 0
                self.last_state_change = now
            return res
        except Exception as e:
            self.failure_count += 1
            if self.failure_count >= self.failure_threshold:
                self.state = "OPEN"
                self.last_state_change = now
            raise e
