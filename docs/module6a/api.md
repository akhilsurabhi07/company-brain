# Module 6A — REST API Specification

Module 6A exposes clean backend REST endpoints under `/api/v1/chat`:

1. `POST /api/v1/chat`: Complete grounded conversational turn execution.
2. `POST /api/v1/chat/stream`: Server-Sent Events (SSE) streaming turn execution.
3. `POST /api/v1/chat/explain`: Explanation engine summary generation for reasoning queries.
4. `POST /api/v1/chat/session`: Create a new conversation session.
5. `DELETE /api/v1/chat/session/{id}`: Archive an active conversation session.

*(Note: Presentation and file export formatting are handled by Module 6B).*
