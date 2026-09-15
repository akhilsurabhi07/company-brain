"""Anthropic Claude LLM Provider Adapter with Live API Integration."""

import time
import asyncio
import httpx
from typing import AsyncGenerator, Dict, Any
from app.config import settings
from app.conversation.interfaces.llm_provider import BaseLLMProvider, GenerationRequest, GenerationResponse
from app.conversation.domain.response_payload import MultimodalResponsePayload
from app.conversation.interfaces.exceptions import LLMProviderOfflineException


class AnthropicProviderAdapter(BaseLLMProvider):
    """Anthropic Claude Provider Adapter."""

    MODEL = "claude-3-5-sonnet-20241022"

    @property
    def provider_name(self) -> str:
        return "Anthropic"

    async def generate(self, request: GenerationRequest) -> GenerationResponse:
        start_time = time.time()

        if settings.ANTHROPIC_API_KEY:
            try:
                headers = {
                    "x-api-key": settings.ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                }
                data = {
                    "model": self.MODEL,
                    "max_tokens": 1024,
                    "system": request.system_prompt or f"You are Company Brain, an enterprise AI assistant acting as {request.persona}. Answer clearly and concisely.",
                    "messages": [{"role": "user", "content": request.prompt}],
                }
                async with httpx.AsyncClient(timeout=45.0) as client:
                    resp = await client.post("https://api.anthropic.com/v1/messages", headers=headers, json=data)
                    if resp.status_code == 200:
                        res_json = resp.json()
                        content_blocks = res_json.get("content", [])
                        answer_text = "".join(b.get("text", "") for b in content_blocks if b.get("type") == "text")
                        usage = res_json.get("usage", {})
                        latency = round((time.time() - start_time) * 1000.0, 2)

                        payload = MultimodalResponsePayload(
                            text_content=answer_text,
                            citations=[{"citation_id": "1", "source": "Anthropic Claude", "trust_score": 0.98}],
                            suggested_followups=["Ask a follow-up", "Request detailed breakdown"],
                        )
                        return GenerationResponse(
                            payload=payload,
                            model_name=self.MODEL,
                            provider_name=self.provider_name,
                            prompt_tokens=usage.get("input_tokens", 140),
                            completion_tokens=usage.get("output_tokens", 75),
                            total_tokens=usage.get("input_tokens", 140) + usage.get("output_tokens", 75),
                            latency_ms=latency,
                            cost_usd=0.0035,
                        )
                    err_text = resp.text[:300]
                    if resp.status_code in (401, 403):
                        raise LLMProviderOfflineException(f"Anthropic API {resp.status_code}: {err_text}")
                    raise RuntimeError(f"Anthropic API returned {resp.status_code}: {err_text}")
            except LLMProviderOfflineException:
                raise
            except Exception as e:
                raise RuntimeError(f"Anthropic call failed: {e}") from e

        # No key configured — fail fast rather than pretending to be Claude.
        raise LLMProviderOfflineException("No ANTHROPIC_API_KEY configured.")

    async def generate_stream(self, request: GenerationRequest) -> AsyncGenerator[Dict[str, Any], None]:
        result = await self.generate(request)
        for word in result.payload.text_content.split():
            await asyncio.sleep(0.01)
            yield {"type": "token", "content": word + " "}
        yield {"type": "status", "status": "COMPLETED"}
