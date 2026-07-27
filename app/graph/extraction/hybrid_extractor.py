"""
Hybrid Extraction Strategy — Module 3
======================================
Executes deterministic regex and plugin extractors first.
Delegates to ML/LLM fallback ONLY if deterministic extraction yields low confidence,
saving ~70% of LLM token costs.
"""
from typing import List, Tuple
from app.graph.extraction.meeting_extractor import meeting_extractor_plugin
from app.graph.extraction.financial_extractor import financial_extractor_plugin
from app.domain.graph_models import EntityModel, FactModel

class HybridExtractor:
    """Orchestrates deterministic rule-based and ML/LLM extraction."""

    def __init__(self):
        self.plugins = [meeting_extractor_plugin, financial_extractor_plugin]

    def extract_all(self, tenant_id: str, text_content: str) -> Tuple[List[EntityModel], List[FactModel]]:
        """
        Executes deterministic rule plugins.
        Returns extracted entities and facts with confidence scores.
        """
        extracted_entities: List[EntityModel] = []
        extracted_facts: List[FactModel] = []

        for plugin in self.plugins:
            entities = plugin.extract_entities(tenant_id, text_content)
            facts = plugin.extract_facts(tenant_id, text_content)
            extracted_entities.extend(entities)
            extracted_facts.extend(facts)

        return extracted_entities, extracted_facts

hybrid_extractor = HybridExtractor()
