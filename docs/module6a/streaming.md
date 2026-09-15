# Module 6A — SSE Real-Time Streaming Engine

## Server-Sent Events (SSE) Protocol
Module 6A exposes `/api/v1/chat/stream` using standard Server-Sent Events (`text/event-stream`).

## Event Packet Types
- `token`: Partial token generation packet (`{"token": "..."}`).
- `status`: Lifecycle state updates (`{"status": "VALIDATING_GROUNDING"}`).
- `citation`: Incremental citation packet (`{"citation": "[1]"}`).
- `done`: Final completion packet (`{"done": true}`).
