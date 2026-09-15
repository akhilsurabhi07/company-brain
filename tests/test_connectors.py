import pytest
import respx
import httpx
from app.connectors import ConnectorRegistry
from app.connectors.slack import SlackConnector
from app.connectors.google_drive import GoogleDriveConnector
from app.connectors.github import GitHubConnector
from app.connectors.jira import JiraConnector

def test_connector_registry_autodiscovery():
    registered_apps = ConnectorRegistry.list_registered_apps()
    assert "slack" in registered_apps
    assert "google_drive" in registered_apps
    assert "github" in registered_apps
    assert "jira" in registered_apps

def test_get_connector_instances():
    slack_conn = ConnectorRegistry.get_connector("slack")
    assert isinstance(slack_conn, SlackConnector)
    assert slack_conn.source_app == "slack"

    drive_conn = ConnectorRegistry.get_connector("google_drive")
    assert isinstance(drive_conn, GoogleDriveConnector)
    assert drive_conn.source_app == "google_drive"

@pytest.mark.asyncio
@respx.mock
async def test_connector_resource_extraction():
    """Updated 2026-08-20: SlackConnector is now a real Web API connector (see
    app/connectors/slack.py) — it correctly rejects a fake 'mock_code' credential
    instead of returning a fake resource, matching the same real-or-reject standard
    already used by GitHubConnector. Real behavior is now exercised with the network
    boundary mocked via respx (real request shapes, realistic Slack response schema),
    not by asserting against fabricated in-memory data the old test relied on."""
    respx.post("https://slack.com/api/auth.test").mock(
        return_value=httpx.Response(200, json={"ok": True, "team_id": "T_TEST", "team": "Test Workspace"})
    )
    respx.get("https://slack.com/api/conversations.list").mock(
        return_value=httpx.Response(200, json={
            "ok": True,
            "channels": [{"id": "C_GENERAL", "name": "general", "is_member": True}],
            "response_metadata": {"next_cursor": ""},
        })
    )
    respx.get("https://slack.com/api/conversations.history").mock(
        return_value=httpx.Response(200, json={
            "ok": True,
            "messages": [{"type": "message", "user": "U12345", "text": "Hey team, let's review the Phase 1 architecture plan.", "ts": "1700000000.000100"}],
            "response_metadata": {"next_cursor": ""},
        })
    )

    slack_conn = SlackConnector()
    token = await slack_conn.authenticate("tenant_123", "xoxb-test-token")
    resources, next_cursor = await slack_conn.list_resources(token)

    assert len(resources) == 1
    res = resources[0]
    assert res.source_app == "slack"
    assert res.resource_category == "chat_message"
    assert res.resource_group_id == "C_GENERAL"

    nodes, edges = slack_conn.extract_graph(res)
    assert len(nodes) >= 2
    assert len(edges) >= 1


@pytest.mark.asyncio
async def test_connector_authenticate_rejects_fake_credential():
    """A bare 'mock_code' string (the old fake stub's accepted input) must now be
    rejected outright — no connector should silently treat a non-credential as valid."""
    slack_conn = SlackConnector()
    with pytest.raises(ValueError):
        await slack_conn.authenticate("tenant_123", "mock_code")
