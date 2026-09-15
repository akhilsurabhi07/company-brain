"""Real-data regression suite for hybrid retrieval (Module 4).

Pins down a real retrieval failure found and fixed 2026-08-20 using real GitHub README
content ingested via the actual GitHub connector: a genuinely relevant, correctly
keyword-matched document (combined score 0.896) was rejected because of a brittle,
arbitrary second threshold (raw cosine >= 0.50) that ignored the keyword signal — the
real raw cosine was 0.4960, four thousandths below the floor. Root cause and fix are
documented in app/retrieval/implementations/hybrid_retriever.py.

Uses directly-inserted, realistic content + REAL BGE embeddings (the embedding model is
never mocked, matching the rest of this suite) so these tests run without a live GitHub
token or network dependency, while still exercising the exact same code paths
(chunk_embed_and_store, HybridRetriever.search) the real GitHub connector uses.
"""
import uuid
import pytest
from sqlalchemy import text
from app.db.database import async_session_factory
from app.processors.ingestion_pipeline import chunk_embed_and_store
from app.retrieval.implementations.hybrid_retriever import hybrid_retriever

# Real content shape: this is (near-verbatim) the actual README text ingested from the
# real akhilsurabhi07/AI-agent repository during live testing.
README_CONTENT = (
    "This is a Next.js project bootstrapped with create-next-app.\n\n"
    "## Getting Started\n\n"
    "First, run the development server: npm run dev, yarn dev, or pnpm dev. "
    "Open http://localhost:3000 with your browser to see the result.\n\n"
    "You can start editing the page by modifying app/page.tsx. The page auto-updates "
    "as you edit the file. This project uses next/font to automatically optimize and "
    "load Geist, a new font family for Vercel.\n\n"
    "## Learn More\n\n"
    "To learn more about Next.js, take a look at the Next.js documentation."
)

UNRELATED_CONTENT = (
    "COMPANY HR POLICY MANUAL.\n\nAll employees are entitled to 24 days of paid annual "
    "leave per calendar year. Sick leave is capped at 12 days annually. The probation "
    "period for new hires is 90 days with reviews at day 30, 60, and 90."
)


async def _make_tenant(name: str) -> str:
    tenant_id = str(uuid.uuid4())
    async with async_session_factory() as session:
        await session.execute(
            text("INSERT INTO tenants (id, name, domain) VALUES (:id, :name, :domain)"),
            {"id": tenant_id, "name": name, "domain": f"{name.lower().replace(' ', '-')}-{tenant_id[:8]}.company.com"},
        )
        await session.commit()
    return tenant_id


async def _ingest_readme(tenant_id: str, content: str = README_CONTENT, title: str = "test-org/example-repo — README") -> str:
    """Real ingestion path: real document row -> real chunk_embed_and_store (real
    semantic chunking + real BGE embeddings + real pgvector/document_chunks persistence)."""
    doc_id = str(uuid.uuid4())
    async with async_session_factory() as session:
        await session.execute(text("SELECT set_config('app.current_tenant_id', :tid, true)"), {"tid": tenant_id})
        await session.execute(
            text("""
                INSERT INTO documents (
                    id, tenant_id, source_app, resource_category, resource_type, external_id,
                    title, content, s3_bucket, s3_key, is_compressed, file_size_bytes
                ) VALUES (
                    :id, :tid, 'github', 'doc', 'readme', :ext_id, :title, :content,
                    'test-bucket', :key, TRUE, :size
                )
            """),
            {
                "id": doc_id, "tid": tenant_id, "ext_id": f"readme_{doc_id[:8]}",
                "title": title, "content": content,
                "key": f"raw/{tenant_id}/github/readme_{doc_id[:8]}.json.zst", "size": len(content),
            },
        )
        await session.commit()

    result = await chunk_embed_and_store(tenant_id=tenant_id, document_id=doc_id, full_text=content, resource_category="doc")
    assert result["status"] == "completed", f"Real ingestion must succeed: {result}"
    return doc_id


# ── Test A — Direct README retrieval (query uses the README's own wording) ──
@pytest.mark.asyncio
async def test_a_direct_readme_retrieval():
    tenant_id = await _make_tenant("Retrieval Test A")
    await _ingest_readme(tenant_id)

    result = await hybrid_retriever.search(tenant_id=tenant_id, query="Next.js project bootstrapped with create-next-app", top_k=5)
    assert len(result["chunks"]) > 0, "A query using the document's own exact wording MUST retrieve it."
    assert all("README" in c["doc_title"] for c in result["chunks"])


# ── Test B — Semantic README retrieval (same concept, different wording) ──
@pytest.mark.asyncio
async def test_b_semantic_paraphrase_retrieval():
    tenant_id = await _make_tenant("Retrieval Test B")
    await _ingest_readme(tenant_id)

    # None of these words appear verbatim in the README's "run the development server"
    # sentence, but the concept is the same — this is the exact case that used to fail.
    result = await hybrid_retriever.search(tenant_id=tenant_id, query="how do I get this project running locally", top_k=5)
    assert len(result["chunks"]) > 0, "A semantic paraphrase MUST still retrieve the relevant document."
    assert all("README" in c["doc_title"] for c in result["chunks"])


# ── Test C — Exact keyword query (real Postgres full-text search channel) ──
@pytest.mark.asyncio
async def test_c_exact_keyword_query_hits_fts_channel():
    tenant_id = await _make_tenant("Retrieval Test C")
    await _ingest_readme(tenant_id)

    result = await hybrid_retriever.search(tenant_id=tenant_id, query="create-next-app", top_k=5, debug=True)
    assert len(result["chunks"]) > 0
    assert result["debug"]["keyword_candidate_count"] > 0, "An exact technical term MUST be found by the full-text search channel."
    assert any(c["keyword_rank"] is not None for c in result["chunks"])


# ── Test D — Irrelevant query (README must not be falsely ranked relevant) ──
@pytest.mark.asyncio
async def test_d_irrelevant_query_does_not_select_readme():
    tenant_id = await _make_tenant("Retrieval Test D")
    await _ingest_readme(tenant_id)

    result = await hybrid_retriever.search(tenant_id=tenant_id, query="what is the capital of France", top_k=5)
    assert len(result["chunks"]) == 0, "A genuinely unrelated query MUST NOT select the README as relevant evidence."


# ── Test E — Zero-PR query must not fabricate (regression for the live bug found today) ──
@pytest.mark.asyncio
async def test_e_zero_pr_repo_does_not_fabricate_prs():
    tenant_id = await _make_tenant("Retrieval Test E")
    await _ingest_readme(tenant_id)  # only a README exists — zero PR documents ingested

    result = await hybrid_retriever.search(tenant_id=tenant_id, query="summarize the pull requests for this repository", top_k=5)
    # The README's generic boilerplate must not be retrieved as if it were PR content.
    assert len(result["chunks"]) == 0, "With zero real PR data, retrieval MUST NOT surface unrelated content as if it answered a PR question."


# ── Test F — Missing information anywhere in connected sources ──
@pytest.mark.asyncio
async def test_f_missing_information_returns_no_evidence():
    tenant_id = await _make_tenant("Retrieval Test F")
    await _ingest_readme(tenant_id)

    result = await hybrid_retriever.search(tenant_id=tenant_id, query="what is our company's revenue forecast for next quarter", top_k=5)
    assert len(result["chunks"]) == 0, "Information that exists nowhere in ingested sources MUST NOT be fabricated evidence."


# ── Test G — Tenant isolation ──
@pytest.mark.asyncio
async def test_g_tenant_isolation_enforced():
    tenant_a = await _make_tenant("Retrieval Test G-A")
    tenant_b = await _make_tenant("Retrieval Test G-B")
    await _ingest_readme(tenant_a, content=README_CONTENT, title="tenant-a/repo — README")
    await _ingest_readme(tenant_b, content=UNRELATED_CONTENT, title="tenant-b/hr-docs — HR Policy")

    # Tenant A must never see Tenant B's HR content, even via a query tuned to it.
    result_a = await hybrid_retriever.search(tenant_id=tenant_a, query="probation period sick leave annual leave", top_k=5)
    assert all("tenant-b" not in c["doc_title"] for c in result_a["chunks"]), "Tenant A MUST NOT retrieve Tenant B's documents."

    # Tenant B must never see Tenant A's README content.
    result_b = await hybrid_retriever.search(tenant_id=tenant_b, query="Next.js create-next-app development server", top_k=5)
    assert all("tenant-a" not in c["doc_title"] for c in result_b["chunks"]), "Tenant B MUST NOT retrieve Tenant A's documents."

    # And each tenant's own real query against its own real data still works.
    result_a_own = await hybrid_retriever.search(tenant_id=tenant_a, query="create-next-app", top_k=5)
    assert len(result_a_own["chunks"]) > 0
    result_b_own = await hybrid_retriever.search(tenant_id=tenant_b, query="probation period", top_k=5)
    assert len(result_b_own["chunks"]) > 0


# ── Test H — Permission/ACL filtering ──
@pytest.mark.asyncio
async def test_h_acl_restricts_evidence_before_it_reaches_the_llm():
    tenant_id = await _make_tenant("Retrieval Test H")
    open_doc_id = await _ingest_readme(tenant_id, content=README_CONTENT, title="public-repo — README")
    restricted_doc_id = await _ingest_readme(
        tenant_id, content=README_CONTENT.replace("Next.js", "ConfidentialNextJs"), title="private-repo — README"
    )

    async with async_session_factory() as session:
        await session.execute(text("SELECT set_config('app.current_tenant_id', :tid, true)"), {"tid": tenant_id})
        await session.execute(
            text("""
                INSERT INTO document_acls (document_id, tenant_id, principal_type, principal_external_id, permission)
                VALUES (:doc_id, :tid, 'user', 'authorized_user_123', 'read')
            """),
            {"doc_id": restricted_doc_id, "tid": tenant_id},
        )
        await session.commit()

    # An unauthorized user must not retrieve the ACL-restricted document...
    result_unauthorized = await hybrid_retriever.search(
        tenant_id=tenant_id, query="ConfidentialNextJs create-next-app", top_k=5, user_id="some_other_user"
    )
    assert all(c["document_id"] != restricted_doc_id for c in result_unauthorized["chunks"]), \
        "A user without ACL permission MUST NOT receive the restricted document as evidence."

    # ...but the authorized user must.
    result_authorized = await hybrid_retriever.search(
        tenant_id=tenant_id, query="ConfidentialNextJs create-next-app", top_k=5, user_id="authorized_user_123"
    )
    assert any(c["document_id"] == restricted_doc_id for c in result_authorized["chunks"]), \
        "The ACL-authorized user MUST be able to retrieve the document."

    # The open document (no ACL rows at all) must remain visible to everyone regardless.
    result_open = await hybrid_retriever.search(tenant_id=tenant_id, query="create-next-app", top_k=5, user_id="some_other_user")
    assert any(c["document_id"] == open_doc_id for c in result_open["chunks"]), \
        "A document with no ACL rows MUST remain open (default-allow) to preserve existing behavior for un-ACL'd content."


# ── Retrieval threshold / calibration regression ──
@pytest.mark.asyncio
async def test_retrieval_reranker_threshold_is_calibrated_not_guessed():
    """Regression pin for the calibration itself: relevant content must clear the
    accept threshold with real margin, irrelevant content must fail it with real margin."""
    from app.retrieval.implementations.hybrid_retriever import RERANK_ACCEPT_THRESHOLD
    from app.retrieval.implementations.cross_encoder import reranker as cross_encoder

    relevant = cross_encoder.rerank(
        "how do I run the development server",
        [{"content": README_CONTENT}], top_n=1,
    )[0]["rerank_score"]
    irrelevant = cross_encoder.rerank(
        "what is the capital of France",
        [{"content": README_CONTENT}], top_n=1,
    )[0]["rerank_score"]

    assert relevant > RERANK_ACCEPT_THRESHOLD + 1.0, "Relevant content must clear the threshold with real margin."
    assert irrelevant < RERANK_ACCEPT_THRESHOLD - 1.0, "Irrelevant content must fail the threshold with real margin."
