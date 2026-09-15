"""
Module 6B — Enterprise Experience Layer (EXL) UI Router
=========================================================
Serves the standalone EXL Web Application independently at `/m6b/`.
Strictly decoupled from backend intelligence modules 1–6A.
"""

import os
from fastapi import APIRouter
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles

router = APIRouter(prefix="/m6b", tags=["Module 6B - EXL Frontend UI"])

FRONTEND_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "frontend"))

@router.get("/", response_class=HTMLResponse)
@router.get("/index.html", response_class=HTMLResponse)
async def serve_exl_index():
    """Serves the Module 6B Enterprise Experience Layer main SPA."""
    index_path = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return HTMLResponse("<h2>Module 6B EXL Interface Initializing...</h2>")


@router.get("/theme.css")
async def serve_theme_css():
    """Serves the Module 6B Design System theme CSS file."""
    css_path = os.path.join(FRONTEND_DIR, "theme.css")
    return FileResponse(css_path, media_type="text/css")

@router.get("/app.js")
async def serve_app_js():
    """Serves the Module 6B Application Controller JavaScript file."""
    js_path = os.path.join(FRONTEND_DIR, "app.js")
    return FileResponse(js_path, media_type="application/javascript")


@router.get("/health")
async def module6b_health():
    """Health-check endpoint — returns version and available model list.

    Real bug found via live browser testing 2026-08-22 (same session as the
    frontend model-dropdown fix): this list was fabricated ("5.6 Sol",
    "Gemini 1.5 Pro" don't exist as real model names) and had already drifted
    out of sync with the real, corrected model list in frontend/app.js
    (models[]) by the time it was found. Kept in sync with that array by
    hand since one is JS and the other Python — there's no single source of
    truth to import from across that boundary."""
    return {
        "status": "ok",
        "module": "6B",
        "version": "EXL v6B",
        "api_bridge": "/api/v6a/chat/turn",
        "available_models": [
            {"name": "Auto (Recommended)",      "badge": "Default", "provider": ""},
            {"name": "OpenAI",                  "badge": "Cloud",   "provider": "openai"},
            {"name": "Groq",                    "badge": "Cloud",   "provider": "groq"},
            {"name": "Gemini",                  "badge": "Cloud",   "provider": "gemini"},
            {"name": "Anthropic",               "badge": "Cloud",   "provider": "anthropic"},
            {"name": "HuggingFace",              "badge": "Cloud",   "provider": "huggingface"},
            {"name": "Local (Free, Offline)",   "badge": "Offline", "provider": "local"},
            {"name": "Mock (Offline Test Stub)", "badge": "Test",    "provider": "mock"},
        ],
    }
