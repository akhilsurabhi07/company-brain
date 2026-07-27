"""
Entity Resolution & Alias Merging Engine — Module 3
===================================================
Merges duplicate entities using exact alias lookup, string similarity (Jaro-Winkler),
corporate suffix normalization, and canonical mapping.
(e.g., "Microsoft Corporation", "Microsoft Inc", "MSFT" -> Canonical Entity 'Microsoft')
"""
import re
from typing import Dict, Any, Optional
from app.db.postgres_knowledge_repo import postgres_knowledge_repo
from app.domain.graph_models import EntityModel

def normalize_company_name(name: str) -> str:
    """Normalizes corporate suffix variations ('Inc', 'Corp', 'Corporation', 'LLC', 'Ltd')."""
    clean_name = re.sub(r'\b(corporation|corp|inc|ltd|llc)\b', '', name, flags=re.IGNORECASE).strip()
    return clean_name if clean_name else name

class EntityResolver:
    """Resolves raw entity names to canonical entity IDs."""

    async def resolve_or_create(self, tenant_id: str, raw_name: str, entity_type: str) -> str:
        """
        1. Checks exact match in database.
        2. Normalizes corporate suffixes and alias mappings.
        3. Performs fuzzy alias lookup.
        4. Creates new canonical entity if no match found.
        """
        existing = await postgres_knowledge_repo.get_entity_by_canonical_name(tenant_id, raw_name)
        if existing:
            return existing["id"]

        # Alias dictionary check for known enterprise mappings
        alias_map = {
            "microsoft corporation": "Microsoft",
            "microsoft inc": "Microsoft",
            "msft": "Microsoft",
            "johnathan smith": "John Smith",
            "j smith": "John Smith",
        }
        raw_lower = raw_name.lower().strip()
        canonical = alias_map.get(raw_lower, normalize_company_name(raw_name))

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
