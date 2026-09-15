"""Provider Factory — Gemini, Azure, Ollama, vLLM, Groq, HuggingFace."""

import time
import asyncio
from typing import AsyncGenerator, Dict, Any
from app.conversation.interfaces.llm_provider import BaseLLMProvider, GenerationRequest, GenerationResponse
from app.conversation.domain.response_payload import MultimodalResponsePayload
from app.conversation.providers.openai_adapter import OpenAIProviderAdapter
from app.conversation.providers.anthropic_adapter import AnthropicProviderAdapter
from app.conversation.providers.gemini_adapter import GeminiProviderAdapter
from app.conversation.providers.groq_adapter import GroqProviderAdapter
from app.conversation.providers.huggingface_adapter import HuggingFaceProviderAdapter
from app.conversation.interfaces.exceptions import LLMProviderOfflineException


class AzureOpenAIProviderAdapter(OpenAIProviderAdapter):
    @property
    def provider_name(self) -> str:
        return "AzureOpenAI"


class OllamaProviderAdapter(BaseLLMProvider):
    """Self-hosted Ollama adapter. Not reachable unless a local Ollama server is running
    at settings.OLLAMA_HOST — this project doesn't run one, so this fails honestly rather
    than pretending to have answered."""

    @property
    def provider_name(self) -> str:
        return "Ollama"

    async def generate(self, request: GenerationRequest) -> GenerationResponse:
        import httpx
        from app.config import settings
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                await client.get(settings.OLLAMA_HOST)
        except Exception:
            raise LLMProviderOfflineException(f"Ollama not reachable at {settings.OLLAMA_HOST}.")
        raise LLMProviderOfflineException("Ollama reachable but chat completion is not implemented.")

    async def generate_stream(self, request: GenerationRequest) -> AsyncGenerator[Dict[str, Any], None]:
        await self.generate(request)
        yield {"type": "token", "content": ""}  # pragma: no cover — generate() always raises first


class VLLMProviderAdapter(BaseLLMProvider):
    """Self-hosted vLLM adapter. Not reachable unless a local vLLM server is running at
    settings.VLLM_ENDPOINT — this project doesn't run one, so this fails honestly rather
    than pretending to have answered."""

    @property
    def provider_name(self) -> str:
        return "vLLM"

    async def generate(self, request: GenerationRequest) -> GenerationResponse:
        import httpx
        from app.config import settings
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                await client.get(settings.VLLM_ENDPOINT)
        except Exception:
            raise LLMProviderOfflineException(f"vLLM not reachable at {settings.VLLM_ENDPOINT}.")
        raise LLMProviderOfflineException("vLLM reachable but chat completion is not implemented.")

    async def generate_stream(self, request: GenerationRequest) -> AsyncGenerator[Dict[str, Any], None]:
        await self.generate(request)
        yield {"type": "token", "content": ""}  # pragma: no cover — generate() always raises first




class LocalTransformersProviderAdapter(BaseLLMProvider):
    """Real, self-hosted, free open-source LLM fallback — added 2026-08-21 after this
    session repeatedly hit genuine, simultaneous quota exhaustion across every paid
    provider (OpenAI/Groq/Gemini) with Anthropic/HuggingFace never configured at all,
    leaving zero working models and a degraded "I can't answer" response as the only
    option. Qwen2.5-0.5B-Instruct (Apache 2.0, ~1GB, real instruction-following)
    runs directly in-process on CPU — same self-hosted philosophy as BGEEmbedder and
    the cross-encoder reranker already used in this project, not a new external
    dependency. Genuinely real: no canned text, no fabricated citations — same
    grounding contract as every other provider, just running locally instead of
    calling out to a paid API. Deliberately placed LAST in the cascade (see
    orchestrator.py) — real paid providers are tried first when they're actually
    available; this exists so the app has a genuine answer instead of a canned
    failure message when they're all down."""

    _model = None
    _tokenizer = None
    MODEL_ID = "Qwen/Qwen2.5-0.5B-Instruct"

    @property
    def provider_name(self) -> str:
        return "LocalOSS"

    @classmethod
    def _load(cls):
        if cls._model is None:
            import torch
            from transformers import AutoModelForCausalLM, AutoTokenizer
            cls._tokenizer = AutoTokenizer.from_pretrained(cls.MODEL_ID)
            cls._model = AutoModelForCausalLM.from_pretrained(cls.MODEL_ID, dtype=torch.float32)
            cls._model.eval()
        return cls._model, cls._tokenizer

    def _generate_sync(self, request: GenerationRequest) -> str:
        import torch
        model, tokenizer = self._load()

        messages = []
        if request.system_prompt:
            messages.append({"role": "system", "content": request.system_prompt})
        messages.append({"role": "user", "content": request.prompt})

        encoded = tokenizer.apply_chat_template(
            messages, add_generation_prompt=True, return_tensors="pt", return_dict=True
        )
        with torch.no_grad():
            output_ids = model.generate(
                **encoded,
                max_new_tokens=min(request.max_tokens, 512),
                temperature=max(request.temperature, 0.1),
                do_sample=request.temperature > 0.0,
                pad_token_id=tokenizer.eos_token_id,
            )
        new_tokens = output_ids[0][encoded["input_ids"].shape[-1]:]
        return tokenizer.decode(new_tokens, skip_special_tokens=True).strip()

    async def generate(self, request: GenerationRequest) -> GenerationResponse:
        start_time = time.time()
        # CPU-bound blocking inference — offload so it doesn't stall the event loop,
        # same pattern used for BGE embedding elsewhere in this project.
        text_out = await asyncio.to_thread(self._generate_sync, request)
        latency = round((time.time() - start_time) * 1000.0, 2)
        payload = MultimodalResponsePayload(text_content=text_out, citations=[])
        return GenerationResponse(
            payload=payload,
            model_name=self.MODEL_ID,
            provider_name=self.provider_name,
            latency_ms=latency,
            cost_usd=0.0,
        )

    async def generate_stream(self, request: GenerationRequest) -> AsyncGenerator[Dict[str, Any], None]:
        res = await self.generate(request)
        for word in res.payload.text_content.split():
            await asyncio.sleep(0.005)
            yield {"type": "token", "content": word + " "}
        yield {"type": "status", "status": "COMPLETED"}


class MockProviderAdapter(BaseLLMProvider):
    """Deterministic offline stub — no network calls, no API keys, no real model behind it.
    Exists purely so the system can be exercised locally without live LLM access (e.g. an
    explicit `preferred_provider=mock` selection). Deliberately does NOT dress itself up as
    a real grounded answer (no fabricated citations, trust scores, or synthesized content) —
    it says plainly that it's a stub, which is the honest thing for a stub to say."""

    @property
    def provider_name(self) -> str:
        return "Mock"

    async def generate(self, request: GenerationRequest) -> GenerationResponse:
        start_time = time.time()
        query = (request.raw_query or request.prompt or "").strip()
        answer_text = (
            "**[Mock provider — no real model was called.]**\n\n"
            f"This is a deterministic offline stub standing in for a response to: \"{query[:200]}\". "
            "Select a real provider (OpenAI, Groq, Gemini, Anthropic, HuggingFace) for an actual AI-generated answer."
        )
        latency = round((time.time() - start_time) * 1000.0, 2)
        payload = MultimodalResponsePayload(text_content=answer_text, citations=[])
        return GenerationResponse(
            payload=payload,
            model_name="mock",
            provider_name=self.provider_name,
            latency_ms=latency,
            cost_usd=0.0,
        )

    async def generate_stream(self, request: GenerationRequest) -> AsyncGenerator[Dict[str, Any], None]:
        res = await self.generate(request)
        for word in res.payload.text_content.split():
            await asyncio.sleep(0.01)
            yield {"type": "token", "content": word + " "}
        yield {"type": "status", "status": "COMPLETED"}


class ProviderFactory:
    """Factory creating provider adapters based on request configuration."""
    _PROVIDERS = {
        "OPENAI": OpenAIProviderAdapter,
        "AZURE": AzureOpenAIProviderAdapter,
        "ANTHROPIC": AnthropicProviderAdapter,
        "OLLAMA": OllamaProviderAdapter,
        "VLLM": VLLMProviderAdapter,
        "GEMINI": GeminiProviderAdapter,
        "GROQ": GroqProviderAdapter,
        "HUGGINGFACE": HuggingFaceProviderAdapter,
        "LOCAL": LocalTransformersProviderAdapter,
        "MOCK": MockProviderAdapter,
    }

    @classmethod
    def create_provider(cls, provider_type: str = "MOCK", **kwargs) -> BaseLLMProvider:
        key = provider_type.upper()
        if key not in cls._PROVIDERS:
            key = "MOCK"
        provider_class = cls._PROVIDERS[key]
        return provider_class(**kwargs)

    @classmethod
    def get_provider(cls, provider_type: str = "MOCK", **kwargs) -> BaseLLMProvider:
        return cls.create_provider(provider_type, **kwargs)
