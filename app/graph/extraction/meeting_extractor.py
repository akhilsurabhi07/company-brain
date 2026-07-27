"""
Meeting & Decision Extractor Plugin — Module 3
==============================================
Extracts Meeting entities, Tasks, and Decisions from meeting minutes and chat logs.
"""
import re
from typing import List
from app.graph.interfaces.plugin_sdk import ExtractorPluginInterface
from app.domain.graph_models import EntityModel, FactModel

class MeetingExtractorPlugin(ExtractorPluginInterface):
    @property
    def plugin_name(self) -> str:
        return "meeting_decision_extractor"

    def extract_entities(self, tenant_id: str, text_content: str) -> List[EntityModel]:
        entities = []
        # Match Project patterns
        projects = re.findall(r'Project\s+([A-Z][a-zA-Z0-9_-]+)', text_content)
        for proj in set(projects):
            entities.append(EntityModel(
                tenant_id=tenant_id,
                entity_type="Project",
                canonical_name=f"Project {proj}",
                confidence_score=0.95,
                attributes={"source_plugin": self.plugin_name}
            ))

        # Match Persons
        persons = re.findall(r'(?:Owner|Assigned to|Lead):\s*([A-Z][a-z]+\s+[A-Z][a-z]+)', text_content)
        for person in set(persons):
            entities.append(EntityModel(
                tenant_id=tenant_id,
                entity_type="Person",
                canonical_name=person.strip(),
                confidence_score=0.90,
                attributes={"source_plugin": self.plugin_name}
            ))
        return entities

    def extract_facts(self, tenant_id: str, text_content: str) -> List[FactModel]:
        facts = []
        # Match Decisions
        decision_matches = re.findall(r'Decision:\s*([^\.\n]+)', text_content, re.IGNORECASE)
        for dec in decision_matches:
            facts.append(FactModel(
                tenant_id=tenant_id,
                fact_type="Decision",
                metric_name="Executive Decision",
                value=dec.strip(),
                confidence_score=0.92,
                source_authority=0.85
            ))
        return facts

meeting_extractor_plugin = MeetingExtractorPlugin()
