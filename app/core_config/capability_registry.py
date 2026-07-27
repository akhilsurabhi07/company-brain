"""
Capability Registry — Module 3
==============================
Provides a dynamic registry for platform feature flags, enterprise licensing,
and active tenant capabilities.
"""
from typing import Dict, Any

class CapabilityRegistry:
    def __init__(self):
        self._global_capabilities = {
            "entity_extraction": True,
            "relationship_extraction": True,
            "fact_extraction": True,
            "entity_resolution": True,
            "conflict_detection": True,
            "knowledge_reasoning": True,
            "workflow_discovery": True,
            "impact_analysis": True,
            "decision_intelligence": True,
            "action_recommendations": True,
            "organizational_health": True,
            "evaluation_framework": True,
        }

    def is_capability_enabled(self, tenant_id: str, capability_name: str) -> bool:
        """Return whether a capability is enabled for a given tenant."""
        return self._global_capabilities.get(capability_name, False)

    def get_tenant_capabilities(self, tenant_id: str) -> Dict[str, bool]:
        """Return all active capabilities for a given tenant."""
        return dict(self._global_capabilities)

capability_registry = CapabilityRegistry()
