"""Subsystem 5: KnowledgeContext Composer."""

from typing import Dict, Any


class ContextComposer:
    """Consumes KnowledgeContext v1 without modifying its contract and formats it for prompt inclusion."""

    @classmethod
    def compose_context_string(cls, knowledge_context: Any) -> str:
        if isinstance(knowledge_context, str):
            return knowledge_context
        if isinstance(knowledge_context, dict):
            parts = []
            if "query" in knowledge_context:
                parts.append(f"Query Context: {knowledge_context['query']}")
            if "documents" in knowledge_context:
                parts.append("Retrieved Documents:")
                for idx, doc in enumerate(knowledge_context["documents"]):
                    parts.append(f"[{idx+1}] {doc.get('title', 'Doc')}: {doc.get('content', '')}")
            return "\n".join(parts)
        return str(knowledge_context)
