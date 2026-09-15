"""
RFC 7807 Problem Details Error Responses — Module 5 EKAP
=========================================================
Standardized error formatting according to RFC 7807.
"""
from typing import Dict, Any, Optional
from pydantic import BaseModel, Field
from fastapi.responses import JSONResponse
from app.gateway.common.exceptions import GatewayException

class ProblemDetails(BaseModel):
    type: str = "about:blank"
    title: str
    status: int
    detail: str
    code: str
    instance: str
    trace_id: str
    timestamp: str
    details: Dict[str, Any] = Field(default_factory=dict)

def create_problem_response(exc: GatewayException, request_path: str, correlation_id: str, timestamp_iso: str) -> JSONResponse:
    problem = ProblemDetails(
        title=exc.code.replace("_", " ").title(),
        status=exc.status_code,
        detail=exc.message,
        code=exc.code,
        instance=request_path,
        trace_id=correlation_id,
        timestamp=timestamp_iso,
        details=exc.details
    )
    return JSONResponse(
        status_code=exc.status_code,
        content=problem.model_dump()
    )
