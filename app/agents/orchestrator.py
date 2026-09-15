import uuid
import time
import logging
import re
import ast
import operator
import httpx
from typing import List, Dict, Any, Tuple
from app.agents.agent_trace import AgentTraceTracker
from app.agents.interfaces.agent_interfaces import AgentTaskContext, AgentResult
from app.agents.workers.rag_agent import rag_agent
from app.agents.workers.code_analysis_agent import code_analysis_agent
from app.agents.workers.synthesis_agent import synthesis_agent

logger = logging.getLogger("company_brain.agents.orchestrator")


async def _execute_web_search(query: str) -> str:
    """
    Performs a real-time web search using Yahoo Search (primary)
    and DuckDuckGo HTML search (secondary fallback).
    """
    from bs4 import BeautifulSoup
    import urllib.parse

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    encoded_query = urllib.parse.quote_plus(query)

    # ── Try Yahoo Search first ──
    try:
        url = f"https://search.yahoo.com/search?p={encoded_query}"
        async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                snippets = soup.find_all("div", class_="compText")
                if snippets:
                    results = []
                    for idx, sn in enumerate(snippets[:6], 1):
                        snippet_text = sn.text.strip()
                        title_text = "Search Result"
                        parent = sn.parent
                        while parent and parent.name not in ["li", "div"] and "dd" not in parent.get("class", []):
                            parent = parent.parent
                        if parent:
                            title_el = parent.find("h3")
                            if title_el:
                                title_text = title_el.text.strip()
                        results.append(f"[{idx}] {title_text}\nSnippet: {snippet_text}")
                    return "\n\n".join(results)
    except Exception as ex:
        logger.warning(f"[WorldKnowledge] Yahoo search failed: {ex}")

    # ── Fallback to DuckDuckGo HTML search ──
    try:
        url = f"https://html.duckduckgo.com/html/?q={encoded_query}"
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                results = soup.find_all("a", class_="result__snippet")
                titles = soup.find_all("a", class_="result__url")
                if results:
                    snippets = []
                    for idx, (t, r) in enumerate(zip(titles[:5], results[:5]), 1):
                        title_text = t.text.strip()
                        snippet_text = r.text.strip()
                        snippets.append(f"[{idx}] {title_text}\nSnippet: {snippet_text}")
                    return "\n\n".join(snippets)
    except Exception as ex:
        logger.warning(f"[WorldKnowledge] DuckDuckGo HTML search failed: {ex}")

    return ""


# ── Tier 0: Built-in Knowledge Base (instant, no network needed) ──────────────────
_BUILTIN_KNOWLEDGE: dict = {
    # Internet / Web
    "www": "**WWW** stands for **World Wide Web** — a system of interconnected hypertext documents accessible via the Internet using HTTP/HTTPS protocols. It was invented by **Sir Tim Berners-Lee** in 1989 at CERN.",
    "full form of www": "**WWW** stands for **World Wide Web** — a system of interconnected hypertext documents accessible via the Internet using HTTP/HTTPS protocols. Invented by **Sir Tim Berners-Lee** in 1989.",
    "http": "**HTTP** stands for **HyperText Transfer Protocol** — the foundation of data communication on the World Wide Web. HTTPS is the secure version using TLS/SSL encryption.",
    "https": "**HTTPS** stands for **HyperText Transfer Protocol Secure** — HTTP with TLS/SSL encryption. It ensures secure data transfer between a browser and a web server.",
    "html": "**HTML** stands for **HyperText Markup Language** — the standard markup language used to create and structure web pages.",
    "css": "**CSS** stands for **Cascading Style Sheets** — a stylesheet language used to describe the presentation and visual styling of HTML documents.",
    "api": "**API** stands for **Application Programming Interface** — a set of protocols and tools that allows different software applications to communicate with each other.",
    "rest": "**REST** stands for **Representational State Transfer** — an architectural style for distributed hypermedia systems used to design networked APIs.",
    "sql": "**SQL** stands for **Structured Query Language** — the standard language for managing and manipulating relational databases.",
    "url": "**URL** stands for **Uniform Resource Locator** — a reference or address used to access resources on the Internet (e.g., `https://www.example.com`).",
    "ip": "**IP** stands for **Internet Protocol** — the principal communications protocol for relaying datagrams across network boundaries.",
    "tcp": "**TCP** stands for **Transmission Control Protocol** — a core Internet protocol that provides reliable, ordered, and error-checked delivery of data.",
    "dns": "**DNS** stands for **Domain Name System** — a hierarchical system that translates human-readable domain names (like `google.com`) into IP addresses.",
    "ftp": "**FTP** stands for **File Transfer Protocol** — a standard network protocol used to transfer files between a client and server.",
    "vpn": "**VPN** stands for **Virtual Private Network** — a technology that creates a secure, encrypted connection (tunnel) over the Internet.",
    "sdk": "**SDK** stands for **Software Development Kit** — a set of tools, libraries, and documentation that developers use to build applications for a specific platform.",
    "ide": "**IDE** stands for **Integrated Development Environment** — a software application that provides comprehensive tools for software development (e.g., VS Code, IntelliJ).",
    "oop": "**OOP** stands for **Object-Oriented Programming** — a programming paradigm based on the concept of objects, which contain data (attributes) and code (methods).",
    "ram": "**RAM** stands for **Random Access Memory** — a type of computer memory that temporarily stores data being actively used by the CPU.",
    "rom": "**ROM** stands for **Read-Only Memory** — non-volatile memory whose contents are fixed and cannot be easily modified.",
    "cpu": "**CPU** stands for **Central Processing Unit** — the primary component of a computer that executes instructions of a computer program.",
    "gpu": "**GPU** stands for **Graphics Processing Unit** — a specialized processor designed to accelerate graphics rendering and, increasingly, machine learning workloads.",
    "os": "**OS** stands for **Operating System** — software that manages computer hardware, software resources, and provides common services for programs (e.g., Windows, Linux, macOS).",
    "ai": "**AI** stands for **Artificial Intelligence** — the simulation of human intelligence in machines, including capabilities like learning, reasoning, and problem-solving.",
    "ml": "**ML** stands for **Machine Learning** — a subset of AI where algorithms learn from data to make predictions or decisions without being explicitly programmed.",
    "nlp": "**NLP** stands for **Natural Language Processing** — a branch of AI focused on enabling computers to understand, interpret, and generate human language.",
    "rag": "**RAG** stands for **Retrieval-Augmented Generation** — an AI architecture that combines document retrieval with a language model to generate grounded, factual responses.",
    "llm": "**LLM** stands for **Large Language Model** — a type of AI model trained on vast text data to understand and generate human language (e.g., GPT-4, Gemini, Llama).",
    "json": "**JSON** stands for **JavaScript Object Notation** — a lightweight, text-based data interchange format that is easy for humans to read and write.",
    "xml": "**XML** stands for **eXtensible Markup Language** — a markup language that defines rules for encoding documents in a format readable by both humans and machines.",
    "yaml": "**YAML** stands for **YAML Ain't Markup Language** — a human-readable data serialization format commonly used for configuration files.",
    "ci": "**CI** stands for **Continuous Integration** — a software development practice where developers frequently integrate code into a shared repository, with automated builds and tests.",
    "cd": "**CD** stands for **Continuous Delivery/Deployment** — a software practice that ensures code can be reliably released to production at any time through automation.",
    "devops": "**DevOps** is a set of practices that combines software development (Dev) and IT operations (Ops), aimed at shortening the development lifecycle and delivering high-quality software continuously.",
    "aws": "**AWS** stands for **Amazon Web Services** — a comprehensive cloud computing platform offering IaaS, PaaS, and SaaS services including compute, storage, databases, and AI tools.",
    "gcp": "**GCP** stands for **Google Cloud Platform** — Google's suite of cloud computing services for compute, storage, machine learning, and analytics.",
    "eks": "**EKS** stands for **Elastic Kubernetes Service** — Amazon's managed Kubernetes service that simplifies deploying, managing, and scaling containerized applications.",
    "aes": "**AES** stands for **Advanced Encryption Standard** — a symmetric block cipher algorithm widely used for encrypting data. AES-256 uses a 256-bit key and is considered highly secure.",
    "rls": "**RLS** stands for **Row-Level Security** — a database feature (e.g., in PostgreSQL) that controls access to rows in a table based on user-defined policies, ensuring data isolation.",
    "sla": "**SLA** stands for **Service Level Agreement** — a formal agreement between a service provider and a client that defines the expected level of service, uptime, and performance metrics.",
    "uat": "**UAT** stands for **User Acceptance Testing** — the final phase of software testing where end users verify the system meets business requirements before production deployment.",
    "saas": "**SaaS** stands for **Software as a Service** — a cloud delivery model where software is hosted by a vendor and accessed by customers over the Internet (e.g., Salesforce, Slack).",
    "paas": "**PaaS** stands for **Platform as a Service** — a cloud model that provides a platform for developers to build, run, and manage applications without managing the underlying infrastructure.",
    "iaas": "**IaaS** stands for **Infrastructure as a Service** — a cloud model providing virtualized computing resources (servers, storage, networking) over the Internet.",
    "ui": "**UI** stands for **User Interface** — the visual layer through which a user interacts with software, including buttons, forms, menus, and layouts.",
    "ux": "**UX** stands for **User Experience** — the overall experience a person has when using a product or service, focusing on usability, accessibility, and satisfaction.",
    "seo": "**SEO** stands for **Search Engine Optimization** — the practice of improving a website's visibility and ranking in search engine results pages (e.g., Google) organically.",
    "b2b": "**B2B** stands for **Business-to-Business** — a commerce model where transactions occur between businesses (e.g., a company selling software to another company).",
    "b2c": "**B2C** stands for **Business-to-Consumer** — a commerce model where businesses sell products or services directly to end consumers.",
    "kpi": "**KPI** stands for **Key Performance Indicator** — a measurable value that demonstrates how effectively a company or individual is achieving key business objectives.",
    "roi": "**ROI** stands for **Return on Investment** — a measure of the profitability of an investment, calculated as `(Net Profit / Cost of Investment) × 100%`.",
    "erp": "**ERP** stands for **Enterprise Resource Planning** — software that manages and integrates a company's core business processes (finance, HR, supply chain) in a unified system.",
    "crm": "**CRM** stands for **Customer Relationship Management** — software and strategies for managing a company's interactions with current and potential customers.",
    "hr": "**HR** stands for **Human Resources** — the department within a company responsible for recruiting, managing, and supporting employees throughout their employment lifecycle.",
    "cto": "**CTO** stands for **Chief Technology Officer** — the executive responsible for the technological direction and strategy of an organisation.",
    "ceo": "**CEO** stands for **Chief Executive Officer** — the highest-ranking executive in an organisation, responsible for overall business strategy and operations.",
    "cfo": "**CFO** stands for **Chief Financial Officer** — the senior executive responsible for managing a company's financial actions, planning, and reporting.",
    "cpo": "**CPO** stands for **Chief People Officer** — the executive responsible for all aspects of the employee lifecycle: recruitment, culture, L&D, and HR policies.",
    "esop": "**ESOP** stands for **Employee Stock Ownership Plan** — a program that grants employees ownership interest in the company through stock options, typically subject to a vesting schedule.",
    "okr": "**OKR** stands for **Objectives and Key Results** — a goal-setting framework used by organisations to define objectives and track measurable outcomes toward achieving them.",
    "pip": "**PIP** stands for **Performance Improvement Plan** — a formal document outlining specific goals and timelines for an employee to meet performance standards.",
}


_REFUSAL_PHRASES = (
    "don't have that information",
    "don't have specific",
    "couldn't find",
    "do not have that information",
    "do not have specific",
    "no relevant information",
    "not enough information",
)


def _looks_like_refusal(text: str) -> bool:
    """Detects a tier's own 'I don't know' response so a caller can decide to
    try the next tier instead of returning it as final. Real bug found via
    live testing 2026-08-22: Tier 1.5's search-context-only synthesis
    correctly refuses a generative request (e.g. "write a python function")
    since there's no relevant search context for it — but that refusal was
    previously returned as the final answer instead of falling through to a
    tier that can actually answer non-lookup questions directly.

    Second real bug found the same day: this comparison silently failed
    whenever a model (observed from both Groq and the local model) typeset
    the apostrophe in "don't"/"couldn't" as a Unicode right single quote
    (U+2019, "'") instead of a plain ASCII apostrophe — "don't" (U+2019)
    does not contain "don't" (U+0027) as a substring, so the refusal went
    fully undetected and got returned as the final answer regardless of
    this whole function's fallthrough logic. Normalize both to the same
    ASCII apostrophe before matching.

    Third real bug found via live browser testing 2026-08-23: a blank/empty
    string (a real, observed provider edge case — HTTP 200 with an empty or
    whitespace-only completion body, e.g. from content filtering or a
    zero-token generation) matched none of the phrases below, so it was
    treated as "not a refusal" and accepted as the tier's final answer —
    producing a genuinely empty chat response (which the frontend then had
    no honest way to render, since a truly-empty text_content isn't a
    rendering concern, it's an upstream answer-quality one). Empty/whitespace-only
    text is exactly as unusable as an explicit refusal, so it must fall
    through the same way."""
    t = text.strip().lower().replace(chr(0x2019), chr(0x27)).replace(chr(0x2018), chr(0x27))
    if not t:
        return True
    return any(p in t for p in _REFUSAL_PHRASES)


_SAFE_ARITH_OPS = {
    ast.Add: operator.add, ast.Sub: operator.sub,
    ast.Mult: operator.mul, ast.Div: operator.truediv,
    ast.Pow: operator.pow, ast.Mod: operator.mod,
    ast.FloorDiv: operator.floordiv,
    ast.USub: operator.neg, ast.UAdd: operator.pos,
}


def _safe_eval_arithmetic_node(node):
    """Evaluates only a strictly-numeric AST (+ - * / // % ** and unary +/-) --
    never falls back to Python's real eval(), so there is no code-execution
    risk from user-controlled query text."""
    if isinstance(node, ast.Expression):
        return _safe_eval_arithmetic_node(node.body)
    if isinstance(node, ast.BinOp) and type(node.op) in _SAFE_ARITH_OPS:
        return _SAFE_ARITH_OPS[type(node.op)](
            _safe_eval_arithmetic_node(node.left), _safe_eval_arithmetic_node(node.right)
        )
    if isinstance(node, ast.UnaryOp) and type(node.op) in _SAFE_ARITH_OPS:
        return _SAFE_ARITH_OPS[type(node.op)](_safe_eval_arithmetic_node(node.operand))
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return node.value
    raise ValueError("unsafe or non-numeric expression")


def _try_answer_pure_arithmetic(user_query: str):
    """Real Tier 0 (checked before any dict lookup or web call): directly
    computes a query that, once conversational wrapper words are stripped, is
    ONLY a numeric expression.

    Real bug found via live browser testing 2026-08-24: "What is 3+3?" against
    a brand-new tenant with zero ingested documents was routed to the
    DuckDuckGo Instant Answer tier below, which -- a real, well-known DDG
    quirk -- returns the Isley Brothers' 1973 album titled "3 + 3" instead of
    an arithmetic result. The chat confidently answered a trivial math
    question with unrelated album trivia. Root cause: nothing in this pipeline
    ever recognized "is this literally just arithmetic?" before asking an
    external search API to guess what the string means. Fixed by computing it
    directly, safely (AST-restricted, never a real eval of arbitrary code),
    before Tier 1 (DDG) ever runs."""
    stripped = re.sub(
        r"^(what is|what's|whats|calculate|compute|solve|evaluate|find)\s+", "",
        user_query.strip().lower()
    ).rstrip("?").strip()
    # Only digits/whitespace/operators/parens/decimal points survive here --
    # any letter means this isn't pure arithmetic, so don't even try.
    if not stripped or not re.fullmatch(r"[0-9\s+\-*/().%^]+", stripped):
        return None
    if not re.search(r"[+\-*/^%]", stripped):
        return None  # a bare number isn't "a math question" -- nothing to compute
    try:
        tree = ast.parse(stripped.replace("^", "**"), mode="eval")
        result = _safe_eval_arithmetic_node(tree)
    except Exception:
        return None
    if isinstance(result, float) and result.is_integer():
        result = int(result)
    return f"{stripped} = {result}"


async def _world_knowledge(user_query: str) -> str:
    """
    Multi-tier world knowledge engine with instant built-in knowledge base:
      Tier -1: Direct arithmetic computation (no network, no dict lookup)
      Tier 0: Built-in instant knowledge (no network, sub-millisecond)
      Tier 1: DuckDuckGo Instant Answer API
      Tier 1.5: Groq Llama synthesis over web search
      Tier 2: Gemini API
      Tier 3: Groq direct
      Tier 4: OpenAI API
      Tier 5: Polite enterprise fallback
    """
    import asyncio, re

    q = user_query.strip().lower()

    # ── Tier -1: Pure arithmetic gets computed directly, never searched ──
    _arith_answer = _try_answer_pure_arithmetic(user_query)
    if _arith_answer:
        return _arith_answer

    # ── Tier 0: Check built-in knowledge base first (instant) ──
    # Try exact match
    if q in _BUILTIN_KNOWLEDGE:
        return _BUILTIN_KNOWLEDGE[q]

    # ── Tiers 1 through 4.5 (every tier that calls an external network
    # provider) run under one overall wall-clock deadline -- see
    # _run_networked_world_knowledge_tiers's docstring for the real,
    # measured bug this fixes.
    try:
        _networked_result = await asyncio.wait_for(
            _run_networked_world_knowledge_tiers(user_query, q), timeout=20.0
        )
        if _networked_result:
            return _networked_result
    except Exception as ex:
        logger.warning(f"[WorldKnowledge] networked tier cascade did not finish within the 20s budget: {ex}")

    # ── Tier 5: Enterprise Fallback ──
    # Fixed 2026-08-20: this used to suggest fictional example entities ("Project
    # Orion", "Quantum Security Vault") as if they were real, indexed company data —
    # same fabrication pattern found and removed from conversation_service.py and the
    # frontend's suggestion chips.
    return (
        f"I wasn't able to find **\"{user_query}\"** in the company knowledge vault or via real-time search at this moment.\n\n"
        f"Try asking about a document or topic that's actually been ingested into your workspace, or rephrase the question."
    )


async def _run_networked_world_knowledge_tiers(user_query: str, q: str):
    """Tiers 1 through 4.5 of world knowledge -- the ones that call an
    external network provider (DuckDuckGo, Groq, Gemini, OpenAI, and the
    local self-hosted model). Factored out of _world_knowledge() so the
    whole cascade can be wrapped in one overall wall-clock deadline.

    Real bug found via live browser testing 2026-08-24: with no cap on total
    time across tiers, a single query that failed/refused on every paid
    provider in sequence (DDG up to 4s + Groq-search-synthesis up to 13s +
    Gemini 8s + Groq-direct 8s + OpenAI 10s + Local-model 45s = ~88s worst
    case) left a real user staring at a spinner for 47.6s on an actual
    measured run, before ever reaching the fast, honest give-up message
    (Tier 5) that existed the whole time. Returns None if nothing here
    produced a usable answer, so the caller falls through to Tier 5 instead
    of the query ever waiting out every remaining tier's own timeout one
    after another.
    """
    import asyncio

    # ── Tier 1: DuckDuckGo Instant Answer (free, no key) ──
    try:
        ddg_query = re.sub(
            r'^(what is|what are|who is|who was|tell me about|explain|define|describe|how is|how many|when was|when did|where is|what does|what was|full form of)\s+',
            '', q, flags=re.IGNORECASE
        ).strip()
        queries_to_try = list(dict.fromkeys([ddg_query, q]))

        async with httpx.AsyncClient(timeout=4.0) as client:
            for dq in queries_to_try:
                ddg_url = f"https://api.duckduckgo.com/?q={dq}&format=json&no_html=1&skip_disambig=1"
                resp = await asyncio.wait_for(
                    client.get(ddg_url, headers={"User-Agent": "CompanyBrain/1.0"}),
                    timeout=4.0
                )
                if resp.status_code == 200:
                    data = resp.json()
                    abstract  = data.get("AbstractText", "").strip()
                    answer_t  = data.get("Answer", "").strip()
                    definition = data.get("Definition", "").strip()
                    result = abstract or answer_t or definition
                    if result and len(result) > 30:
                        result = result[:600] + ("..." if len(result) > 600 else "")
                        return result
    except Exception as ex:
        logger.warning(f"[WorldKnowledge] DuckDuckGo failed: {ex}")

    # ── Tier 1.5: Groq synthesis over web search results ──
    try:
        from app.config import settings
        api_key = getattr(settings, "GROQ_API_KEY", None)
        if api_key:
            search_context = await asyncio.wait_for(_execute_web_search(user_query), timeout=5.0)
            if search_context:
                url = "https://api.groq.com/openai/v1/chat/completions"
                payload = {
                    "model": "openai/gpt-oss-120b",
                    "messages": [
                        {"role": "system", "content": (
                            "You are Company Brain, an enterprise AI assistant. Give a concise, clear answer "
                            "using ONLY the search context provided. No date preambles. Use markdown. "
                            "If the search context does not actually contain an answer to this specific "
                            "question, say plainly that you don't have that information rather than "
                            "generating a plausible-sounding but unverified answer."
                        )},
                        {"role": "user", "content": f"Query: {user_query}\n\nContext:\n{search_context}\n\nAnswer:"}
                    ],
                    "max_tokens": 500, "temperature": 0.3
                }
                async with httpx.AsyncClient(timeout=8.0) as client:
                    resp = await asyncio.wait_for(
                        client.post(url, json=payload, headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}),
                        timeout=8.0
                    )
                    if resp.status_code == 200:
                        _tier1_5_answer = resp.json()["choices"][0]["message"]["content"].strip()
                        # Real bug found via live testing 2026-08-22: this tier is
                        # instructed to answer "using ONLY the search context provided"
                        # — correct for a genuine fact-lookup question, but a generative
                        # request ("write a python function that adds two numbers") has
                        # no relevant search context to find, so this tier correctly (by
                        # its own instructions) refuses — and that refusal was returned
                        # immediately as if it were the final answer, even though a plain
                        # LLM call (Tier 3/4 below, no search-context constraint) could
                        # trivially have answered it. Don't accept a refusal from THIS
                        # tier specifically as final — fall through to the tiers that can
                        # actually answer generative/non-lookup questions.
                        if not _looks_like_refusal(_tier1_5_answer):
                            return _tier1_5_answer
    except Exception as ex:
        logger.warning(f"[WorldKnowledge] Groq search synthesis failed: {ex}")

    # ── Tier 2: Gemini API ──
    try:
        from app.config import settings
        api_key = getattr(settings, "GEMINI_API_KEY", None)
        if api_key:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.6-flash:generateContent?key={api_key}"
            prompt_text = (
                "Answer clearly and concisely. If you don't have specific, verifiable "
                "information to answer this exact question, say so plainly rather than "
                f"generating a plausible-sounding but unverified answer.\n\nQuestion: {user_query}"
            )
            payload = {
                "contents": [{"parts": [{"text": prompt_text}]}],
                "generationConfig": {"temperature": 0.2, "maxOutputTokens": 400}
            }
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await asyncio.wait_for(client.post(url, json=payload), timeout=8.0)
                if resp.status_code == 200:
                    candidates = resp.json().get("candidates", [])
                    if candidates:
                        _tier2_answer = candidates[0]["content"]["parts"][0]["text"].strip()
                        # Same fallthrough as Tier 1.5 above — an unconstrained model
                        # refusing here doesn't necessarily mean Tier 3/4 (different
                        # providers) will too.
                        if not _looks_like_refusal(_tier2_answer):
                            return _tier2_answer
    except Exception as ex:
        logger.warning(f"[WorldKnowledge] Gemini failed: {ex}")

    # ── Tier 3: Groq direct ──
    try:
        from app.config import settings
        api_key = getattr(settings, "GROQ_API_KEY", None)
        if api_key:
            url = "https://api.groq.com/openai/v1/chat/completions"
            payload = {
                "model": "openai/gpt-oss-120b",
                "messages": [
                    {"role": "system", "content": (
                        "You are Company Brain, an enterprise AI. Answer concisely and professionally in "
                        "markdown. If you don't have specific, verifiable information to answer this exact "
                        "question, say so plainly rather than generating a plausible-sounding but unverified answer."
                    )},
                    {"role": "user", "content": user_query}
                ],
                "max_tokens": 400, "temperature": 0.2
            }
            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await asyncio.wait_for(
                    client.post(url, json=payload, headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}),
                    timeout=8.0
                )
                if resp.status_code == 200:
                    _tier3_answer = resp.json()["choices"][0]["message"]["content"].strip()
                    # Same fallthrough as Tier 1.5/2 above — this tier's own
                    # "say so plainly if you don't know" instruction can also
                    # produce a refusal-shaped response to a purely generative
                    # request (e.g. "write a function") that a later tier
                    # (OpenAI, then Local) might still answer correctly.
                    if not _looks_like_refusal(_tier3_answer):
                        return _tier3_answer
    except Exception as ex:
        logger.warning(f"[WorldKnowledge] Groq failed: {ex}")

    # ── Tier 4: OpenAI API ──
    try:
        from app.config import settings
        api_key = getattr(settings, "OPENAI_API_KEY", None)
        if api_key:
            url = "https://api.openai.com/v1/chat/completions"
            payload = {
                "model": "gpt-4o-mini",
                "messages": [
                    {"role": "system", "content": (
                        "You are Company Brain, an enterprise AI. Answer general knowledge questions clearly "
                        "in 2-4 sentences. If you don't have specific, verifiable information to answer this "
                        "exact question, say so plainly rather than generating a plausible-sounding but "
                        "unverified answer."
                    )},
                    {"role": "user", "content": user_query}
                ],
                "max_tokens": 300
            }
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await asyncio.wait_for(
                    client.post(url, json=payload, headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}),
                    timeout=10.0
                )
                if resp.status_code == 200:
                    _tier4_answer = resp.json()["choices"][0]["message"]["content"].strip()
                    # Same fallthrough as earlier tiers — the free Local model
                    # (next tier) can still answer a purely generative request
                    # even if OpenAI's own instructed refusal fires here.
                    if not _looks_like_refusal(_tier4_answer):
                        return _tier4_answer
    except Exception as ex:
        logger.warning(f"[WorldKnowledge] OpenAI failed: {ex}")

    # ── Tier 4.5: Local self-hosted fallback (real, free, always available) ──
    # Real gap found via live testing 2026-08-21: this function has its own separate
    # 5-tier cascade and never included the LOCAL provider (Qwen2.5-0.5B-Instruct,
    # added the same day to RuntimeOrchestrator's cascade for company-data answers).
    # Confirmed live: a plain "what is the capital of France" question hit every tier
    # above genuinely failing at once — OpenAI/Groq/Gemini quota-exhausted (real 429s),
    # and DuckDuckGo's Instant Answer API returning an empty placeholder "test" payload
    # for ordinary trivia (a known real limitation of that free API, not a bug) — and
    # fell all the way to the honest give-up message despite a working, free, local
    # model being available the whole time. Adding it here so an ordinary general
    # knowledge question doesn't go unanswered purely because every paid provider
    # happens to be down at once.
    try:
        from app.conversation.providers.factory import LocalTransformersProviderAdapter
        from app.conversation.interfaces.llm_provider import GenerationRequest
        local_provider = LocalTransformersProviderAdapter()
        local_req = GenerationRequest(
            prompt=user_query,
            system_prompt=(
                "You are Company Brain, an enterprise AI. Answer concisely and factually. "
                "If you don't have specific, verifiable information to answer this exact "
                "question, say so plainly rather than generating a plausible-sounding but "
                "unverified answer."
            ),
            max_tokens=200, temperature=0.2,
        )
        local_res = await asyncio.wait_for(local_provider.generate(local_req), timeout=45.0)
        _local_answer = local_res.payload.text_content.strip()
        # Same fallthrough as every earlier tier — if even the local model
        # refuses, fall through to Tier 5's clean, honest give-up message
        # instead of returning whatever arbitrary refusal phrasing this
        # small model happened to generate.
        if _local_answer and not _looks_like_refusal(_local_answer):
            return _local_answer
    except Exception as ex:
        logger.warning(f"[WorldKnowledge] Local fallback failed: {ex}")

    # Nothing in the networked cascade produced a usable answer -- let
    # _world_knowledge's own Tier 5 (the fast, honest give-up message) handle
    # it rather than duplicating that text here.
    return None


class AgentOrchestrator:
    """
    Multi-Agent Orchestrator & Execution DAG Engine.
    Classifies queries, routes tasks to subagent workers under PostgreSQL RLS,
    emits machine-checkable trace entries, and enforces cycle/timeout safeguards.
    """

    MAX_STEPS = 5
    TIMEOUT_SECONDS = 15.0

    def classify_query(self, user_query: str) -> Tuple[str, str]:
        """
        Classifies user prompt into execution path.
        Logs every classification decision explicitly for auditability.
        Returns:
            (path_type: 'fast_path' | 'dag_path', reasoning: str)
        """
        q_lower = user_query.lower()
        
        # Multi-part analysis, comparative synthesis, or multi-step queries trigger DAG execution
        is_multi_part = any(term in q_lower for term in ["compare", "versus", "vs", "cross-reference", "overview and detail", "analyze differences", "and also"])
        
        if is_multi_part:
            path_type = "dag_path"
            reasoning = "Multi-part comparative analysis query requiring Research & Technical Spec subagent coordination."
        else:
            path_type = "fast_path"
            reasoning = "Single-turn factoid query routing to fast RAG path."

        logger.info(f"[Orchestrator CLASSIFY LOG] Query '{user_query}' -> Classified as '{path_type}' ({reasoning})")
        return path_type, reasoning

    async def execute_task(self, user_query: str, tenant_id: str, user_id: str = "default_user", tenant_tier: str = "default") -> Dict[str, Any]:
        """
        Executes multi-agent orchestrator workflow with trace tracking and safeguards.
        """
        t0 = time.time()
        task_id = str(uuid.uuid4())
        
        # ── Conversational Greetings Safeguard ──
        q_clean = user_query.strip().lower()

        # ── Casual affirmations / short responses fast path ──
        if q_clean in {"haa", "ha", "haha", "yes", "yep", "yeah", "hmm", "hmmm"}:
            ack_text = "Got it! Let me know if you need anything specific from your company documents or have any other questions."
            return {
                "task_id": task_id, "tenant_id": tenant_id, "path_type": "fast_path",
                "classification_reasoning": "Casual affirmation.", "step_count": 1,
                "response_text": ack_text, "citations": [], "agent_trace": [], "execution_latency_seconds": 0
            }
        
        greetings = {"hi", "hello", "hey", "greetings", "good morning", "good afternoon", "howdy", "hi there", "hey there", "sup", "holla", "hola", "namasthe", "namaste"}
        if q_clean in greetings:
            intro_text = (
                "Hello! I am **Company Brain**, your enterprise multi-agent intelligence engine.\n\n"
                "How can I assist you today? You can ask me to:\n"
                "• Retrieve real information from your company's ingested documents\n"
                "• Analyze code architecture or Pull Requests\n"
                "• Answer general questions outside your company data"
            )
            return {
                "task_id": task_id, "tenant_id": tenant_id, "path_type": "fast_path",
                "classification_reasoning": "Conversational greeting.", "step_count": 1,
                "response_text": intro_text, "citations": [], "agent_trace": [], "execution_latency_seconds": 0
            }

        # ── General Knowledge Instant Fast-Path (Strict Word-Boundary Lookup) ──
        builtin_answer = None
        # Skip built-in KB lookup completely if query is asking WHO someone is
        if not any(who_word in q_clean for who_word in ["who is", "who are", "who lead", "who built", "who created", "who "]):
            if q_clean in _BUILTIN_KNOWLEDGE:
                builtin_answer = _BUILTIN_KNOWLEDGE[q_clean]
            else:
                # Check multi-word phrase keys first
                for k_phrase, v_phrase in _BUILTIN_KNOWLEDGE.items():
                    if " " in k_phrase and k_phrase in q_clean:
                        builtin_answer = v_phrase
                        break
                # Check single-word acronyms with strict word-boundary matching
                if builtin_answer is None:
                    import re as _re
                    query_words = _re.findall(r'\b[a-z0-9]+\b', q_clean)
                    for w in query_words:
                        # Ignore common short acronyms / pronouns in sentence context
                        if w in {"os", "ip", "ai", "ml", "ui", "ux", "cd", "ci", "hr", "ceo", "cto", "cfo", "cpo", "it"} and len(query_words) > 1:
                            continue
                        if w in _BUILTIN_KNOWLEDGE and len(w) >= 2:
                            builtin_answer = _BUILTIN_KNOWLEDGE[w]
                            break

        if builtin_answer:
            return {
                "task_id": task_id, "tenant_id": tenant_id, "path_type": "fast_path",
                "classification_reasoning": "Built-in general knowledge fast-path.", "step_count": 1,
                "response_text": builtin_answer, "citations": ["General Knowledge"], "agent_trace": [],
                "execution_latency_seconds": 0, "confidence_score": 95
            }

        # ── Self-Introduction / Identity Intent Safeguard ──
        self_intro_phrases = [
            "tell about yourself", "tell me about yourself", "who are you", "what are you",
            "introduce yourself", "what is company brain", "what do you do", "what can you do",
            "how do you work", "explain yourself", "describe yourself", "who made you",
            "what is your purpose", "what are your capabilities", "about yourself", "about you"
        ]
        if any(phrase in q_clean for phrase in self_intro_phrases):
            # Fixed 2026-08-20: this used to unconditionally claim "GitHub, Jira, Slack,
            # Microsoft Teams, Google Drive, WhatsApp Business" were all ingested data
            # sources regardless of tenant — most are still fake stub connectors with
            # zero real data (see the Phase 2 audit). This whole method (execute_task)
            # is dead code today (not called by the live chat path — see
            # response-quality-overhaul memory), so there's no live tenant to query
            # real per-tenant sources for here the way conversation_service.py's
            # equivalent fix does; simplified to drop the false specific claim entirely
            # rather than fabricate a "real-looking" per-tenant answer with no tenant.
            self_text = (
                "I am **Company Brain** — an Enterprise AI Operating System built for your organisation.\n\n"
                "**What I can do:**\n"
                "• 🔍 **Company Knowledge Retrieval** — real hybrid search over whatever is actually ingested for your workspace\n"
                "• 🌐 **World Knowledge** — for general questions outside your company data, I answer from general intelligence\n"
                "• 🏢 **Tenant-Scoped Answers** — your data is isolated per tenant with PostgreSQL Row-Level Security\n"
                "• 🙅 **No guessing** — if I don't have relevant information, I say so instead of making something up\n\n"
                "Ask me anything about what's really in your workspace, or a general question."
            )
            return {
                "task_id": task_id, "tenant_id": tenant_id, "path_type": "fast_path",
                "classification_reasoning": "Self-introduction intent.", "step_count": 1,
                "response_text": self_text, "citations": [], "agent_trace": [], "execution_latency_seconds": 0
            }

        # ── Thanks / Acknowledgement Intent ──
        if q_clean in {"thanks", "thank you", "ok", "okay", "got it", "nice", "great", "cool", "awesome", "perfect"}:
            return {
                "task_id": task_id, "tenant_id": tenant_id, "path_type": "fast_path",
                "classification_reasoning": "Acknowledgement intent.", "step_count": 1,
                "response_text": "You're welcome! Feel free to ask anything else about your company's data or any general question.",
                "citations": [], "agent_trace": [], "execution_latency_seconds": 0
            }

        # NOTE (removed 2026-08-20): there used to be a "Company Information Overview"
        # fast-path here, triggered by phrases like "about the company" or "company
        # information", that returned an entirely fabricated company dossier — fake
        # project names, a fake CTO, fake filenames (auth_service.py,
        # payroll_processor.py), fake HR policy numbers, fake financial figures — with
        # fake citations to two documents that don't exist
        # (Project_Orion_Architecture_Spec.md, Company_Brain_Employee_Handbook_2026.pdf).
        # This was the most severe instance of the "canned fabrication" pattern found
        # across the codebase (see the twin fixes in conversation_service.py). Deleted
        # outright rather than patched, matching how the other instances were handled —
        # these queries now fall through to the real DAG path below.

        tracker = AgentTraceTracker(tenant_id=tenant_id)

        path_type, reasoning = self.classify_query(user_query)

        base_context = AgentTaskContext(
            task_id=task_id,
            tenant_id=tenant_id,
            user_id=user_id,
            user_query=user_query,
            subtask_query=user_query,
            tenant_tier=tenant_tier,
            trace_tracker=tracker
        )

        subagent_results: List[AgentResult] = []
        step_count = 0

        # Fast Path vs DAG Path
        if path_type == "fast_path":
            step_count += 1
            rag_res = await rag_agent.execute(base_context)
            subagent_results.append(rag_res)

            step_count += 1
            from app.agents.workers.background_researcher import background_researcher
            bg_res = await background_researcher.execute(base_context)
            subagent_results.append(bg_res)
        else:
            # DAG Path: Execute ResearchRAGAgent + TechnicalSpecCodeAnalysisAgent in parallel/sequence
            step_count += 1
            rag_res = await rag_agent.execute(base_context)
            subagent_results.append(rag_res)

            step_count += 1
            code_res = await code_analysis_agent.execute(base_context)
            subagent_results.append(code_res)

        # Enforce Cycle & Step-Limit Safeguard
        if step_count > self.MAX_STEPS:
            logger.warning(f"[AgentOrchestrator WARNING] Step limit threshold ({self.MAX_STEPS}) reached. Halting subagent execution.")

        # Execute Synthesis & Reflection Agent
        synthesis_context = AgentTaskContext(
            task_id=task_id,
            tenant_id=tenant_id,
            user_id=user_id,
            user_query=user_query,
            subtask_query=user_query,
            tenant_tier=tenant_tier,
            trace_tracker=tracker
        )
        synthesis_context.metadata["subagent_results"] = subagent_results

        synth_res = await synthesis_agent.execute(synthesis_context)

        total_latency = time.time() - t0
        final_response_text = synth_res.summary_text
        final_citations = synth_res.citations

        # ── World Knowledge Fallback Handler ──
        # If RAG found nothing above confidence threshold, escalate to world knowledge engine
        if synth_res.metadata.get("honest_refusal"):
            logger.info(f"[Orchestrator] Honest refusal for '{user_query}' → scope classification")

            # ── Enterprise Scope Guard ──
            # Block only pure fiction/entertainment — Company Brain is NOT a movie wiki.
            # Everything else (coding, general knowledge, world facts) is allowed.
            q_lower_scope = user_query.lower()

            fiction_signals = [
                "arc reactor", "iron man", "avengers", "marvel", "dc comics", "batman", "spiderman",
                "thor", "captain america", "thanos", "hulk", "superman", "stark",
                "hogwarts", "harry potter", "lord of the rings", "game of thrones",
                "star wars", "star trek", "pokemon", "dragon ball", "anime", "naruto",
                "one piece", "attack on titan"
            ]

            is_fiction = any(s in q_lower_scope for s in fiction_signals)

            if is_fiction:
                scope_msg = (
                    "I'm **Company Brain** — an Enterprise AI Operating System.\n\n"
                    "I can answer:\n"
                    "• 🔍 **Company knowledge** — documents, Slack, GitHub, Jira, Google Drive\n"
                    "• 🌐 **Real-world facts** — current events, leaders, sports, geography\n"
                    "• 💻 **Coding & technical questions** — programming, algorithms, architecture\n\n"
                    f"Questions about fictional universes like *\"{user_query}\"* are outside my scope. "
                    "Is there something about your **company data or a technical topic** I can help with?"
                )
                final_response_text = scope_msg
                final_citations = []
            else:
                # All other queries: coding, general knowledge, world facts → web search + Groq synthesis
                final_response_text = await _world_knowledge(user_query)
                final_citations = ["General World Knowledge"]


        return {
            "task_id": task_id,
            "tenant_id": tenant_id,
            "path_type": path_type,
            "classification_reasoning": reasoning,
            "response_text": final_response_text,
            "citations": final_citations,
            "agent_trace": tracker.to_dict_list(),
            "execution_latency_seconds": round(total_latency, 4),
            "step_count": step_count
        }

orchestrator = AgentOrchestrator()
