import pytest
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
async def test_connector_resource_extraction():
    slack_conn = SlackConnector()
    token = await slack_conn.authenticate("tenant_123", "mock_code")
    resources, next_cursor = await slack_conn.list_resources(token)
    
    assert len(resources) == 1
    res = resources[0]
    assert res.source_app == "slack"
    assert res.resource_category == "chat_message"

    nodes, edges = slack_conn.extract_graph(res)
    assert len(nodes) >= 2
    assert len(edges) >= 1
