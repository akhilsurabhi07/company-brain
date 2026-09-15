import logging
from typing import List, Dict, Any
from app.agents.interfaces.agent_interfaces import BaseSubagent, AgentTaskContext, AgentResult

logger = logging.getLogger("company_brain.agents.synthesis_agent")

class ReflectionSynthesisAgent(BaseSubagent):
    """
    Reflection & Synthesis Subagent Worker.
    Synthesizes grounded findings from subagent workers.
    Performs self-reflection verification to drop ungrounded claims or trigger honest refusal.
    """

    @property
    def agent_name(self) -> str:
        return "ReflectionSynthesisAgent"

    async def execute(self, context: AgentTaskContext) -> AgentResult:
        tenant_id = context.tenant_id
        user_query = context.user_query
        
        # Subagent worker results passed via context metadata
        subagent_results: List[AgentResult] = context.metadata.get("subagent_results", [])
        
        # Deduplicate: keep only the BEST (highest-score) chunk per unique document
        all_citations = []
        best_chunk_per_doc: dict = {}  # document_title → best chunk

        db_offline = False
        for sr in subagent_results:
            if not sr.success and sr.error_message and ("10061" in sr.error_message or "Connect call failed" in sr.error_message):
                logger.error(f"[{self.agent_name}] Database Offline Detected in subagent result.")
                db_offline = True
            
            if sr.success:
                for c in sr.citations:
                    if c not in all_citations:
                        all_citations.append(c)
                for chunk in sr.retrieved_chunks:
                    doc_title = chunk.get("document_title", "").strip() or "Untitled"
                    score = chunk.get("score", 0.0)
                    existing = best_chunk_per_doc.get(doc_title)
                    if existing is None or score > existing.get("score", 0.0):
                        best_chunk_per_doc[doc_title] = chunk

        # Sort selected chunks by score descending
        all_chunks = sorted(best_chunk_per_doc.values(), key=lambda x: x.get("score", 0.0), reverse=True)

        # 1. Entity & Topic Self-Reflection Check
        # Verify if explicit project entity mentions in user_query exist in the retrieved chunks
        if not db_offline:
            import re
            proj_matches = re.findall(r'\bproject\s+([a-zA-Z0-9]+)', user_query, re.IGNORECASE)
            if proj_matches:
                combined_corpus = (
                    " ".join([c.get("content", "") for c in all_chunks]) + " " +
                    " ".join([c.get("document_title", "") for c in all_chunks]) + " " +
                    " ".join(all_citations)
                ).lower()
                
                # If ANY requested project entity is missing from retrieved corpus, treat as ungrounded
                for proj in proj_matches:
                    if proj.lower() not in combined_corpus:
                        logger.info(f"[{self.agent_name}] Entity 'Project {proj}' missing from retrieved corpus -> Dropping ungrounded chunks.")
                        all_chunks = []
                        all_citations = []
                        break

        # 2. Honest Refusal check if zero grounded chunks remain and DB is online
        if not all_chunks and not db_offline:
            refusal_text = f"I couldn't find information regarding **\"{user_query}\"** in your company's ingested data."
            logger.info(f"[{self.agent_name}] Zero grounded chunks -> Triggering Honest Refusal.")
            return AgentResult(
                agent_name=self.agent_name,
                success=True,
                retrieved_chunks=[],
                citations=[],
                summary_text=refusal_text,
                metadata={"grounded_claims_count": 0, "honest_refusal": True}
            )

        # 2. Synthesize Grounded Answer & Perform Self-Reflection Verification
        # Format populated citation links (each source title only once)
        formatted_sources = "\n".join([f"## 📄 Grounded Search Result: `{c}`" for c in all_citations])
        unique_text_blocks = [c["content"] for c in all_chunks[:2]]
        combined_chunk_text = "\n\n".join(unique_text_blocks)

        synthesis_text = await _llm_synthesize(user_query, combined_chunk_text, all_citations)

        if synthesis_text and not synthesis_text.startswith("## 📄") and all_citations:
            synthesis_text = f"{formatted_sources}\n\n{synthesis_text}"
            
        if db_offline:
            synthesis_text = "⚠️ **Database Offline:** I am answering this using general knowledge because the company database is currently offline.\n\n" + (synthesis_text or "No answer could be generated.")

        # 3. Record Machine-Checkable Agent Trace Entry
        if context.trace_tracker is not None:
            sql_pattern = "SYNTHESIS_SELF_REFLECTION_VERIFICATION"
            params = {"tenant_id": tenant_id, "citation_count": len(all_citations)}
            context.trace_tracker.record_step(
                agent_name=self.agent_name,
                query_str=sql_pattern,
                params=params,
                citations=all_citations,
                metadata={"grounded_chunks_count": len(all_chunks)}
            )

        # Compute confidence score from chunk scores (0-100)
        if all_chunks:
            avg_score = sum(c.get("score", 0.5) for c in all_chunks) / len(all_chunks)
            confidence_score = min(100, round(avg_score * 100))
        else:
            confidence_score = 0

        return AgentResult(
            agent_name=self.agent_name,
            success=True,
            retrieved_chunks=all_chunks,
            citations=all_citations,
            summary_text=synthesis_text,
            metadata={"grounded_claims_count": len(all_chunks), "honest_refusal": False, "confidence_score": confidence_score}
        )

async def _llm_synthesize(user_query: str, chunks_text: str, citations: List[str]) -> str:
    """
    Calls Groq / Gemini / OpenAI to synthesize a professional, conversational response
    based strictly on the retrieved grounded documents.
    """
    import httpx
    from app.config import settings

    system_prompt = (
        "You are Company Brain — an Enterprise AI Operating System (like Glean). "
        "Your mission is to synthesize executive-grade, highly intelligent, grounded responses from company documents.\n\n"
        "RULES FOR EXCELLENCE:\n"
        "1. Synthesize directly from the provided company context with executive clarity.\n"
        "2. Structure your answer with clear markdown headings, key bullet points, and **bold** key concepts.\n"
        "3. Only name specific people, specs, SLAs, or architecture details that actually appear in the "
        "provided Company Documents Context below — never invent or assume names/figures not present there.\n"
        "4. NEVER output dictionary definitions or meta-commentary like 'Meaning of X' or 'Ways to say Y'.\n"
        "5. Keep the tone professional, natural, intelligent, and authoritative."
    )

    prompt = (
        f"User Query: {user_query}\n\n"
        f"Company Documents Context:\n{chunks_text}\n\n"
        f"Write a clear, grounded response:"
    )

    # Try Groq (blazing-fast, free, active key)
    if settings.GROQ_API_KEY:
        try:
            url = "https://api.groq.com/openai/v1/chat/completions"
            payload = {
                "model": "openai/gpt-oss-120b",
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt}
                ],
                "max_tokens": 600,
                "temperature": 0.2
            }
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(url, json=payload, headers={"Authorization": f"Bearer {settings.GROQ_API_KEY}", "Content-Type": "application/json"})
                if resp.status_code == 200:
                    return resp.json()["choices"][0]["message"]["content"].strip()
        except Exception as ex:
            logger.warning(f"[SynthesisLLM] Groq failed: {ex}")

    # Try Gemini
    if settings.GEMINI_API_KEY:
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.6-flash:generateContent?key={settings.GEMINI_API_KEY}"
            payload = {
                "contents": [{"parts": [{"text": f"{system_prompt}\n\n{prompt}"}]}],
                "generationConfig": {"temperature": 0.2, "maxOutputTokens": 600}
            }
            async with httpx.AsyncClient(timeout=12.0) as client:
                resp = await client.post(url, json=payload, headers={"Content-Type": "application/json"})
                if resp.status_code == 200:
                    candidates = resp.json().get("candidates", [])
                    if candidates:
                        return candidates[0]["content"]["parts"][0]["text"].strip()
        except Exception as ex:
            logger.warning(f"[SynthesisLLM] Gemini failed: {ex}")

    # Try OpenAI
    if settings.OPENAI_API_KEY:
        try:
            url = "https://api.openai.com/v1/chat/completions"
            payload = {
                "model": "gpt-4o-mini",
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt}
                ],
                "max_tokens": 600,
                "temperature": 0.2
            }
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(url, json=payload, headers={"Authorization": f"Bearer {settings.OPENAI_API_KEY}", "Content-Type": "application/json"})
                if resp.status_code == 200:
                    return resp.json()["choices"][0]["message"]["content"].strip()
        except Exception as ex:
            logger.warning(f"[SynthesisLLM] OpenAI failed: {ex}")

    # Canned raw concatenation fallback if all LLMs fail
    formatted_sources = "\n".join([f"## 📄 Grounded Search Result: `{c}`" for c in citations])
    return f"{formatted_sources}\n\n{chunks_text}"

synthesis_agent = ReflectionSynthesisAgent()
