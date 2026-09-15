# Module 6A — Deployment Topology

## Stateless Microservice Container
Module 6A is packaged as an independently deployable container (`company-brain-ecip`).

## Environment Variables
- `REDIS_CACHE_URL`: Connection string for conversation cache.
- `DATABASE_URL`: PostgreSQL connection pool for session persistence.
- `OPENAI_API_KEY`: API key for OpenAI provider.
- `ANTHROPIC_API_KEY`: API key for Anthropic provider.
- `GEMINI_API_KEY`: API key for Google Gemini provider.
