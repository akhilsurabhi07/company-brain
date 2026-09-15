"""Groq LLM Provider Adapter — Free tier, blazing fast inference.

Groq runs open-weight models at very high throughput for free (rate-limited).
API is OpenAI-compatible. Get a free key at https://console.groq.com
MODEL below should track whatever's current in Groq's catalog — models get
deprecated/removed there periodically; check https://console.groq.com/docs/models
if generation starts failing with a "model decommissioned" error.
"""

import time
import asyncio
import httpx
from typing import AsyncGenerator, Dict, Any
from app.config import settings
from app.conversation.interfaces.llm_provider import BaseLLMProvider, GenerationRequest, GenerationResponse
from app.conversation.domain.response_payload import MultimodalResponsePayload
from app.conversation.interfaces.exceptions import LLMProviderOfflineException


class GroqProviderAdapter(BaseLLMProvider):
    """Groq Cloud free-tier adapter."""

    GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
    MODEL = "openai/gpt-oss-120b"

    @property
    def provider_name(self) -> str:
        return "Groq"

    async def generate(self, request: GenerationRequest) -> GenerationResponse:
        start_time = time.time()

        if settings.GROQ_API_KEY:
            for attempt in range(3):
                try:
                    system_msg = request.system_prompt or (
                        f"You are Company Brain, an advanced AI assistant acting as {request.persona}. "
                        f"You have comprehensive knowledge about science, technology, history, programming, "
                        f"mathematics, geography, culture, business, health, and all general world topics. "
                        f"When the user asks about ANY topic, provide a detailed, thorough, well-structured answer. "
                        f"Use markdown formatting with headers (##), bullet points, bold text, and code blocks. "
                        f"For company-specific questions, use enterprise knowledge. "
                        f"For general questions, draw from your broad training knowledge. "
                        f"Always give comprehensive answers — never give short or snippet-like responses. "
                        f"Pay close attention to conversation history to understand follow-up questions."
                    )

                    # Build messages list with conversation history
                    messages = [{"role": "system", "content": system_msg}]

                    # Parse history from the prompt if it contains conversation context
                    prompt_text = request.prompt
                    if "Previous Conversation Context:" in prompt_text and "Current User Query:" in prompt_text:
                        parts = prompt_text.split("Current User Query:", 1)
                        context_block = parts[0].replace("Previous Conversation Context:", "").strip()
                        current_query = parts[1].strip()

                        # Parse each history turn
                        for line in context_block.split("\n"):
                            line = line.strip()
                            if line.startswith("User:"):
                                messages.append({"role": "user", "content": line[5:].strip()})
                            elif line.startswith("Assistant:"):
                                messages.append({"role": "assistant", "content": line[10:].strip()})

                        messages.append({"role": "user", "content": current_query})
                    else:
                        messages.append({"role": "user", "content": prompt_text})

                    headers = {
                        "Content-Type": "application/json",
                        "Authorization": f"Bearer {settings.GROQ_API_KEY}",
                    }
                    payload = {
                        "model": self.MODEL,
                        "messages": messages,
                        "temperature": 0.7,
                        "max_tokens": 4096,
                    }

                    async with httpx.AsyncClient(timeout=25.0) as client:
                        resp = await client.post(self.GROQ_API_URL, headers=headers, json=payload)

                        if resp.status_code == 200:
                            data = resp.json()
                            answer = data["choices"][0]["message"]["content"]
                            usage = data.get("usage", {})
                            latency = round((time.time() - start_time) * 1000.0, 2)

                            response_payload = MultimodalResponsePayload(
                                text_content=answer,
                                citations=[{"citation_id": "1", "source": f"Groq ({self.MODEL})", "trust_score": 0.97}],
                                suggested_followups=["Ask a follow-up", "Go deeper"],
                            )
                            return GenerationResponse(
                                payload=response_payload,
                                model_name=self.MODEL,
                                provider_name=self.provider_name,
                                prompt_tokens=usage.get("prompt_tokens", 0),
                                completion_tokens=usage.get("completion_tokens", 0),
                                total_tokens=usage.get("total_tokens", 0),
                                latency_ms=latency,
                                cost_usd=0.0,  # Free tier
                            )

                        elif resp.status_code == 429:
                            wait = min(2 ** attempt, 5)
                            print(f"[GroqAdapter] Rate limited (429). Waiting {wait}s (attempt {attempt+1}/3)...")
                            await asyncio.sleep(wait)
                            continue
                        elif resp.status_code in [401, 403, 404]:
                            err = resp.json().get("error", {}).get("message", resp.text[:200])
                            print(f"[GroqAdapter] Critical Error {resp.status_code}: {err}")
                            raise LLMProviderOfflineException(f"Groq API {resp.status_code}: {err}")
                        else:
                            err = resp.json().get("error", {}).get("message", resp.text[:200])
                            print(f"[GroqAdapter] Error {resp.status_code}: {err}")
                            break

                except LLMProviderOfflineException:
                    # Not worth retrying (bad key / forbidden) — stop immediately and let
                    # the caller fail over to another provider.
                    raise
                except Exception as e:
                    print(f"[GroqAdapter] Exception on attempt {attempt+1}: {e}")
                    await asyncio.sleep(1)

        # All retries exhausted (or no key configured) — raise so RuntimeOrchestrator can
        # fail over to another real provider, instead of returning a fake "successful"
        # response whose text just happens to say it failed.
        if not settings.GROQ_API_KEY:
            raise LLMProviderOfflineException("No GROQ_API_KEY configured.")
        raise RuntimeError("Groq call failed after 3 attempts.")

    async def generate_stream(self, request: GenerationRequest) -> AsyncGenerator[Dict[str, Any], None]:
        result = await self.generate(request)
        for word in result.payload.text_content.split():
            await asyncio.sleep(0.01)
            yield {"type": "token", "content": word + " "}
        yield {"type": "status", "status": "COMPLETED"}
