"""
Knowledge Retrieval Engine FastAPI REST API Router — Module 4
============================================================
Exposes POST /api/v1/retrieval/query and POST /api/v1/retrieval/debug endpoints.
"""
from typing import Optional, Dict, Any
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from app.retrieval.retrieval_service import knowledge_retrieval_service
from app.retrieval.domain.context import KnowledgeContext

router = APIRouter(prefix="/api/v1/retrieval", tags=["Knowledge Retrieval Engine"])

class RetrievalQueryRequest(BaseModel):
    tenant_id: str
    query: str
    user_id: Optional[str] = None
    correlation_id: Optional[str] = None

@router.post("/query", response_model=KnowledgeContext)
async def execute_retrieval_query(req: RetrievalQueryRequest):
    """Executes Knowledge Retrieval Engine pipeline and returns KnowledgeContext v1."""
    try:
        context = await knowledge_retrieval_service.execute_retrieval(
            tenant_id=req.tenant_id,
            query=req.query,
            user_id=req.user_id,
            correlation_id=req.correlation_id
        )
        return context
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@router.post("/debug")
async def execute_retrieval_debug(req: RetrievalQueryRequest):
    """Debug endpoint returning raw context details and step execution traces."""
    try:
        context = await knowledge_retrieval_service.execute_retrieval(
            tenant_id=req.tenant_id,
            query=req.query,
            user_id=req.user_id,
            correlation_id=req.correlation_id
        )
        return {
            "query": req.query,
            "tenant_id": req.tenant_id,
            "correlation_id": context.metadata.get("correlation_id"),
            "execution_trace": context.execution_trace,
            "confidence_breakdown": context.confidence.model_dump(),
            "quality_metrics": context.quality.model_dump(),
            "knowledge_gaps": [g.model_dump() for g in context.knowledge_gaps],
            "raw_context": context.model_dump()
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
