"""External World Knowledge Search Engine — Zero-config live web & encyclopedia search.

Fetches live real-time external world knowledge from Wikipedia REST API,
DuckDuckGo Instant Answers, and live web search parsing without requiring any paid API keys.
Includes query preprocessing for common typos and pronoun coreference resolution across conversation turns.
"""

import httpx
import urllib.parse
import re
from typing import Optional, Dict, Any, List


class ExternalKnowledgeEngine:
    """Searches live external web & world knowledge repositories."""

    HEADERS = {"User-Agent": "CompanyBrain/1.0 (Enterprise AI Operating System)"}
    WEB_HEADERS = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    TYPO_MAP = {
        r"\bcompnay\b": "company",
        r"\bcloacks\b": "clocks",
        r"\bchack\b": "check",
        r"\bproerly\b": "properly",
        r"\banwsers\b": "answers",
        r"\bknowlegede\b": "knowledge",
        r"\boutsaid\b": "outside",
        r"\bdifferents\b": "difference",
        r"\bbetewent\b": "between",
    }

    @classmethod
    def clean_query(cls, query: str) -> str:
        cleaned = query.strip()
        for pattern, replacement in cls.TYPO_MAP.items():
            cleaned = re.sub(pattern, replacement, cleaned, flags=re.IGNORECASE)
        return cleaned

    @classmethod
    def resolve_coreference(cls, query: str, history: Optional[List[Dict[str, Any]]] = None) -> str:
        q_lower = query.strip().lower()
        followup_markers = [
            "that college", "this college", "the college", "that university",
            "that company", "this company", "the company",
            "that person", "him", "her", "who is he", "who is she",
            "that topic", "that place", "that city", "that institution",
            "about it", "tell more", "give more", "explain more", "more details"
        ]
        
        if any(marker in q_lower for marker in followup_markers) and history:
            for item in reversed(history):
                role = item.get("role") if isinstance(item, dict) else getattr(item, "role", "")
                content = item.get("content") if isinstance(item, dict) else getattr(item, "content", "")
                if role == "user" and content:
                    # Strip leading question preambles to extract core entity
                    topic = re.sub(
                        r"^(tell about|what is|give info about|who is|tell me about|information about|give information about|details about)\s+",
                        "",
                        content,
                        flags=re.IGNORECASE
                    ).strip()
                    if topic and len(topic) > 3 and topic.lower() not in ["it", "that", "this", "that college"]:
                        return f"{topic} {query}"
        return query

    @classmethod
    async def fetch_world_knowledge(cls, query: str, history: Optional[List[Dict[str, Any]]] = None) -> Optional[Dict[str, Any]]:
        """Search Wikipedia, DuckDuckGo API, and Live Web Search for real world knowledge."""
        resolved_query = cls.resolve_coreference(query, history=history)
        cleaned_query = cls.clean_query(resolved_query)
        if not cleaned_query:
            return None

        # Special query transformations for companies & entities
        search_term = cleaned_query
        p_lower = cleaned_query.lower()

        if "apple" in p_lower and ("company" in p_lower or "data" in p_lower or "inc" in p_lower):
            search_term = "Apple Inc."
        elif "microsoft" in p_lower and ("company" in p_lower or "data" in p_lower):
            search_term = "Microsoft Corporation"
        elif "google" in p_lower and ("company" in p_lower or "data" in p_lower):
            search_term = "Alphabet Inc."
        elif "tesla" in p_lower and ("company" in p_lower or "data" in p_lower):
            search_term = "Tesla Inc."

        # 1. Try Wikipedia Summary API
        try:
            wiki_title = urllib.parse.quote(search_term.replace(" ", "_"))
            wiki_url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{wiki_title}"
            
            async with httpx.AsyncClient(timeout=4.0) as client:
                resp = await client.get(wiki_url, headers=cls.HEADERS)
                if resp.status_code == 200:
                    data = resp.json()
                    extract = data.get("extract", "")
                    title = data.get("title", search_term)
                    if extract and len(extract) > 40:
                        return {
                            "source": f"Wikipedia ({title})",
                            "title": title,
                            "summary": extract,
                            "url": data.get("content_urls", {}).get("desktop", {}).get("page", ""),
                        }
        except Exception:
            pass

        # 2. Try DuckDuckGo Instant Answer API
        try:
            ddg_url = f"https://api.duckduckgo.com/?q={urllib.parse.quote(search_term)}&format=json"
            async with httpx.AsyncClient(timeout=4.0) as client:
                resp = await client.get(ddg_url, headers=cls.HEADERS)
                if resp.status_code == 200:
                    data = resp.json()
                    abstract = data.get("AbstractText", "")
                    heading = data.get("Heading", search_term)
                    if abstract and len(abstract) > 30:
                        return {
                            "source": f"DuckDuckGo Index ({heading})",
                            "title": heading,
                            "summary": abstract,
                            "url": data.get("AbstractURL", ""),
                        }
        except Exception:
            pass

        # 3. Live Web Search Scraping for Natural Questions & Coreference Resolved Queries
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.post(
                    "https://html.duckduckgo.com/html/",
                    data={"q": cleaned_query},
                    headers=cls.WEB_HEADERS
                )
                if resp.status_code == 200:
                    from bs4 import BeautifulSoup
                    soup = BeautifulSoup(resp.text, "html.parser")
                    snippets = []
                    for a in soup.find_all("a", class_="result__snippet"):
                        text_val = a.get_text().strip()
                        if text_val and len(text_val) > 20 and text_val not in snippets:
                            snippets.append(text_val)
                        if len(snippets) >= 3:
                            break
                    if snippets:
                        combined_summary = "\n\n".join(snippets)
                        return {
                            "source": "Live Web Search (DuckDuckGo)",
                            "title": query.strip(),
                            "summary": combined_summary,
                            "url": f"https://duckduckgo.com/?q={urllib.parse.quote(cleaned_query)}",
                        }
        except Exception:
            pass

        return None
