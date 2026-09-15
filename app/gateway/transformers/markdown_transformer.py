"""
Markdown Response Transformer — Module 5 EKAP
=============================================
Transforms KnowledgeContext v1 into Markdown for Chat UIs.
"""
from typing import Dict, Any
from app.retrieval.domain.context import KnowledgeContext

class MarkdownTransformer:
    """Transforms KnowledgeContext v1 into GitHub-style Markdown text."""

    def transform(self, context: KnowledgeContext) -> str:
        md = [f"# Knowledge Context for Query: *\"{context.query}\"*\n"]
        md.append(f"**Intent Recognized**: `{context.intent}` (Confidence: {context.confidence.overall * 100:.1f}%)\n")
        
        if context.retrieved_chunks:
            md.append("### 📚 Top Evidence Snippets")
            for idx, chunk in enumerate(context.retrieved_chunks[:5]):
                score = chunk.get("score", 0.8)
                md.append(f"{idx+1}. **[Score: {score:.2f}]** {chunk.get('content')}")
            md.append("")

        if context.derived_facts:
            md.append("### 💡 Derived Facts")
            for fact in context.derived_facts:
                md.append(f"- {fact.get('content')}")
            md.append("")

        if context.citations:
            md.append("### 📌 Source Citations")
            for cit in context.citations:
                md.append(f"- **[{cit.citation_id}]** {cit.title} (Source: {cit.source_app})")
            md.append("")

        return "\n".join(md)

markdown_transformer = MarkdownTransformer()
