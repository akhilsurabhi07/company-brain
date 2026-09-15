"""Subsystem 4: Versioned Enterprise Prompt Registry."""

from typing import Dict, Optional
from pydantic import BaseModel, Field
from app.conversation.domain.modes import ConversationMode


class PromptTemplate(BaseModel):
    name: str
    version: str
    mode: ConversationMode
    template_str: str
    description: str


class PromptRegistry:
    """Stores and versions 10 enterprise prompt templates."""

    _TEMPLATES: Dict[str, PromptTemplate] = {
        "ARCHITECTURE_REVIEW": PromptTemplate(
            name="ARCHITECTURE_REVIEW",
            version="v2.1.0",
            mode=ConversationMode.ARCHITECTURE_REVIEW,
            template_str="Perform a deep architecture review using provided context. Evaluate scalability, bottlenecks, and security. System: {{ system_prompt }} Context: {{ knowledge_context }} Query: {{ user_query }}",
            description="Enterprise Architecture Review Prompt",
        ),
        "INCIDENT_REPORT": PromptTemplate(
            name="INCIDENT_REPORT",
            version="v1.4.0",
            mode=ConversationMode.EXPLAIN,
            template_str="Analyze the root cause and impact of the reported incident. System: {{ system_prompt }} Context: {{ knowledge_context }} Query: {{ user_query }}",
            description="Incident Root Cause Report Prompt",
        ),
        "EXECUTIVE_SUMMARY": PromptTemplate(
            name="EXECUTIVE_SUMMARY",
            version="v3.0.0",
            mode=ConversationMode.EXECUTIVE_BRIEF,
            template_str="Provide a high-level executive summary tailored for leadership. System: {{ system_prompt }} Context: {{ knowledge_context }} Query: {{ user_query }}",
            description="Executive Summary Briefing Prompt",
        ),
        "RISK_ANALYSIS": PromptTemplate(
            name="RISK_ANALYSIS",
            version="v2.0.0",
            mode=ConversationMode.RISK_REVIEW,
            template_str="Conduct a thorough risk and dependency analysis. System: {{ system_prompt }} Context: {{ knowledge_context }} Query: {{ user_query }}",
            description="Enterprise Risk Assessment Prompt",
        ),
        "COMPLIANCE": PromptTemplate(
            name="COMPLIANCE",
            version="v1.8.0",
            mode=ConversationMode.COMPLIANCE_AUDIT,
            template_str="Audit regulatory and export compliance (e.g. EAR99, SOC2). System: {{ system_prompt }} Context: {{ knowledge_context }} Query: {{ user_query }}",
            description="Compliance Audit Prompt",
        ),
        "CODE_REVIEW": PromptTemplate(
            name="CODE_REVIEW",
            version="v2.5.0",
            mode=ConversationMode.REVIEW,
            template_str="Review code snippets for performance, clean code, and edge cases. System: {{ system_prompt }} Context: {{ knowledge_context }} Query: {{ user_query }}",
            description="Code Review & Optimization Prompt",
        ),
        "TEACHING": PromptTemplate(
            name="TEACHING",
            version="v1.1.0",
            mode=ConversationMode.EXPLAIN,
            template_str="Explain complex technical concepts in simple terms with examples. System: {{ system_prompt }} Context: {{ knowledge_context }} Query: {{ user_query }}",
            description="Educational Deep Dive Prompt",
        ),
        "RESEARCH": PromptTemplate(
            name="RESEARCH",
            version="v2.2.0",
            mode=ConversationMode.TECHNICAL_DEEP_DIVE,
            template_str="Synthesize research papers, docs, and technical specifications. System: {{ system_prompt }} Context: {{ knowledge_context }} Query: {{ user_query }}",
            description="Technical Research Synthesis Prompt",
        ),
        "MEETING_SUMMARY": PromptTemplate(
            name="MEETING_SUMMARY",
            version="v1.3.0",
            mode=ConversationMode.SUMMARIZED,
            template_str="Extract key decisions, action items, and owners from meeting notes. System: {{ system_prompt }} Context: {{ knowledge_context }} Query: {{ user_query }}",
            description="Meeting Notes & Decisions Prompt",
        ),
        "ROOT_CAUSE_ANALYSIS": PromptTemplate(
            name="ROOT_CAUSE_ANALYSIS",
            version="v1.9.0",
            mode=ConversationMode.EXPLAIN,
            template_str="Perform 5-Whys root cause analysis with evidence citations. System: {{ system_prompt }} Context: {{ knowledge_context }} Query: {{ user_query }}",
            description="5-Whys Root Cause Analysis Prompt",
        ),
    }

    @classmethod
    def get_template(cls, name: str) -> Optional[PromptTemplate]:
        return cls._TEMPLATES.get(name.upper())

    @classmethod
    def list_templates(cls) -> Dict[str, str]:
        return {k: v.version for k, v in cls._TEMPLATES.items()}
