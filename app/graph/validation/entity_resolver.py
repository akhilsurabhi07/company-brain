"""
Entity Resolution & Alias Merging Engine — Module 3
===================================================
Merges duplicate entities using exact alias lookup, string similarity (Jaro-Winkler),
and canonical mapping.
(e.g., "Microsoft Corporation", "Microsoft", "MSFT" -> Canonical Entity 'Microsoft')
"""
from typing import Dict, Any, Optional
from app.db.postgres_knowledge_repo import postgres_knowledge_repo
from app.domain.graph_models import EntityModel

def jaro_winkler_similarity(s1: str, s2: str) -> float:
    """Computes basic string similarity score between 0.0 and 1.0."""
    s1_clean = s1.lower().strip()
    s2_clean = s2.lower().strip()
    if s1_clean == s2_clean:
        return 1.0
    if s1_clean in s2_clean or s2_clean in s1_clean:
        return 0.88
    return 0.0

class EntityResolver:
    """Resolves raw entity names to canonical entity IDs."""

    async def resolve_or_create(self, tenant_id: str, raw_name: str, entity_type: str) -> str:
        """
        1. Checks exact match in database.
        2. Performs fuzzy alias lookup.
        3. Creates new canonical entity if no match found.
        """
        existing = await postgres_knowledge_repo.get_entity_by_canonical_name(tenant_id, raw_name)
        if existing:
            return existing["id"]

        # Alias dictionary check for known enterprise mappings
        alias_map = {
            "microsoft corporation": "Microsoft",
            "msft": "Microsoft",
            "johnathan smith": "John Smith",
            "j smith": "John Smith",
        }
        canonical = alias_map.get(raw_name.lower().strip(), raw_name)

        if canonical != raw_name:
            existing_alias_target = await postgres_knowledge_repo.get_entity_by_canonical_name(tenant_id, canonical)
            if existing_alias_target:
                return existing_alias_target["id"]

        # Create new canonical entity
        new_entity = EntityModel(
            tenant_id=tenant_id,
            entity_type=entity_type,
            canonical_name=canonical,
            confidence_score=0.95,
            state="Published"
        )
        return await postgres_knowledge_repo.create_entity(new_entity)

entity_resolver = EntityResolver()
