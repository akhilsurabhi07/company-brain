"""
Gateway Dependency Injection Container — Module 5 EKAP
======================================================
"""
from app.gateway.authentication.auth_handler import auth_handler
from app.gateway.authorization.policy_engine import policy_engine
from app.gateway.normalization.query_normalizer import query_normalizer
from app.gateway.clients.knowledge_retrieval_client import knowledge_retrieval_client
from app.gateway.services.search_service import search_service
from app.gateway.transformers.markdown_transformer import markdown_transformer
from app.gateway.transformers.agent_transformer import agent_transformer, dashboard_transformer
from app.gateway.streaming.sse_streamer import sse_streamer
from app.gateway.jobs.job_manager import job_manager
from app.gateway.audit.audit_logger import audit_logger, platform_analytics
from app.gateway.events.integration.event_contracts import event_bus

class GatewayContainer:
    def __init__(self):
        self.auth_handler = auth_handler
        self.policy_engine = policy_engine
        self.query_normalizer = query_normalizer
        self.retrieval_client = knowledge_retrieval_client
        self.search_service = search_service
        self.markdown_transformer = markdown_transformer
        self.agent_transformer = agent_transformer
        self.dashboard_transformer = dashboard_transformer
        self.sse_streamer = sse_streamer
        self.job_manager = job_manager
        self.audit_logger = audit_logger
        self.platform_analytics = platform_analytics
        self.event_bus = event_bus

gateway_container = GatewayContainer()
