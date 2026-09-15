"""
Correlation ID Context Manager — Module 5 EKAP
==============================================
"""
import uuid
import contextvars

correlation_id_var = contextvars.ContextVar("correlation_id", default=None)

def get_correlation_id() -> str:
    corr_id = correlation_id_var.get()
    if not corr_id:
        corr_id = f"req_{uuid.uuid4().hex[:8]}"
        correlation_id_var.set(corr_id)
    return corr_id

def set_correlation_id(corr_id: str) -> None:
    correlation_id_var.set(corr_id)
