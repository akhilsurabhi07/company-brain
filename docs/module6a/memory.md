# Module 6A — Memory Management & Session Lifecycle

## Session Lifecycle States
- `CREATED`: Session initiated.
- `ACTIVE`: Active multi-turn turn exchange.
- `SUMMARIZED`: Context budget limit reached; history compressed.
- `ARCHIVED`: Archived by user or system.
- `EXPIRED`: Session expired due to inactivity.

## Sliding-Window Context Budget
Memory management maintains a strict sliding-window token budget (default 8,192 tokens for history). Older turns are automatically summarized to keep prompt compilation fast and cost-effective.
