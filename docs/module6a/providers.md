# Module 6A — Provider Layer & Capability Registry

## Provider Adapters
Supported enterprise LLM providers:
1. **OpenAI**: GPT-4o, GPT-4-turbo
2. **Anthropic**: Claude 3.5 Sonnet, Claude 3 Opus
3. **Gemini**: Gemini 1.5 Pro, Gemini 1.5 Flash
4. **Azure OpenAI**: Enterprise isolated deployments
5. **Ollama**: Local open-weights execution (Llama 3, Mistral)
6. **vLLM**: High-throughput self-hosted GPU inference

## Capability Registry
Each provider records capability vectors:
- Context Window Size (e.g. 128k, 200k, 1M)
- JSON mode support
- Streaming capability
- Cost per 1k input/output tokens
- Average latency
- Multimodal / Vision support
