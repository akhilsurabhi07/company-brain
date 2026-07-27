"""
Plugin SDK & Extractor Interfaces — Module 3
===========================================
Defines the Plugin SDK for domain extractors.
"""
from abc import ABC, abstractmethod
from typing import List, Dict, Any
from app.domain.graph_models import EntityModel, RelationshipModel, FactModel

class ExtractorPluginInterface(ABC):
    """Abstract interface for domain extraction plugins."""

    @property
    @abstractmethod
    def plugin_name(self) -> str:
        """Name of the extractor plugin."""
        pass

    @abstractmethod
    def extract_entities(self, tenant_id: str, text_content: str) -> List[EntityModel]:
        """Extract domain entities from text content."""
        pass

    @abstractmethod
    def extract_facts(self, tenant_id: str, text_content: str) -> List[FactModel]:
        """Extract structured business facts from text content."""
        pass
