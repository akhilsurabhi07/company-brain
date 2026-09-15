"""
Module 6B — Enterprise Experience Layer (EXL) UI Test Suite
============================================================
Verifies standalone frontend routes, asset serving, and API router mounting.
"""

import pytest
from fastapi.testclient import TestClient
from app.main import app
from tests.conftest import auth_headers_for

client = TestClient(app)


def test_module6b_index_serving():
    """Verifies that Module 6B HTML index SPA is served at /m6b/."""
    response = client.get("/m6b/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Company Brain" in response.text


def test_module6b_theme_css_serving():
    """Verifies that Module 6B CSS design system is served at /m6b/theme.css."""
    response = client.get("/m6b/theme.css")
    assert response.status_code == 200
    assert "text/css" in response.headers["content-type"]
    assert "--accent:" in response.text


def test_module6b_app_js_serving():
    """Verifies that Module 6B Application JavaScript controller is served at /m6b/app.js."""
    response = client.get("/m6b/app.js")
    assert response.status_code == 200
    assert "javascript" in response.headers["content-type"]
    assert "DOMContentLoaded" in response.text


def test_module6b_health_endpoint():
    """Verifies that the Module 6B /health endpoint returns expected JSON schema."""
    response = client.get("/m6b/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["module"] == "6B"
    assert "available_models" in data
    assert isinstance(data["available_models"], list)
    assert len(data["available_models"]) >= 1


def test_v6a_chat_bridge_rejects_empty_query():
    """Verifies the /api/v6a/chat/turn bridge endpoint validates required fields."""
    tenant_id = "tenant_enterprise_01"
    response = client.post(
        "/api/v6a/chat/turn",
        json={
            "tenant_id": tenant_id,
            "user_id": "user_surabhi",
            "session_id": None,
            # user_query intentionally omitted to trigger 422
        },
        headers=auth_headers_for(tenant_id),
    )
    assert response.status_code == 422   # Unprocessable Entity — user_query is required
