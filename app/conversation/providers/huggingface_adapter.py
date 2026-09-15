"""HuggingFace Inference API Provider Adapter — Free tier.

Uses HF's serverless Inference API with Mistral or Llama models.
Get a free token at https://huggingface.co/settings/tokens
"""

import time
import asyncio
import httpx
from typing import AsyncGenerator, Dict, Any
from app.config import settings
from app.conversation.interfaces.llm_provider import BaseLLMProvider, GenerationRequest, GenerationResponse
from app.conversation.domain.response_payload import MultimodalResponsePayload
from app.conversation.interfaces.exceptions import LLMProviderOfflineException


class HuggingFaceProviderAdapter(BaseLLMProvider):
    """HuggingFace Inference API — Free tier adapter."""

    # Use the free serverless inference endpoint
    HF_API_URL = "https://router.huggingface.co/novita/v3/openai/chat/completions"
    MODEL = "deepseek-ai/DeepSeek-V3-0324"

    @property
    def provider_name(self) -> str:
        return "HuggingFace"

    async def generate(self, request: GenerationRequest) -> GenerationResponse:
        start_time = time.time()

        if settings.HUGGINGFACE_API_KEY:
            for attempt in range(3):
                try:
                    system_msg = request.system_prompt or (
                        f"You are Company Brain, an advanced enterprise AI assistant acting as {request.persona}. "
                        f"You have comprehensive knowledge about science, technology, history, programming, mathematics, "
                        f"geography, culture, business, health, and all general world topics. "
                        f"When the user asks about any topic, provide a detailed, thorough, and well-structured answer. "
                        f"Use bullet points, headers, and examples where appropriate. "
                        f"For company-specific questions, use your enterprise knowledge base. "
                        f"For general questions, draw from your broad training knowledge. "
                        f"Always give comprehensive answers — never give one-line or snippet-like responses. "
                        f"Pay close attention to the conversation history to understand context and follow-up questions. "
                        f"If the user says 'it', 'that', 'this', 'more about it', etc., refer back to the previous topic being discussed."
                    )
                    headers = {
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {settings.HUGGINGFACE_API_KEY}",
                    }

                    # Build proper multi-turn messages array with full conversation history
                    messages = [{"role": "system", "content": system_msg}]

                    # Add conversation history as proper message turns
                    if request.history and len(request.history) > 0:
                        for item in request.history[-10:]:  # Last 10 turns for context
                            role = item.get("role", "user") if isinstance(item, dict) else "user"
                            content = item.get("content", "") if isinstance(item, dict) else str(item)
                            if content and role in ("user", "assistant"):
                                messages.append({"role": role, "content": content})

                    # Add the current user query
                    messages.append({"role": "user", "content": request.raw_query or request.prompt})

                    payload = {
                        "model": self.MODEL,
                        "messages": messages,
                        "temperature": 0.7,
                        "max_tokens": 2048,
                    }

                    async with httpx.AsyncClient(timeout=60.0) as client:
                        resp = await client.post(self.HF_API_URL, headers=headers, json=payload)

                        if resp.status_code == 200:
                            data = resp.json()
                            answer = data["choices"][0]["message"]["content"]
                            usage = data.get("usage", {})
                            latency = round((time.time() - start_time) * 1000.0, 2)

                            response_payload = MultimodalResponsePayload(
                                text_content=answer,
                                citations=[{"citation_id": "1", "source": f"HuggingFace ({self.MODEL.split('/')[-1]})", "trust_score": 0.95}],
                                suggested_followups=["Ask a follow-up", "Go deeper"],
                            )
                            return GenerationResponse(
                                payload=response_payload,
                                model_name=self.MODEL.split("/")[-1],
                                provider_name=self.provider_name,
                                prompt_tokens=usage.get("prompt_tokens", 0),
                                completion_tokens=usage.get("completion_tokens", 0),
                                total_tokens=usage.get("total_tokens", 0),
                                latency_ms=latency,
                                cost_usd=0.0,
                            )

                        elif resp.status_code == 429:
                            wait = min(2 ** attempt, 8)
                            print(f"[HuggingFaceAdapter] Rate limited. Waiting {wait}s (attempt {attempt+1}/3)...")
                            await asyncio.sleep(wait)
                            continue
                        elif resp.status_code == 503:
                            # Model loading
                            print(f"[HuggingFaceAdapter] Model loading, waiting 10s...")
                            await asyncio.sleep(10)
                            continue
                        else:
                            err_text = resp.text[:300]
                            print(f"[HuggingFaceAdapter] Error {resp.status_code}: {err_text}")
                            break

                except Exception as e:
                    print(f"[HuggingFaceAdapter] Exception on attempt {attempt+1}: {e}")
                    await asyncio.sleep(2)

        # All retries exhausted (or no key configured) — raise so RuntimeOrchestrator can
        # fail over to another real provider, instead of returning a fake "successful"
        # response whose text just happens to say it failed.
        if not settings.HUGGINGFACE_API_KEY:
            raise LLMProviderOfflineException("No HUGGINGFACE_API_KEY configured.")
        raise RuntimeError("HuggingFace call failed after 3 attempts.")

    async def generate_stream(self, request: GenerationRequest) -> AsyncGenerator[Dict[str, Any], None]:
        result = await self.generate(request)
        for word in result.payload.text_content.split():
            await asyncio.sleep(0.01)
            yield {"type": "token", "content": word + " "}
        yield {"type": "status", "status": "COMPLETED"}
