# Module 6B — Enterprise Experience Layer (EXL) Architecture

## 1. Overview
The **Enterprise Experience Layer (EXL)** represents the complete enterprise web frontend platform for **Company Brain**. Modeled after world-class platforms like Microsoft Copilot, ChatGPT Enterprise, and Cursor, Module 6B provides a highly polished, responsive interface strictly decoupled from the core backend AI and knowledge services.

## 2. High-Level System Architecture
```text
┌────────────────────────────────────────────────────────────────────────┐
│                        Module 6B Frontend UI                           │
│  (HTML5, Vanilla CSS Design System, Decoupled JS Application)          │
│                                                                        │
│  ┌──────────────────┐  ┌──────────────────┐  ┌──────────────────────┐  │
│  │ Conversational AI│  │ Enterprise Search│  │  Knowledge Explorer  │  │
│  └────────┬─────────┘  └────────┬─────────┘  └──────────┬───────────┘  │
└───────────┼─────────────────────┼───────────────────────┼──────────────┘
            │                     │                       │
            ▼                     ▼                       ▼
┌────────────────────────────────────────────────────────────────────────┐
│                      FastAPI Routing Gateway                          │
│                    Mount Point: /m6b/                                  │
└─────────────────────────────────┬──────────────────────────────────────┘
                                  │ REST / JSON (Async HTTP)
                                  ▼
┌────────────────────────────────────────────────────────────────────────┐
│                   Module 6A Backend Services                           │
│  - Conversation Planner     - Provider Health Monitor                  │
│  - Response Lifecycle State - Prompt SHA-256 Hashing                   │
│  - Event Publisher          - Replay & Timeline Engine                 │
└────────────────────────────────────────────────────────────────────────┘
```

## 3. Key Design Principles
- **Strict Backend Decoupling**: Zero business or AI reasoning logic resides in the UI layer. All state and intelligence are consumed via clean REST endpoints.
- **Top Hero Radial Glow Aesthetic**: Dark royal purple/indigo gradient (`#8b5cf6`, `#6366f1`) fading into midnight black (`#08070d`) with translucent glassmorphism cards (`backdrop-filter: blur(16px)`).
- **Row-Level Security Transparency**: RLS tenant boundaries (`tenant_enterprise_01`) and security redaction indicators are clearly visible across all interactive views.
