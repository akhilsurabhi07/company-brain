"""
Unified Authorization Policy Engine (RBAC + ABAC) — Module 5 EKAP
==================================================================
Enforces Role-Based Access Control (RBAC) and Attribute-Based Access Control (ABAC).
"""
from typing import List, Dict, Any
from app.gateway.domain.auth import UserIdentity
from app.gateway.common.exceptions import AuthorizationException
from app.retrieval.domain.context import KnowledgeContext

class PolicyEngine:
    """Enforces fine-grained entitlement rules on queries and response items."""

    def authorize_request(self, identity: UserIdentity, query: str, requested_confidentiality: str = "Internal") -> None:
        q_lower = query.lower()
        
        # Rule 1: Restricted Salary/Payroll ABAC check
        if any(term in q_lower for term in ["salary", "payroll", "compensation", "bonus"]):
            if "Admin" not in identity.roles and "HR_Lead" not in identity.roles:
                raise AuthorizationException("Access Denied: Role 'Employee' is not authorized to query payroll or compensation data.")

        # Rule 2: Confidentiality Clearance ABAC check
        if requested_confidentiality == "Restricted" and identity.clearance_level not in ["Restricted", "TopSecret"]:
            raise AuthorizationException("Access Denied: Insufficient security clearance level.")

    def filter_context_for_user(self, identity: UserIdentity, context: KnowledgeContext) -> KnowledgeContext:
        """Filters retrieved chunks and facts according to user roles (RBAC/ABAC)."""
        # If user is Admin or HR_Lead, return full context
        if "Admin" in identity.roles or "HR_Lead" in identity.roles:
            return context

        # Otherwise filter out sensitive snippets containing salary or payroll numbers
        filtered_chunks = []
        for chunk in context.retrieved_chunks:
            content = chunk.get("content", "").lower()
            if "salary" in content or "compensation" in content:
                continue  # Filter out
            filtered_chunks.append(chunk)

        context.retrieved_chunks = filtered_chunks
        return context

policy_engine = PolicyEngine()
