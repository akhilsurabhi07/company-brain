"""Conversation Roundtrip Exporter Service."""

import json
from typing import Dict, Any, List
from app.conversation.domain.context import ConversationSession


class ConversationExporter:
    """Exports conversation sessions to Markdown, JSON, HTML, or plain text."""

    @classmethod
    def export_to_markdown(cls, session: ConversationSession) -> str:
        lines = [f"# Conversation Export: {session.title}", f"**Tenant ID:** {session.tenant_id}", "---"]
        for turn in session.turns:
            lines.append(f"### User ({turn.timestamp.strftime('%Y-%m-%d %H:%M:%S')})")
            lines.append(turn.user_query)
            lines.append(f"\n### Assistant ({turn.persona_used} - {turn.mode_used})")
            if turn.assistant_response:
                lines.append(turn.assistant_response.text_content)
            lines.append("\n---")
        return "\n".join(lines)

    @classmethod
    def export_to_json(cls, session: ConversationSession) -> str:
        return session.model_dump_json(indent=2)
