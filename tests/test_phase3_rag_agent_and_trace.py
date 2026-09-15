import sys
import uuid
import unittest
import asyncio
from unittest.mock import patch, MagicMock

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from app.agents.agent_trace import AgentTraceEntry, AgentTraceTracker
from app.agents.interfaces.agent_interfaces import AgentTaskContext
from app.agents.workers.rag_agent import rag_agent

class TestPhase3RAGAgentAndTrace(unittest.IsolatedAsyncioTestCase):

    def test_01_trace_entry_query_hash_determinism(self):
        """Test 1: Verify deterministic SHA-256 query hash computation."""
        sql_query = "SELECT * FROM document_chunks WHERE tenant_id = :tenant_id"
        params = {"tenant_id": "tenant_12345", "top_k": 5}

        hash1 = AgentTraceEntry.compute_query_hash(sql_query, params)
        hash2 = AgentTraceEntry.compute_query_hash(sql_query, params)

        self.assertEqual(hash1, hash2, "Query hash MUST be deterministic.")
        self.assertEqual(len(hash1), 64, "SHA-256 hash string length MUST be 64 characters.")
        print(f"  [1.1] Generated SHA-256 Query Hash: {hash1[:16]}...")
        print("[PASS] Test 01: Agent Trace SHA-256 Query Hash Determinism Verified.")

    def test_02_adversarial_trace_hash_mismatch_verification(self):
        """Test 2: Adversarial Check — Confirm test fails if a fake/hardcoded hash is supplied."""
        sql_query = "SELECT * FROM document_chunks WHERE tenant_id = :tenant_id"
        params = {"tenant_id": "tenant_12345", "top_k": 5}
        
        real_hash = AgentTraceEntry.compute_query_hash(sql_query, params)
        fake_hash = "fake_hardcoded_hash_1234567890abcdef1234567890abcdef"

        # Verification function that asserts trace hash matches expected DB execution hash
        def verify_trace_integrity(trace_entry: AgentTraceEntry, expected_sql: str, expected_params: dict):
            expected_hash = AgentTraceEntry.compute_query_hash(expected_sql, expected_params)
            if trace_entry.db_query_hash != expected_hash:
                raise ValueError(f"Trace hash mismatch! Found {trace_entry.db_query_hash}, expected {expected_hash}")

        # Real entry -> passes
        valid_entry = AgentTraceEntry(
            agent_name="ResearchRAGAgent",
            db_query_hash=real_hash,
            db_session_tenant_id="tenant_12345"
        )
        try:
            verify_trace_integrity(valid_entry, sql_query, params)
            print("  [2.1] Real trace hash verification passed cleanly.")
        except ValueError:
            self.fail("Real trace hash should pass verification.")

        # Tampered entry -> MUST FAIL
        tampered_entry = AgentTraceEntry(
            agent_name="ResearchRAGAgent",
            db_query_hash=fake_hash,
            db_session_tenant_id="tenant_12345"
        )
        with self.assertRaises(ValueError, msg="Verification MUST reject tampered/hardcoded trace hash."):
            verify_trace_integrity(tampered_entry, sql_query, params)
        print("  [2.2] Tampered/fake trace hash correctly rejected by verification logic.")
        print("[PASS] Test 02: Adversarial Trace Mismatch Detection Verified.")

    async def test_03_rag_agent_execution_with_trace_recording(self):
        """Test 3: Verify ResearchRAGAgent executes under RLS and records machine-checkable trace."""
        tenant_id = str(uuid.uuid4())
        tracker = AgentTraceTracker(tenant_id=tenant_id)
        
        context = AgentTaskContext(
            task_id="task_001",
            tenant_id=tenant_id,
            user_id="user_001",
            user_query="who is the project lead",
            subtask_query="who is the project lead",
            trace_tracker=tracker
        )

        mock_search_results = [
            {
                "chunk_id": "chunk_99",
                "document_title": "[CLOUD_INFRASTRUCTURE] Project Orion Spec",
                "chunk_content": "Project lead is Dr. Sarah Lin.",
                "score": 0.82
            }
        ]

        with patch("app.retrieval.implementations.hybrid_retriever.hybrid_retriever.search", return_value=mock_search_results):
            result = await rag_agent.execute(context)

            self.assertTrue(result.success)
            self.assertEqual(len(result.citations), 1)
            self.assertIn("[CLOUD_INFRASTRUCTURE] Project Orion Spec", result.citations)

            # Assert trace entry was recorded
            self.assertEqual(len(tracker.entries), 1)
            trace_entry = tracker.entries[0]
            self.assertEqual(trace_entry.agent_name, "ResearchRAGAgent")
            self.assertEqual(trace_entry.db_session_tenant_id, tenant_id)
            self.assertEqual(len(trace_entry.db_query_hash), 64)
            print(f"  [3.1] ResearchRAGAgent Executed. Citations: {result.citations}")
            print(f"  [3.2] Trace Entry Recorded: {trace_entry.model_dump()}")

        print("[PASS] Test 03: ResearchRAGAgent Execution & Trace Recording Verified.")

if __name__ == "__main__":
    unittest.main()
