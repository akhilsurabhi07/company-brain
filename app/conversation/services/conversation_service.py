"""Module 6A Main Conversation Service Orchestrator."""

import time
import re
import hashlib
import httpx
from typing import Dict, Any, Optional, AsyncGenerator, List
from sqlalchemy import text as sql_text
from app.db.database import async_session_factory
from app.conversation.domain.context import ConversationSession, ConversationTurn
from app.conversation.domain.persona import PersonaType
from app.conversation.domain.modes import ConversationMode
from app.conversation.domain.response_state import ResponseState
from app.conversation.domain.timeline import ConversationTimeline
from app.conversation.planner.conversation_planner import ConversationPlanner
from app.conversation.runtime.provider_health import ProviderHealthMonitor
from app.conversation.events.event_publisher import EventPublisher
from app.conversation.prompts.compiler import PromptCompiler
from app.conversation.routing.intelligent_router import IntelligentModelRouter
from app.conversation.runtime.orchestrator import RuntimeOrchestrator
from app.conversation.orchestration.consensus import MultiLLMConsensusEngine
from app.conversation.grounding.grounding_guard import GroundingGuard
from app.conversation.citations.citation_validator import CitationValidator
from app.conversation.review.response_review import AIResponseReviewEngine
from app.conversation.validation.output_guard import OutputGuard
from app.conversation.quality.explanation_engine import ExplanationEngine
from app.conversation.cache.conversation_cache import ConversationCache
from app.conversation.analytics.conversation_analytics import ConversationAnalytics, AnalyticsEvent
from app.conversation.interfaces.llm_provider import GenerationRequest
from app.conversation.session.session_manager import SessionManager
from app.security.content_redaction import redact_if_restricted
from app.conversation.session.postgres_repo import PostgresSessionRepository


class ConversationService:
    """Enterprise Conversational Intelligence Platform (ECIP) Main Orchestrator."""

    def __init__(self):
        # Real bug found 2026-08-22: this used to be InMemorySessionRepository —
        # a plain Python dict inside one process — so a server restart, crash,
        # or any multi-instance deployment silently wiped every tenant's entire
        # conversation history. Swapped for the real, durable Postgres-backed
        # repository (same BaseSessionRepository interface, no other change
        # needed here).
        self.session_repo = PostgresSessionRepository()
        self.session_manager = SessionManager(self.session_repo)
        self.planner = ConversationPlanner()
        self.health_monitor = ProviderHealthMonitor()
        self.event_publisher = EventPublisher()
        self.timeline = ConversationTimeline()
        self.orchestrator = RuntimeOrchestrator()
        self.cache = ConversationCache()
        self.analytics = ConversationAnalytics()

    async def _get_knowledge_context_version(self, tenant_id: str) -> str:
        """Real per-tenant knowledge fingerprint for cache keys — was a hardcoded
        "v1.0.0" literal at the cache_key call site, meaning the cache never actually
        invalidated when a tenant's data changed: upload a document that answers a
        question someone already asked, ask the identical question again, and you'd
        keep getting the old "I don't know" answer straight out of cache (Redis's
        24h TTL, or indefinitely from the in-process fallback while Redis is down)
        even though the underlying knowledge genuinely changed. Cheap real signal:
        row count + latest chunk timestamp for this tenant — either changing means
        new content (or new chunks from re-ingestion) landed since the last cache."""
        try:
            async with async_session_factory() as session:
                await session.execute(
                    sql_text("SELECT set_config('app.current_tenant_id', :tid, true)"), {"tid": str(tenant_id)}
                )
                res = await session.execute(
                    sql_text("SELECT count(*), max(created_at) FROM document_chunks WHERE tenant_id = :tid"),
                    {"tid": str(tenant_id)},
                )
                row = res.fetchone()
                return f"{row[0]}:{row[1]}"
        except Exception:
            # Fail open to a constant rather than blocking the whole turn on this —
            # worst case is a stale cache hit, not a broken response.
            return "v1.0.0"

    async def process_turn(
        self,
        tenant_id: str,
        user_id: str,
        session_id: Optional[str],
        user_query: str,
        persona: PersonaType = PersonaType.ENGINEER,
        mode: ConversationMode = ConversationMode.ASK,
        knowledge_context: Any = "KnowledgeContext v1.0.0 Grounded Baseline",
        use_consensus: bool = False,
        preferred_provider: Optional[str] = None,
        history: Optional[List[Dict[str, Any]]] = None,
        debug_retrieval: bool = False,
        # Real hardening found via code audit 2026-09-11: every real caller of
        # process_turn (chat_router x2, query_scheduler, and 3 Gateway paths)
        # already explicitly passes a real, safely-resolved caller_role, so
        # this default is currently unreachable in production -- but an
        # unreachable insecure default is still the wrong default. A future
        # caller that forgets to pass caller_role should fail closed to the
        # lowest privilege, not silently get full admin-level content access.
        caller_role: str = "member",
    ) -> Dict[str, Any]:
        start_time = time.time()
        persona_val = persona.value if isinstance(persona, PersonaType) else str(persona)
        mode_val = mode.value if isinstance(mode, ConversationMode) else str(mode)

        # Build context-aware prompt if history is present
        effective_query = user_query
        if history and len(history) > 0:
            history_summary = []
            for item in history[-20:]:  # Use last 20 turns for comprehensive context
                role = item.get("role", "user")
                content = item.get("content", "")
                if content:
                    history_summary.append(f"{role.capitalize()}: {content}")
            if history_summary:
                effective_query = "Previous Conversation Context:\n" + "\n".join(history_summary) + f"\n\nCurrent User Query: {user_query}"

        # 1. Resolve Session & Retrieve Multi-Turn History
        if not session_id:
            session = await self.session_manager.create_session(tenant_id, user_id)
            session_id = session.session_id
        else:
            session = await self.session_manager.get_session(session_id, tenant_id)
            if not session:
                session = await self.session_manager.create_session(tenant_id, user_id)
                session_id = session.session_id

        # 2. Build History String for Multi-Turn Continuity
        history_turns = session.turns[-5:] if session and session.turns else []
        history_lines = []
        last_turn_query = ""
        last_turn_answer = ""

        for t in history_turns:
            history_lines.append(f"User: {t.user_query}")
            if t.assistant_response:
                history_lines.append(f"Assistant: {t.assistant_response.text_content[:200]}...")
            last_turn_query = t.user_query
            if t.assistant_response:
                last_turn_answer = t.assistant_response.text_content

        history_str = "\n".join(history_lines)

        # 3. Fast-path: Greetings check BEFORE any reformulation (safeguard ordering)
        import re as _re
        lower_q = user_query.strip().lower()
        clean_q = _re.sub(r'[^\w\s]', '', lower_q).strip()
        words = clean_q.split()

        # ── Casual affirmations / short responses fast path ──
        if lower_q in {"haa", "ha", "haha", "yes", "yep", "yeah", "hmm", "hmmm"}:
            ack_text = "Got it! Let me know if you need anything specific from your company documents or have any other questions."
            return {
                "session_id": session_id, "turn_id": "acknowledgement", "provider": "fast-path",
                "response": {"text_content": ack_text, "citations": []},
                "response_text": ack_text, "model_used": "fast-path", "latency_ms": 0, "cost_usd": 0
            }

        greeting_words = {
            "hi", "hello", "hey", "greetings", "howdy", "sup", "holla", "hola",
            "namasthe", "namaste", "there", "good", "morning", "afternoon", "evening",
            "buddy", "friend", "bro", "dude", "man", "guys", "yo"
        }
        if words and all(w in greeting_words for w in words):
            intro_text = (
                "Hello! I am **Company Brain**, your enterprise knowledge assistant.\n\n"
                "How can I assist you today? You can ask me to:\n"
                "• Retrieve real information from whatever's actually ingested into your workspace\n"
                "• Answer general questions outside your company data\n"
                "• Tell you honestly when I don't have something, instead of guessing"
            )
            return {
                "session_id": session_id, "turn_id": "greeting", "provider": "fast-path",
                "response": {"text_content": intro_text, "citations": []},
                "response_text": intro_text, "model_used": "fast-path", "latency_ms": 0, "cost_usd": 0
            }

        # 4. Resolve Short Follow-Up Queries or reformulate contextual queries using history
        #    Only run for non-trivial queries (3+ words) to avoid reformulating tiny inputs
        resolved_query = user_query

        # NOTE (removed 2026-08-20): there used to be a "context-clarification" fast-path
        # here, triggered by phrases including literally "like glean" and "proper model
        # like glane" — i.e. it was keyed to the user's own past complaint phrasing and
        # responded with a scripted, entirely fabricated answer ("Project Orion" led by
        # a fictional "Dr. Sarah Lin", a fictional "Quantum Security Vault" led by a
        # fictional "Marcus Vance", with a fake citation to a document that doesn't
        # exist). This is exactly the "canned response keyed to the user's own past
        # phrasing" anti-pattern already found and removed once from app/agents/
        # orchestrator.py (see the response-quality-overhaul memory) — this was a second,
        # separate occurrence of the same pattern that overhaul missed. Deleted outright;
        # these queries now fall through to the real retrieval + LLM pipeline below,
        # which will honestly say it doesn't have that information rather than inventing it.

        # ── General Knowledge Instant Fast-Path (Strict Word-Boundary Lookup) ──
        from app.agents.orchestrator import _BUILTIN_KNOWLEDGE
        _builtin_hit = None
        if not any(who_word in lower_q for who_word in ["who is", "who are", "who lead", "who built", "who created", "who "]):
            if lower_q in _BUILTIN_KNOWLEDGE:
                _builtin_hit = _BUILTIN_KNOWLEDGE[lower_q]
            else:
                for _k_phrase, _v_phrase in _BUILTIN_KNOWLEDGE.items():
                    if " " in _k_phrase and _k_phrase in lower_q:
                        _builtin_hit = _v_phrase
                        break
                if _builtin_hit is None:
                    import re as _re
                    _q_words = _re.findall(r'\b[a-z0-9]+\b', lower_q)
                    # Real bug found via live testing 2026-08-22: matching ANY single
                    # word anywhere in a query — no matter how long or specific —
                    # hijacked genuine company questions with a generic dictionary
                    # definition. Confirmed live on a brand-new tenant: "What VPN
                    # client do we use and how do I request access?" (a question
                    # whose exact answer was sitting in a document uploaded moments
                    # earlier) got hijacked by the bare "vpn" entry into "VPN stands
                    # for Virtual Private Network..." — never touching real
                    # retrieval at all. "vpn" wasn't even on the existing short-
                    # acronym exclusion list below, but the deeper problem is the
                    # missing length gate: this fast-path should only fire for
                    # short, genuinely definition-seeking queries ("what is VPN",
                    # bare "AWS"), never for a longer, specific operational
                    # question that happens to use a common acronym as one word
                    # among many real ones — those must always reach real
                    # retrieval, which can honestly say "I don't know" if nothing
                    # real is actually found.
                    if len(_q_words) <= 4:
                        for _w in _q_words:
                            if _w in {"os", "ip", "ai", "ml", "ui", "ux", "cd", "ci", "hr", "ceo", "cto", "cfo", "cpo", "it", "vpn"} and len(_q_words) > 1:
                                continue
                            if _w in _BUILTIN_KNOWLEDGE and len(_w) >= 2:
                                _builtin_hit = _BUILTIN_KNOWLEDGE[_w]
                                break

        if _builtin_hit:
            return {
                "session_id": session_id, "turn_id": "builtin-kb", "provider": "fast-path",
                "response": {"text_content": _builtin_hit, "citations": ["General Knowledge"]},
                "response_text": _builtin_hit, "model_used": "fast-path",
                "confidence_score": 95, "latency_ms": 0, "cost_usd": 0
            }

        if lower_q in ["yes", "yep", "sure", "tell me more", "go deeper", "explain more", "more details", "expand"] and last_turn_query:
            resolved_query = f"Expand further on the previous discussion topic: '{last_turn_query}'"
        elif last_turn_query and len(words) >= 3 and not any(p in lower_q for p in ["show", "list", "files", "documents"]):
            # Contextual reformulation using Groq Llama 3.3 (blazing-fast, context-aware)
            try:
                from app.config import settings
                if settings.GROQ_API_KEY:
                    url = "https://api.groq.com/openai/v1/chat/completions"
                    payload = {
                        "model": "openai/gpt-oss-120b",
                        "messages": [
                            {
                                "role": "system",
                                "content": (
                                    "You are a search query optimizer. Given a conversation history, reformulate "
                                    "the user's latest query into a standalone, complete search query that can be searched "
                                    "on a search engine or vector database. Respond with ONLY the reformulated query text, nothing else. "
                                    "Do not add any prefix. If the query is already complete and standalone, return it as-is."
                                )
                            },
                            {
                                "role": "user",
                                "content": f"History:\nUser: {last_turn_query}\nAssistant: {last_turn_answer[:150]}\n\nLatest Query: {user_query}"
                            }
                        ],
                        "max_tokens": 100,
                        "temperature": 0.1
                    }
                    async with httpx.AsyncClient(timeout=4.0) as client:
                        resp = await client.post(url, json=payload, headers={"Authorization": f"Bearer {settings.GROQ_API_KEY}", "Content-Type": "application/json"})
                        if resp.status_code == 200:
                            reformulated = resp.json()["choices"][0]["message"]["content"].strip().strip('"')
                            if reformulated and len(reformulated) > 5:
                                resolved_query = reformulated
                                print(f"[QueryReformulation] Rewrote '{user_query}' -> '{resolved_query}'")
            except Exception as ex:
                print(f"[QueryReformulation-Error] {ex}")



        # ── Self-Introduction / Identity Intent Safeguard ──
        self_intro_phrases = [
            "tell about yourself", "tell me about yourself", "who are you", "what are you",
            "introduce yourself", "what is company brain", "what do you do", "what can you do",
            "how do you work", "explain yourself", "describe yourself", "who made you",
            "what is your purpose", "what are your capabilities", "about yourself", "about you"
        ]
        if any(phrase in lower_q for phrase in self_intro_phrases):
            # Real bug fixed 2026-08-20: this used to unconditionally claim "GitHub,
            # Jira, Slack, Microsoft Teams, Google Drive, WhatsApp Business" were all
            # ingested data sources, regardless of tenant — most of those connectors
            # are still fake stubs with zero real data (see the Phase 2 audit), so this
            # was actively lying about system capability to every tenant. Now queries
            # this tenant's actual `documents` table so the answer is true for whoever
            # is asking, not a fixed marketing list.
            from sqlalchemy import text as _text
            from app.db.database import async_session_factory as _asf
            source_rows = []
            try:
                async with _asf() as _session:
                    await _session.execute(_text("SELECT set_config('app.current_tenant_id', :tid, true)"), {"tid": tenant_id})
                    _res = await _session.execute(
                        _text("SELECT source_app, COUNT(*) FROM documents WHERE tenant_id = :tid GROUP BY source_app ORDER BY COUNT(*) DESC"),
                        {"tid": tenant_id},
                    )
                    source_rows = _res.fetchall()
            except Exception as _ex:
                print(f"[SelfIntro] Could not look up real ingested sources: {_ex}")

            if source_rows:
                sources_line = ", ".join(f"**{r[0]}** ({r[1]} doc{'s' if r[1] != 1 else ''})" for r in source_rows)
            else:
                sources_line = "nothing ingested yet for this workspace — connect a data source or upload a file to get started"

            self_text = (
                "I am **Company Brain** — an Enterprise AI Operating System built for your organisation.\n\n"
                "**What I can do:**\n"
                "• 🔍 **Company Knowledge Retrieval** — real hybrid search (vector + keyword + reranking) over whatever is actually ingested for your workspace\n"
                "• 🌐 **World Knowledge** — for general questions outside your company data, I answer from general intelligence\n"
                "• 🏢 **Tenant-Scoped Answers** — your data is isolated per tenant with PostgreSQL Row-Level Security\n"
                "• 🙅 **No guessing** — if I don't have relevant information for your question, I say so instead of making something up\n\n"
                f"**Your actual ingested data right now:** {sources_line}\n\n"
                "Ask me anything about what's really in your workspace, or any general question."
            )
            return {
                "session_id": session_id, "turn_id": "self-intro", "provider": "fast-path",
                "response": {"text_content": self_text, "citations": []},
                "response_text": self_text, "model_used": "fast-path", "latency_ms": 0, "cost_usd": 0
            }

        # ── Thanks / Acknowledgement Intent ──
        if lower_q in {"thanks", "thank you", "ok", "okay", "got it", "nice", "great", "cool", "awesome", "perfect"}:
            thanks_text = "You're welcome! Feel free to ask anything else about your company's data or any general question."
            return {
                "session_id": session_id, "turn_id": "acknowledgement", "provider": "fast-path",
                "response": {"text_content": thanks_text, "citations": []},
                "response_text": thanks_text, "model_used": "fast-path", "latency_ms": 0, "cost_usd": 0
            }

        # ── "What documents/files do you have" — real listing, not semantic search ──
        # Real gap found via live user testing 2026-08-21: a tenant with real ingested
        # documents (GitHub PR, Drive doc, Jira ticket, Slack message) still got a flat
        # "I don't have that information" for "what all the files you have about the
        # company". Root cause: this is a meta/listing question, not a content question
        # — vector similarity between "what files do you have" and a document's actual
        # subject matter is naturally weak regardless of how much real data exists, so
        # hybrid retrieval (correctly, for what it's built to do) finds nothing and the
        # honest-refusal path kicks in. The fix isn't "make retrieval try harder" —
        # it's routing this specific intent to what actually answers it: a real listing
        # of this tenant's own documents table, the same real query the self-intro
        # fast-path above already uses.
        # Word-set check, not exact-phrase substrings — a real user's actual wording
        # ("what all THE files you have") slips right past a fixed phrase list, which
        # is exactly what happened live: "what all files" never matched "what all the
        # files you have about the company" because of the one extra word "the".
        _listing_intent_words = {"what", "which", "list", "show"}
        _listing_subject_words = {"files", "file", "documents", "document", "docs", "doc", "data"}
        _q_word_set = set(re.findall(r"\b[a-z0-9]+\b", lower_q))
        if _q_word_set & _listing_intent_words and _q_word_set & _listing_subject_words:
            from sqlalchemy import text as _text
            from app.db.database import async_session_factory as _asf
            doc_rows = []
            try:
                async with _asf() as _session:
                    await _session.execute(_text("SELECT set_config('app.current_tenant_id', :tid, true)"), {"tid": tenant_id})
                    _res = await _session.execute(
                        _text("""
                            SELECT source_app, title FROM documents
                            WHERE tenant_id = :tid ORDER BY created_at DESC LIMIT 25
                        """),
                        {"tid": tenant_id},
                    )
                    doc_rows = _res.fetchall()
            except Exception as _ex:
                print(f"[DocumentListing-Error] {_ex}")

            if doc_rows:
                lines = "\n".join(f"- **{r.title}** ({r.source_app})" for r in doc_rows)
                listing_text = f"Here's what's actually in your workspace right now:\n\n{lines}"
                if len(doc_rows) == 25:
                    listing_text += "\n\n(showing the 25 most recent — there may be more)"
            else:
                listing_text = "Nothing's been ingested into this workspace yet — try uploading a document or connecting a data source."

            return {
                "session_id": session_id, "turn_id": "document-listing", "provider": "fast-path",
                "response": {"text_content": listing_text, "citations": []},
                "response_text": listing_text, "model_used": "fast-path", "latency_ms": 0, "cost_usd": 0
            }

        # Dynamically build real RAG context for company queries
        real_knowledge_context = knowledge_context
        retrieval_debug_info: Optional[Dict[str, Any]] = None
        chunks_list: List[Dict[str, Any]] = []  # populated below when real retrieval runs; stays
        # empty (not undefined) otherwise, so the real explanation built later always has a safe,
        # honest value to reflect instead of raising or silently reusing a stale one.

        if (knowledge_context == "KnowledgeContext v1.0.0 Grounded Baseline" or not knowledge_context):
            try:
                from app.retrieval.implementations.hybrid_retriever import hybrid_retriever
                # Execute RLS + ACL-scoped hybrid search (vector + full-text, RRF-fused,
                # cross-encoder reranked). The retriever itself now decides relevance via
                # the calibrated reranker threshold — no second, separate score gate here;
                # a chunk it returns has already earned its place.
                raw_results = await hybrid_retriever.search(
                    query=resolved_query, tenant_id=tenant_id, top_k=5,
                    user_id=user_id, debug=debug_retrieval,
                )
                chunks_list = raw_results.get("chunks", []) if isinstance(raw_results, dict) else raw_results
                if debug_retrieval:
                    retrieval_debug_info = raw_results.get("debug")

                # Real RBAC/ABAC content filtering (2026-08-21): ported from the real,
                # tested app/gateway/authorization/policy_engine.py, which existed but was
                # never wired to the live retrieval path — nothing here previously
                # filtered retrieved chunk *content* by role at all. Non-admin callers
                # never see salary/payroll/compensation content, regardless of whether
                # the document that chunk came from is otherwise a legitimate match.
                #
                # Real bug found via live testing 2026-08-21: this originally dropped the
                # ENTIRE chunk if it contained any restricted term anywhere. A real
                # document mixing a legitimate fact (leave days) with a restricted one
                # (salary) in the same chunk meant a member asking the plain, unrestricted
                # "how many leave days" question got the whole chunk denied, fell through
                # to the world-knowledge fallback, and got a wrong, hallucinated generic
                # answer instead of the correct real one — a strictly worse outcome than
                # just redacting the restricted sentence. Fixed to redact only the
                # sentences that actually contain a restricted term, sentence-by-sentence,
                # keeping the rest of the chunk's real content intact. Only drops the
                # whole chunk if every sentence in it turns out to be restricted.
                # Real bug found via live testing 2026-08-22 (still applies): decisions and
                # graph facts wired into the live chat context must go through the exact
                # same redaction as document chunks, or a non-admin can extract restricted
                # figures (e.g. salary) verbatim through that path instead. Now shared with
                # the Decisions/Risks read endpoints (app/api/graph_api.py) via
                # app.security.content_redaction — see that module's docstring for the full
                # history of the bug this closure used to be a standalone fix for.
                def _redact_if_restricted(text_in: str) -> Optional[str]:
                    return redact_if_restricted(text_in, caller_role)

                if caller_role != "admin":
                    filtered_chunks = []
                    for c in chunks_list:
                        content = c.get("content") or c.get("chunk_content") or ""
                        redacted_content = _redact_if_restricted(content)
                        if redacted_content is None:
                            continue  # every sentence was restricted — drop the whole chunk
                        c = dict(c)
                        if "content" in c:
                            c["content"] = redacted_content
                        if "chunk_content" in c:
                            c["chunk_content"] = redacted_content
                        filtered_chunks.append(c)
                    chunks_list = filtered_chunks

                retrieved_texts = []
                retrieved_citations = []
                for r in chunks_list:
                    title = r.get("doc_title") or r.get("document_title") or "Untitled Document"
                    content = r.get("content") or r.get("chunk_content") or ""
                    retrieved_texts.append(f"Source Document: {title}\nContent:\n{content}")
                    if title not in retrieved_citations:
                        retrieved_citations.append(title)

                # Real gap found via live testing 2026-08-21: graph_decisions (real
                # decisions extracted from resolved GitHub PRs / Jira tickets) is a
                # separate table from document_chunks — HybridRetriever, correctly, only
                # ever searches document_chunks. That meant a real, specific, recorded
                # decision rationale was completely invisible to chat: asking "why did
                # we choose X" fell straight through to world-knowledge and answered
                # with generic textbook advice instead of the tenant's own real recorded
                # reasoning. This is a real, tenant-scoped keyword search over decisions,
                # additive to document retrieval — never replaces it, never changes
                # HybridRetriever itself.
                decision_keywords = [w for w in re.findall(r"\b[a-zA-Z0-9]{4,}\b", resolved_query.lower())
                                      if w not in {"what", "when", "where", "which", "about", "there", "they", "have", "does", "with", "this", "that"}]
                if decision_keywords:
                    try:
                        from app.db.database import async_session_factory as _dec_asf
                        async with _dec_asf() as _session:
                            await _session.execute(sql_text("SELECT set_config('app.current_tenant_id', :tid, true)"), {"tid": tenant_id})
                            or_clauses = " OR ".join(f"decision_title ILIKE :kw{i} OR rationale ILIKE :kw{i}" for i in range(len(decision_keywords)))
                            params = {"tid": tenant_id, **{f"kw{i}": f"%{kw}%" for i, kw in enumerate(decision_keywords)}}
                            dec_res = await _session.execute(
                                sql_text(f"""
                                    SELECT decision_title, rationale, actual_outcome, state FROM graph_decisions
                                    WHERE tenant_id = :tid AND ({or_clauses})
                                    ORDER BY created_at DESC LIMIT 3
                                """),
                                params,
                            )
                            for d in dec_res.fetchall():
                                dec_text = (
                                    f"Real Decision: {d.decision_title}\n"
                                    f"Outcome: {d.actual_outcome or 'pending'} ({d.state})\n"
                                    f"Rationale: {d.rationale or ''}"
                                )
                                # CRITICAL: apply the same RBAC redaction as document chunks —
                                # see _redact_if_restricted's docstring for the real, live-
                                # confirmed leak this closes (a real salary decision's exact
                                # figures were fully readable by a non-admin test account
                                # before this fix).
                                dec_text = _redact_if_restricted(dec_text)
                                if dec_text is None:
                                    continue
                                retrieved_texts.append(dec_text)
                                if d.decision_title not in retrieved_citations:
                                    retrieved_citations.append(d.decision_title)
                                # Real Module 4 gap found via inspection 2026-08-22: a decision
                                # was only ever appended to retrieved_texts (the LLM's own
                                # prompt content) — never to chunks_list, which is the ONLY
                                # thing ExplanationEngine.generate_explanation() looks at for
                                # evidence_used/reasoning_summary/grounding_status. A real
                                # answer built entirely from a real decision (confirmed live:
                                # its actual rationale text appeared verbatim in the answer)
                                # still showed "evidence_used: []" and
                                # "NO_COMPANY_DATA_RETRIEVED" in the explanation panel — a
                                # real, user-visible contradiction with the top-level grounding
                                # field (which DOES check the fuller context and correctly said
                                # grounded). Adding a real chunks_list entry for every decision
                                # actually used closes that gap.
                                chunks_list.append({
                                    "content": dec_text,
                                    "doc_title": d.decision_title,
                                    "source_app": "decision",
                                    "score": 1.0,
                                })
                    except Exception as dec_ex:
                        print(f"[DecisionSearch-Error] {dec_ex}")

                if retrieved_texts:
                    # Graph-aware enrichment (2026-08-20): the real knowledge graph
                    # (graph_entities/graph_relationships, populated on ingestion) has
                    # been sitting disconnected from live chat — reachable only via the
                    # separate, frozen Module 4 debug endpoint (see the Phase 2 audit).
                    # This adds real graph facts about the *already-retrieved* documents
                    # as supplementary context — purely additive, after retrieval has
                    # already picked its chunks, so it cannot change what gets retrieved
                    # or its ranking. Zero risk to the frozen HybridRetriever behavior;
                    # nothing here touches hybrid_retriever.py. Best-effort: any failure
                    # just means no graph enrichment this turn, never a broken chat turn.
                    graph_facts_lines = []
                    try:
                        from app.db.postgres_knowledge_repo import postgres_knowledge_repo

                        # Real Module 4 gap found via inspection 2026-08-22: entities only
                        # ever got matched by an exact document TITLE — for connector
                        # documents with generic auto-generated titles ("Channel Message in
                        # #general", "PR #42: ..."), that's essentially never a real entity
                        # name (people, projects, vendors), so graph enrichment almost never
                        # fired outside the narrow case of a document literally titled
                        # after an entity. Also trying real candidate entity names pulled
                        # from the user's own query — e.g. "Project Falcon" or a capitalized
                        # proper noun — so enrichment engages based on what's actually being
                        # asked about, not just an incidental title match.
                        _entity_candidates = list(retrieved_citations[:3])
                        _proj_matches = re.findall(r"\b[Pp]roject\s+([A-Z][a-zA-Z0-9]+)\b", resolved_query)
                        for _p in _proj_matches:
                            _entity_candidates.append(f"Project {_p}")
                        _cap_seq = re.findall(r"\b([A-Z][a-zA-Z0-9]+(?:\s+[A-Z][a-zA-Z0-9]+)*)\b", resolved_query)
                        _entity_candidates.extend(_cap_seq)

                        _seen_entities = set()
                        _any_real_entity_matched = False
                        for _cand in _entity_candidates:
                            if _cand in _seen_entities:
                                continue
                            _seen_entities.add(_cand)
                            entity = await postgres_knowledge_repo.get_entity_by_canonical_name(tenant_id, _cand)
                            if not entity:
                                continue
                            _any_real_entity_matched = True
                            # Real multi-hop traversal (fixed 2026-08-22 — this used to
                            # silently do only 1 hop no matter what was asked for; genuine
                            # graph traversal now supports real 2-hop cross-document chains,
                            # e.g. Person -> leads -> Project -> depends_on -> Vendor.
                            edges = await postgres_knowledge_repo.get_relationships_for_entity_name(tenant_id, _cand, max_hops=2)
                            # Real bug found via live end-to-end multi-hop testing 2026-08-31:
                            # "other" used to always be resolved against the ORIGINAL root
                            # entity (_cand) — correct only for a direct 1-hop edge. A 2-hop
                            # edge's own source/target are almost never _cand itself (the real
                            # path is root -> intermediate -> destination), so this always fell
                            # through to "other = edge[source]" and repeated the INTERMEDIATE
                            # entity's name instead of the real, further destination — e.g. a
                            # seeded chain Person -leads-> Project -depends_on-> Vendor
                            # produced "Person depends_on Project (2-hop)" and the real vendor
                            # never appeared anywhere in the answer at all. Track which
                            # entities are already known as the path is walked in hop order so
                            # each edge's near/other side is resolved relative to the path so
                            # far, not against the root every time.
                            _known_entities = {_cand}
                            for edge in sorted(edges[:8], key=lambda e: e.get("hop", 1)):
                                src, tgt = edge["source"], edge["target"]
                                if tgt in _known_entities and src not in _known_entities:
                                    near, other = tgt, src
                                else:
                                    near, other = src, tgt
                                _known_entities.add(other)
                                hop_note = " (2-hop)" if edge.get("hop", 1) > 1 else ""
                                # CRITICAL: same RBAC redaction as decisions/document chunks —
                                # a real relationship or entity name could itself reference
                                # restricted info (e.g. an entity literally named after a
                                # compensation program).
                                _rel_line = _redact_if_restricted(f"- \"{near}\" {edge['relation']} {other}{hop_note}")
                                if _rel_line is not None:
                                    graph_facts_lines.append(_rel_line)

                        # Real gap found 2026-08-22: graph_facts (real, tenant-scoped
                        # metric/fact records) had ZERO live surfacing anywhere in chat —
                        # graph enrichment only ever showed relationships, never facts
                        # themselves. graph_facts has no direct entity-linkage column in
                        # the schema (a real, separate structural gap — see the Module 4
                        # audit notes), so this is a tenant-scoped, best-effort real lookup,
                        # only shown once a real entity from this turn actually matched the
                        # graph — avoiding unrelated facts appearing on every unrelated turn.
                        if _any_real_entity_matched:
                            try:
                                async with async_session_factory() as _fact_session:
                                    await _fact_session.execute(
                                        sql_text("SELECT set_config('app.current_tenant_id', :tid, true)"), {"tid": tenant_id}
                                    )
                                    _fact_rows = await _fact_session.execute(
                                        sql_text("""
                                            SELECT metric_name, value, period FROM graph_facts
                                            WHERE tenant_id = :tid AND is_current = TRUE
                                            ORDER BY created_at DESC LIMIT 3
                                        """),
                                        {"tid": tenant_id},
                                    )
                                    for _f in _fact_rows.fetchall():
                                        _fact_line = _redact_if_restricted(
                                            f"- Real fact: {_f.metric_name} = {_f.value}"
                                            + (f" ({_f.period})" if _f.period else "")
                                        )
                                        if _fact_line is not None:
                                            graph_facts_lines.append(_fact_line)
                            except Exception as _fact_ex:
                                print(f"[GraphFactsEnrichment-Error] {_fact_ex}")
                    except Exception as graph_ex:
                        print(f"[GraphEnrichment-Error] {graph_ex}")

                    graph_facts_block = ""
                    if graph_facts_lines:
                        graph_facts_block = "\n\n---\n\nReal Knowledge Graph Relationships (for the documents above):\n" + "\n".join(graph_facts_lines)
                        # Same real gap as decisions above: graph relationships/facts were
                        # only ever added to the LLM's own prompt content (graph_facts_block),
                        # never to chunks_list — so ExplanationEngine's evidence_used/
                        # grounding_status stayed blind to them even when they were the real
                        # source of part of the answer (confirmed live: "Stripe" and a real
                        # metric appeared in an answer whose retrieved document never
                        # mentioned either, sourced entirely from the graph).
                        chunks_list.append({
                            "content": "\n".join(graph_facts_lines),
                            "doc_title": "Knowledge Graph",
                            "source_app": "graph",
                            "score": 0.95,
                        })

                    real_knowledge_context = {
                        "query": resolved_query,
                        "documents": [{"title": c, "content": ""} for c in retrieved_citations],
                        "text_content": "\n\n---\n\n".join(retrieved_texts) + graph_facts_block
                    }
                else:
                    # Honest refusal indicator in context for world knowledge routing
                    real_knowledge_context = "HONEST_REFUSAL_NO_COMPANY_DATA"
            except Exception as ex:
                print(f"[RAG-Pre-Retrieve-Error] {ex}")

        # Direct World Knowledge Fallback Routing if RAG yielded nothing.
        # Skipped for consensus-mandated turns (explicit use_consensus, or high-stakes
        # personas) so those queries still go through multi-LLM consensus review instead
        # of silently short-circuiting past it — and so the response always carries the
        # full field set ("model_used", "cost_usd", etc.) callers rely on.
        if real_knowledge_context == "HONEST_REFUSAL_NO_COMPANY_DATA" and not (
            use_consensus or persona in [PersonaType.LEGAL_COUNSEL, PersonaType.FINANCE, PersonaType.CEO]
        ):
            from app.agents.orchestrator import _world_knowledge
            from app.conversation.domain.response_payload import MultimodalResponsePayload

            # Real bug found via live testing 2026-08-21: _world_knowledge() does a real
            # web search over the open internet whenever retrieval finds nothing, with
            # no distinction between an actual general-knowledge question ("what is an
            # API") and a query that's clearly asking about the user's own private
            # internal project ("what is the architecture of Project Nebula"). For the
            # latter, a real web search often finds real content about some unrelated
            # public thing sharing that name (NASA's historical "Nebula" cloud platform,
            # in this exact case) and confidently answers as if it were relevant — which
            # reads exactly like a hallucination about the user's own company, even
            # though every individual fact quoted is technically real and web-sourced.
            # Detect the "Project <Name>" / "<Name> project" reference pattern and check
            # whether that name appears ANYWHERE in this tenant's real data first; if it
            # doesn't, this is honestly "no company data about that", not a general
            # knowledge question — skip the web search and say so.
            # Real bug found via live testing 2026-08-21: this matched only lowercase
            # "project", so it never fired for a real-world query written the natural
            # way — "Project Zephyrion" — since virtually everyone capitalizes it.
            # Fixed to accept either case for the trigger word itself (`[Pp]roject`)
            # while keeping the actual captured name strictly `[A-Z]...` — still a real
            # proper noun, not accidentally matching an ordinary lowercase word that
            # happens to follow "project" (e.g. "project management").
            _proper_noun_match = re.search(
                r"\b[Pp]roject\s+([A-Z][a-zA-Z0-9]+)\b|\b([A-Z][a-zA-Z0-9]+)\s+[Pp]roject\b", resolved_query
            )
            _referenced_name = None
            if _proper_noun_match:
                _referenced_name = (_proper_noun_match.group(1) or _proper_noun_match.group(2))

            _name_found_in_tenant_data = True  # default permissive — only restrict when we can positively check
            if _referenced_name:
                try:
                    async with async_session_factory() as _session:
                        await _session.execute(
                            sql_text("SELECT set_config('app.current_tenant_id', :tid, true)"), {"tid": tenant_id}
                        )
                        _hit = await _session.execute(
                            sql_text("""
                                SELECT 1 FROM documents WHERE tenant_id = :tid AND (title ILIKE :pat OR content ILIKE :pat) LIMIT 1
                            """),
                            {"tid": tenant_id, "pat": f"%{_referenced_name}%"},
                        )
                        _name_found_in_tenant_data = _hit.fetchone() is not None
                except Exception as _ex:
                    print(f"[InternalReferenceCheck-Error] {_ex}")
                    _name_found_in_tenant_data = True  # fail open to the existing behavior on error

            if _referenced_name and not _name_found_in_tenant_data:
                fallback_text = (
                    f"I don't have any information about \"{_referenced_name}\" in your company's data. "
                    "If you're asking about something outside your organization with a similar name, let me know "
                    "and I can answer from general knowledge instead."
                )
            else:
                fallback_text = await _world_knowledge(resolved_query)
                # Real trust gap found via live testing 2026-08-22: a question phrased
                # as a claim about the user's own company ("Is customer data properly
                # isolated between our different customers?", "Are we PostgreSQL-safe
                # yet?") that finds no real company data falls to general knowledge —
                # which then confidently answers "Yes, ..." with generic textbook
                # advice, phrased exactly like it's describing the user's real,
                # verified system. The "Why this answer?" panel does honestly disclose
                # NO_COMPANY_DATA_RETRIEVED, but the chat bubble text itself reads as
                # an assertion about their actual setup unless they click through.
                # Prepending an explicit disclaimer here for this specific query shape
                # — "our/we/us" + no real data found — makes the chat bubble itself
                # honest, not just the explanation panel underneath it.
                if re.search(r"\b(our|we|us|we've|we're)\b", resolved_query.lower()) and not fallback_text.lower().startswith(
                    ("i don't have", "i wasn't able", "i couldn't find")
                ):
                    fallback_text = (
                        "I don't have specific, verified information about your organization's actual setup for this — "
                        "here's general guidance instead:\n\n" + fallback_text
                    )
            payload = MultimodalResponsePayload(
                text_content=fallback_text,
                citations=[{"citation_id": "1", "source": "General World Knowledge", "trust_score": 0.90}],
            )
            latency = round((time.time() - start_time) * 1000.0, 2)
            
            turn = ConversationTurn(
                session_id=session_id,
                user_query=user_query,
                persona_used=persona if isinstance(persona, PersonaType) else PersonaType.ENGINEER,
                mode_used=mode if isinstance(mode, ConversationMode) else ConversationMode.ASK,
                system_prompt="World Knowledge Fallback",
                prompt_snapshot_id="world_fallback",
                assistant_response=payload,
                model_name="world-knowledge-fallback",
                latency_ms=latency,
                cost_usd=0.0,
            )
            await self.session_repo.add_turn(session_id, turn, tenant_id)

            # Real bug found 2026-08-22 (surfaced once a real, valid tenant_id let
            # retrieval run to completion cleanly instead of erroring out early on
            # a fake placeholder tenant_id): this branch returned a real turn_id
            # but never called self.timeline.record_turn() — so any query honestly
            # answered from general knowledge (no company data for this tenant yet,
            # a common state for any brand-new tenant) silently broke
            # timeline.replay_turn()/"Execution Timeline" lookups for that turn,
            # even though the turn_id itself looked completely valid.
            from app.conversation.domain.response_state import ResponseState as _ResponseState
            self.timeline.record_turn(
                turn_id=turn.turn_id,
                session_id=session_id,
                user_query=user_query,
                compiled_prompt="World Knowledge Fallback",
                provider_used="world-knowledge-fallback",
                state=_ResponseState.COMPLETED,
                latency_ms=latency,
                token_count=len(fallback_text.split()),
                response_text=fallback_text,
            )

            return {
                "session_id": session_id,
                "turn_id": turn.turn_id,
                "response": payload.model_dump(),
                "response_text": fallback_text,
                "provider": "world-knowledge",
                "model_used": "world-knowledge-fallback",
                "persona": persona_val,
                "mode": mode_val,
                # Match the field set the main return path carries — this branch used to
                # omit these, which crashed any caller that (reasonably) expected them
                # to always be present (e.g. reading latency_ms unconditionally).
                "latency_ms": latency,
                "cost_usd": 0.0,
                "cache_hit": False,
                "confidence_score": 0,  # honest — no company-data grounding ran on this fallback path
                # Honest explanation for this path too — no grounding/citation/review
                # pipeline ran here since this is a general-knowledge fallback, not a
                # RAG answer, so the "why" is genuinely "no company data, so this	came
                # from general knowledge" rather than a fabricated grounding score.
                "explanation": {
                    "user_query": resolved_query,
                    "reasoning_summary": (
                        "No relevant company documents were found for this query, so this answer came "
                        "from general knowledge rather than your organization's data."
                    ),
                    "evidence_used": [],
                    "confidence_score": 0.0,
                    "citations": payload.citations,
                    "grounding_status": "NO_COMPANY_DATA_RETRIEVED",
                },
            }

        # 4. Compile Prompt with Multi-Turn History
        compiled = PromptCompiler.compile(
            prompt_name=mode_val if mode_val in ConversationMode.__members__ else "ARCHITECTURE_REVIEW",
            user_query=resolved_query,
            knowledge_context=real_knowledge_context if isinstance(real_knowledge_context, str) else real_knowledge_context.get("text_content", ""),
            persona=persona_val,
            history_str=history_str,
        )

        self.event_publisher.publish("ConversationStarted", tenant_id, session_id, {"query": user_query})

        # 2. Conversation Planning
        plan = self.planner.plan_conversation(query=user_query, mode=mode_val, persona=persona_val)
        if plan.requires_consensus:
            use_consensus = True

        # 4. Check Conversation Cache
        # Keyed on the resolved question text itself (not compiled.prompt_hash, which bakes
        # in the full rendered prompt INCLUDING conversation history) — otherwise a repeated
        # question can never hit cache once any turn has been added to the session, since
        # the history prefix — and therefore the hash — differs every time.
        #
        # CRITICAL real bug found via live testing 2026-08-21: this used to hash only the
        # query text, with no caller_role in it at all. The RBAC/ABAC content filter above
        # redacts restricted facts BEFORE generation, but the final generated ANSWER is what
        # gets cached — so an admin asking a salary question first would cache the real,
        # unredacted figure, and a member asking the exact same question afterward got that
        # cached admin answer served back verbatim, completely bypassing the RBAC filter.
        # Confirmed live: admin asked for the base salary figure, got the real number; a
        # member then asked the identical question and received the cached admin answer,
        # real number included. caller_role is now part of what's hashed, so admin and
        # non-admin answers are cached in entirely separate namespaces and can never
        # cross-serve each other.
        query_hash = hashlib.sha256(f"{caller_role}:{resolved_query.strip().lower()}".encode("utf-8")).hexdigest()
        knowledge_version = await self._get_knowledge_context_version(tenant_id)
        cache_key = self.cache.generate_cache_key(
            query_hash, knowledge_version, compiled.version, persona_val, tenant_id, preferred_provider or "default"
        )
        cached_payload = await self.cache.get(cache_key)
        cache_hit = cached_payload is not None
        # 5. Route Model & Execute Generation with Provider Health Monitoring
        healthy_providers = self.health_monitor.get_healthy_providers()
        if cache_hit:
            # Serve a deep copy so mutations below (e.g. output sanitization) never
            # corrupt the cached original for future lookups.
            payload = cached_payload.model_copy(deep=True)
            model_used = "cache"
            cost = 0.0
        elif use_consensus or persona in [PersonaType.LEGAL_COUNSEL, PersonaType.FINANCE, PersonaType.CEO]:
            req = GenerationRequest(prompt=compiled.compiled_text, persona=persona_val, mode=mode_val)
            consensus_res = await MultiLLMConsensusEngine.evaluate_consensus(req)
            payload = consensus_res.synthesized_payload
            model_used = "multi-llm-consensus"
            cost = 0.0120
            self.event_publisher.publish("ConsensusTriggered", tenant_id, session_id, {"models": ["gpt", "claude", "gemini"]})
        else:
            # Honour the preferred_provider hint from the UI model selector.
            # Map friendly names (openai, gemini, mock, groq, huggingface, anthropic,
            # local) → provider keys used by the factory. Real bug found via live
            # testing 2026-08-21: the frontend dropdown offers "Anthropic" as a real
            # selectable option, but "anthropic" was missing from this map — selecting
            # it silently fell through to auto-routing instead, with no indication the
            # explicit choice was ignored.
            _provider_map = {
                "openai": "OPENAI",
                "gemini": "GEMINI",
                "groq": "GROQ",
                "huggingface": "HUGGINGFACE",
                "anthropic": "ANTHROPIC",
                "local": "LOCAL",
                "mock": "MOCK",
            }
            if preferred_provider and preferred_provider.lower() in _provider_map:
                model_used = _provider_map[preferred_provider.lower()]
            else:
                model_used = IntelligentModelRouter.route_request(user_query)
                # Ensure selected provider is healthy
                if healthy_providers and model_used not in healthy_providers:
                    model_used = healthy_providers[0]
                    self.event_publisher.publish("ProviderChanged", tenant_id, session_id, {"new_provider": model_used})

            req = GenerationRequest(
                prompt=compiled.compiled_text,         # context-enriched query → goes as user role
                raw_query=user_query,                  # exact user turn question
                history=history,                       # conversation history array
                system_prompt=compiled.system_prompt,  # persona system prompt → goes as system role
                model_name=model_used,
                persona=persona_val,
                mode=mode_val,
                tenant_id=tenant_id,
                user_id=user_id,
            )

            # Step 2: Enforce PostgreSQL Row-Level Security (RLS) on DB session safely with bound parameters
            try:
                # Real bug found via live testing 2026-08-21: this redundant local
                # re-import of async_session_factory (already imported at module level)
                # made the name local to this ENTIRE function — the same Python scoping
                # gotcha documented elsewhere in this file — causing an earlier, legitimate
                # use of the module-level async_session_factory (in the "Project X"
                # internal-reference check above) to raise "cannot access local variable"
                # before this line ever ran. Removed; nothing here needs its own import.
                async with async_session_factory() as db_session:
                    await db_session.execute(sql_text("SELECT set_config('app.current_tenant_id', :tenant_id, true)"), {"tenant_id": tenant_id})
                    print(f"[DB-RLS-QUERY-LOG] Connection {id(db_session)}: set_config('app.current_tenant_id', '{tenant_id}') EXECUTED CLEANLY.")
            except Exception as rls_ex:
                print(f"[DB-RLS-QUERY-ERROR] Tenant session scoping error for tenant_id = '{tenant_id}': {rls_ex}")

            try:
                gen_res = await self.orchestrator.execute_generation(req)
                payload = gen_res.payload
                cost = gen_res.cost_usd
                self.health_monitor.record_success(model_used, 150.0)
                # Reflect which provider/model actually answered — the orchestrator may
                # have failed over to a different real provider than originally routed to.
                model_used = gen_res.model_name or model_used
            except Exception as ex:
                self.health_monitor.record_error(model_used, str(ex))
                raise ex

        latency = round((time.time() - start_time) * 1000.0, 2)
        # Real bug found via live testing 2026-08-21: this used to cache EVERY
        # response unconditionally, including RuntimeOrchestrator's honest "all
        # providers failed" degraded response (model_name == "none") — an external
        # LLM-quota outage is transient, not a fact worth memoizing, but caching it
        # meant a query that happened to hit a temporary all-providers-down moment
        # would keep serving that exact failure message for the cache's full TTL
        # (up to 24h), long after providers actually recovered.
        if not cache_hit and model_used != "none":
            await self.cache.set(cache_key, payload)
        response_state = ResponseState.VALIDATED

        # 6. Safety & Quality Guards
        sanitized_text, safety_pass = OutputGuard.sanitize_output(payload.text_content)
        payload.text_content = sanitized_text

        # NOTE: verify against real_knowledge_context (what was actually retrieved and put
        # in the prompt this turn), not the `knowledge_context` param — that one is still
        # the literal placeholder default for almost every real call, which would make
        # grounding/citation checks compare the answer against nothing.
        # Consensus turns (Legal/Finance/CEO) legitimately draw on the models' own
        # professional expertise rather than retrieved company documents, so they aren't
        # held to the same "must match KnowledgeContext" bar as normal RAG-mode answers.
        grounding_res = await GroundingGuard.verify_grounding(
            payload.text_content, real_knowledge_context, user_query=resolved_query,
            require_company_grounding=(model_used != "multi-llm-consensus"),
        )
        if not grounding_res.is_grounded:
            self.event_publisher.publish("GroundingRejected", tenant_id, session_id, {"score": grounding_res.grounding_score})

        citation_res = CitationValidator.validate_citations(payload.text_content, payload.citations, real_knowledge_context)
        if citation_res.citation_coverage < 0.5:
            self.event_publisher.publish("CitationFailed", tenant_id, session_id, {"coverage": citation_res.citation_coverage})

        review_res = AIResponseReviewEngine.review_response(
            payload, mode_val,
            grounding_score=grounding_res.grounding_score,
            citation_coverage=citation_res.citation_coverage,
        )
        if not review_res.is_approved:
            self.event_publisher.publish("ResponseReviewRejected", tenant_id, session_id, {
                "quality_score": review_res.quality_score, "reason": review_res.rejection_reason,
            })

        # Real "Why This Answer?" explanation — see explanation_engine.py's docstring
        # for the fake stub this replaced (fixed 2026-08-20). Built from this exact
        # turn's real grounding/citation/review results and real retrieved chunks,
        # not a fixed template.
        explanation_res = ExplanationEngine.generate_explanation(
            user_query=resolved_query, response_payload=payload,
            grounding_res=grounding_res, citation_res=citation_res, review_res=review_res,
            chunks=chunks_list,
        )

        # 7. Record Turn, Timeline Trace & Analytics
        turn = ConversationTurn(
            session_id=session_id,
            user_query=user_query,
            persona_used=persona if isinstance(persona, PersonaType) else PersonaType.ENGINEER,
            mode_used=mode if isinstance(mode, ConversationMode) else ConversationMode.ASK,
            system_prompt=compiled.system_prompt,
            prompt_snapshot_id=compiled.snapshot_id,
            assistant_response=payload,
            model_name=model_used,
            latency_ms=latency,
            cost_usd=cost,
        )
        await self.session_repo.add_turn(session_id, turn, tenant_id)

        self.timeline.record_turn(
            turn_id=turn.turn_id,
            session_id=session_id,
            user_query=user_query,
            compiled_prompt=compiled.compiled_text,
            provider_used=model_used,
            state=response_state,
            latency_ms=latency,
            token_count=250,
            response_text=payload.text_content,
        )

        self.analytics.record_event(
            AnalyticsEvent(
                tenant_id=tenant_id,
                session_id=session_id,
                turn_id=turn.turn_id,
                latency_ms=latency,
                cost_usd=cost,
                tokens=250,
                cache_hit=cache_hit,
                groundedness_score=grounding_res.grounding_score,
                citation_coverage=citation_res.citation_coverage,
                hallucination_detected=not grounding_res.is_grounded,
            )
        )

        self.event_publisher.publish("ConversationCompleted", tenant_id, session_id, {"turn_id": turn.turn_id, "latency_ms": latency})

        result = {
            "session_id": session_id,
            "turn_id": turn.turn_id,
            "response": payload.model_dump(),
            "response_text": payload.text_content,
            "provider": model_used,
            "model_used": model_used,
            "latency_ms": latency,
            "cost_usd": cost,
            "cache_hit": cache_hit,
            "response_state": response_state.value,
            "prompt_hash_sha256": compiled.prompt_hash,
            "plan": plan.model_dump(),
            "grounding": grounding_res.model_dump(),
            "citation": citation_res.model_dump(),
            "review": review_res.model_dump(),
            "explanation": explanation_res.model_dump(),
            # Real bug fixed 2026-08-20: this key was never set on the main RAG path at
            # all, so the frontend's confidence badge (`evt.confidence || 0`) always
            # silently showed nothing for real answers. explanation_res.confidence_score
            # is 0.0-1.0 (grounding+quality composite); the badge expects a 0-100 scale.
            "confidence_score": round(explanation_res.confidence_score * 100),
        }
        # Retrieval diagnostics (query, per-candidate vector/keyword/rerank scores,
        # latencies) are opt-in only (debug_retrieval=True) — never attached for normal
        # end-user turns, so nothing sensitive about scoring internals leaks by default.
        if retrieval_debug_info is not None:
            result["retrieval_debug"] = retrieval_debug_info
        return result
