"""Subsystem 3: Jinja DSL Prompt Compiler."""

import hashlib
import uuid
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field
from app.conversation.prompts.registry import PromptRegistry
from app.conversation.prompts.context_composer import ContextComposer


class CompiledPrompt(BaseModel):
    compiled_text: str
    system_prompt: str
    prompt_hash: str
    snapshot_id: str = Field(default_factory=lambda: f"snap_{uuid.uuid4().hex[:10]}")
    version: str = "v1.0.0"


class PromptCompiler:
    """Assembles System Prompt + Policy + History + Knowledge Context + Schema + Style -> Compiled Prompt."""

    @classmethod
    def compile(
        cls,
        prompt_name: str,
        user_query: str,
        knowledge_context: Any,
        persona: str = "ENGINEER",
        history_str: str = "",
        policy_str: str = "",
        style_str: str = "",
    ) -> CompiledPrompt:
        template_obj = PromptRegistry.get_template(prompt_name)
        template_str = template_obj.template_str if template_obj else "Context: {{ knowledge_context }}\n\nQuery: {{ user_query }}"
        version = template_obj.version if template_obj else "v1.0.0"

        system_prompt = (
            f"# System Prompt: Persona {persona}\n"
            f"You are Company Brain, an enterprise AI Operating System acting as a {persona}.\n\n"
            f"## Mandatory Grounding & Generation Rules:\n"
            f"1. **Context-Only Grounding**: Answer ONLY using the provided KnowledgeContext. Do not fill in missing details from external memory for company-specific queries.\n"
            f"2. **Missing Context Rule**: If the provided KnowledgeContext does not contain the answer, explicitly state: \"I couldn't find this information in your company's data.\" rather than hallucinating.\n"
            f"3. **Conflict Surfacing Rule**: If two sources in the provided KnowledgeContext contradict each other, surface the conflict explicitly (e.g. \"[Sources Disagree]: Document A specifies X, whereas Document B specifies Y\") rather than silently choosing one.\n"
            f"4. **Inline Citations**: Every claim or factual statement supported by context MUST include an inline citation tag mapping back to the supporting document, page, or chunk (e.g. `[Doc A, p. 3]` or `[hr_policy_v4.2.txt]`).\n"
            f"5. **General World Knowledge**: If the query is an explicit general knowledge question (science, history, world facts), answer thoroughly using structured markdown."
        )
        context_str = ContextComposer.compose_context_string(knowledge_context)

        # Jinja style template substitution
        rendered = template_str.replace("{{ knowledge_context }}", context_str)
        rendered = rendered.replace("{{ user_query }}", user_query)

        if history_str:
            rendered = f"{history_str}\n\n{rendered}"
        if policy_str:
            rendered = f"[Policy Enforcement: {policy_str}]\n{rendered}"
        if style_str:
            rendered = f"{rendered}\n[Style: {style_str}]"

        prompt_hash = hashlib.sha256(rendered.encode("utf-8")).hexdigest()

        return CompiledPrompt(
            compiled_text=rendered,
            system_prompt=system_prompt,
            prompt_hash=prompt_hash,
            version=version,
        )
