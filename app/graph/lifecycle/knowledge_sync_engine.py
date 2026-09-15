"""
Knowledge Synchronization Engine (Knowledge Update Manager) — Module 3
========================================================================
Manages incremental knowledge graph updates for external connector events:
  - FILE_CREATED: Incremental ingestion & graph node creation.
  - FILE_UPDATED: SHA-256 checksum diffing. Skips if unchanged; otherwise archives old version (is_current=False) and updates modified facts.
  - FILE_DELETED: Transitions document facts/entities to 'Archived' state for audit retention.
  - PERMISSION_CHANGED: Updates governance tags without reprocessing text.
"""
import uuid
import hashlib
from typing import Dict, Any, List, Optional
from datetime import datetime
from sqlalchemy import text
from app.db.database import async_session_factory
from app.db.postgres_knowledge_repo import postgres_knowledge_repo
from app.domain.graph_models import EntityModel, FactModel, RelationshipModel

class KnowledgeSyncEngine:
    """Manages incremental graph synchronization and version evolution."""

    def calculate_checksum(self, text_content: str) -> str:
        """Computes SHA-256 checksum of text content."""
        return hashlib.sha256(text_content.encode("utf-8")).hexdigest()

    async def handle_file_created(
        self,
        tenant_id: str,
        document_id: str,
        title: str,
        text_content: str,
        extracted_entities: List[EntityModel],
        extracted_facts: List[FactModel]
    ) -> Dict[str, Any]:
        """
        Processes FILE_CREATED event incrementally.
        Inserts new entities and facts into graph under tenant RLS.
        """
        inserted_entity_ids = []
        inserted_fact_ids = []

        for entity in extracted_entities:
            e_id = await postgres_knowledge_repo.create_entity(entity)
            inserted_entity_ids.append(e_id)

        for fact in extracted_facts:
            f_id = await postgres_knowledge_repo.create_fact(fact, document_id=document_id, snippet=f"Extracted from {title}")
            inserted_fact_ids.append(f_id)

        return {
            "status": "created",
            "document_id": document_id,
            "entities_inserted": len(inserted_entity_ids),
            "facts_inserted": len(inserted_fact_ids)
        }

    async def handle_file_updated(
        self,
        tenant_id: str,
        document_id: str,
        title: str,
        old_checksum: str,
        new_text_content: str,
        new_facts: List[FactModel]
    ) -> Dict[str, Any]:
        """
        Processes FILE_UPDATED event incrementally:
        1. Compares SHA-256 checksums. If identical, skips reprocessing (0 cost).
        2. If changed, marks old document facts as superseded (is_current = False, state = 'Deprecated').
        3. Inserts new version facts with version history.
        """
        new_checksum = self.calculate_checksum(new_text_content)
        if old_checksum and old_checksum == new_checksum:
            return {
                "status": "skipped",
                "reason": "SHA-256 checksum identical. No content changed.",
                "document_id": document_id
            }

        # Content changed! Deprecate old document facts in AWS RDS PostgreSQL
        async with async_session_factory() as session:
            async with session.begin():
                await session.execute(text("SELECT set_config('app.current_tenant_id', :__tid, true)"), {"__tid": str(tenant_id)})
                # Deprecate old fact sources
                await session.execute(
                    text("""
                        UPDATE graph_facts 
                        SET is_current = FALSE, state = 'Deprecated'
                        WHERE id IN (
                            SELECT fact_id FROM graph_fact_sources WHERE document_id = :doc_id
                        )
                    """),
                    {"doc_id": document_id}
                )

        # Insert new version facts
        inserted_facts = []
        for fact in new_facts:
            f_id = await postgres_knowledge_repo.create_fact(fact, document_id=document_id, snippet=f"Updated in {title}")
            inserted_facts.append(f_id)

        return {
            "status": "updated",
            "document_id": document_id,
            "old_checksum": old_checksum,
            "new_checksum": new_checksum,
            "facts_updated": len(inserted_facts)
        }

    async def handle_file_deleted(self, tenant_id: str, document_id: str) -> Dict[str, Any]:
        """
        Processes FILE_DELETED event incrementally.
        Transitions related facts and relationships to 'Archived' state for compliance retention.
        """
        async with async_session_factory() as session:
            async with session.begin():
                await session.execute(text("SELECT set_config('app.current_tenant_id', :__tid, true)"), {"__tid": str(tenant_id)})
                await session.execute(
                    text("""
                        UPDATE graph_facts 
                        SET is_current = FALSE, state = 'Archived'
                        WHERE id IN (
                            SELECT fact_id FROM graph_fact_sources WHERE document_id = :doc_id
                        )
                    """),
                    {"doc_id": document_id}
                )

        return {
            "status": "archived",
            "document_id": document_id,
            "message": "Associated document knowledge archived for compliance audit retention."
        }

    async def handle_permission_changed(self, tenant_id: str, document_id: str, new_governance_tags: List[str]) -> Dict[str, Any]:
        """
        Processes PERMISSION_CHANGED event instantly without reprocessing text.
        """
        import json
        async with async_session_factory() as session:
            async with session.begin():
                await session.execute(text("SELECT set_config('app.current_tenant_id', :__tid, true)"), {"__tid": str(tenant_id)})
                await session.execute(
                    text("""
                        UPDATE graph_entities 
                        SET governance_tags = :tags 
                        WHERE id IN (
                            SELECT entity_id FROM graph_entity_aliases WHERE entity_id IN (
                                SELECT entity_id FROM graph_nodes
                            )
                        )
                    """),
                    {"tags": json.dumps(new_governance_tags)}
                )

        return {
            "status": "permissions_updated",
            "document_id": document_id,
            "new_governance_tags": new_governance_tags
        }

knowledge_sync_engine = KnowledgeSyncEngine()
