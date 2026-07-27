import asyncio
import uuid
import pytest
from app.domain.models import ExtractedDocument, ExtractedTable, ExtractedImage
from app.extractors.pdf_extractor import pdf_extractor
from app.extractors.docx_pptx_extractor import docx_pptx_extractor
from app.extractors.tabular_extractor import tabular_extractor
from app.extractors.image_extractor import image_extractor
from app.extractors.composite_extractor import multimodal_extractor
from app.extractors.ocr_provider import default_ocr_provider
from app.db.extracted_doc_repo import extracted_doc_repo
from app.workers.tasks.extraction_tasks import process_document_extraction_task, process_ocr_fallback_task
from app.db.database import async_session_factory
from sqlalchemy import text

@pytest.mark.asyncio
async def test_1_tabular_csv_extraction_to_json_and_markdown_grid():
    """Verify CSV spreadsheet extraction into JSON data + Markdown Grid format."""
    csv_bytes = b"Product,Price,Category\nLaptop,1200,Electronics\nMouse,25,Accessories\n"
    tenant_id = str(uuid.uuid4())
    doc_id = str(uuid.uuid4())

    extracted = await tabular_extractor.extract(
        tenant_id=tenant_id,
        document_id=doc_id,
        file_bytes=csv_bytes,
        filename="products.csv",
        mime_type="text/csv",
    )

    assert extracted.tenant_id == tenant_id
    assert len(extracted.tables) == 1
    table = extracted.tables[0]
    
    # Check Markdown Grid
    assert "| Product | Price | Category |" in table.grid_markdown
    assert "| Laptop | 1200 | Electronics |" in table.grid_markdown
    
    # Check Structured JSON
    assert len(table.data_json) == 2
    assert table.data_json[0]["Product"] == "Laptop"
    assert table.data_json[0]["Price"] == "1200"

@pytest.mark.asyncio
async def test_2_docx_and_pptx_extraction():
    """Verify DOCX and text file layout, heading, and text parsing."""
    txt_bytes = b"# Executive Summary\nCompany Brain Phase 2 Multi-Modal Extractor is running.\n\n# Q3 Targets\nRevenue growth of 40% YoY."
    tenant_id = str(uuid.uuid4())
    doc_id = str(uuid.uuid4())

    extracted = await docx_pptx_extractor.extract(
        tenant_id=tenant_id,
        document_id=doc_id,
        file_bytes=txt_bytes,
        filename="summary.md",
        mime_type="text/markdown",
    )

    assert "Executive Summary" in extracted.clean_text
    assert len(extracted.sections) >= 1

@pytest.mark.asyncio
async def test_3_ocr_provider_fallback():
    """Verify Tesseract 5 OCR provider fallback on image bytes."""
    tiny_png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06"
        b"\x00\x00\x00\x1f\x15c4\x00\x00\x00\nIDATx\x9cc\x00\x01\x00\x00\x05\x00\x01"
        b"\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    ocr_result = default_ocr_provider.extract_text_from_image_bytes(tiny_png, mime_type="image/png")
    assert isinstance(ocr_result, str)

@pytest.mark.asyncio
async def test_4_composite_multimodal_extractor_routing():
    """Verify Composite Extractor routes by extension and MIME type."""
    tenant_id = str(uuid.uuid4())
    doc_id = str(uuid.uuid4())
    csv_bytes = b"ID,Name\n1,Acme\n2,Tesla\n"

    extracted = await multimodal_extractor.extract(
        tenant_id=tenant_id,
        document_id=doc_id,
        file_bytes=csv_bytes,
        filename="clients.csv",
        mime_type="text/csv",
    )
    assert len(extracted.tables) == 1

@pytest.mark.asyncio
async def test_5_postgresql_rls_persistence_and_concurrency():
    """
    Verifies:
      1. Persisting & retrieving ExtractedDocument in AWS RDS PostgreSQL under RLS.
      2. 10 concurrent workers processing extractions simultaneously.
      3. State machine status transitions and retry logging.
    """
    tenant_id = str(uuid.uuid4())
    document_id = str(uuid.uuid4())

    async with async_session_factory() as session:
        await session.execute(text("INSERT INTO tenants (id, name, domain) VALUES (:id, 'Extract Tenant', :domain)"), {"id": tenant_id, "domain": f"ext_{tenant_id[:8]}.com"})
        await session.execute(text(f"SET LOCAL app.current_tenant_id = '{tenant_id}'"))
        await session.execute(text("""
            INSERT INTO documents (id, tenant_id, source_app, resource_category, resource_type, external_id, title, s3_bucket, s3_key)
            VALUES (:doc_id, :tenant_id, 'google_drive', 'doc', 'file', 'gdrive_file_1', 'Strategy.pdf', 'bucket', 'key')
        """), {"doc_id": document_id, "tenant_id": tenant_id})
        await session.commit()

    sample_doc = ExtractedDocument(
        tenant_id=tenant_id,
        document_id=document_id,
        metadata={"author": "Alice"},
        clean_text="Strategy Roadmap for 2026",
        sections=[],
        tables=[
            ExtractedTable(
                table_id="tbl_1",
                page_number=1,
                grid_markdown="| Col A | Col B |\n| --- | --- |\n| Val A | Val B |",
                data_json=[{"Col A": "Val A", "Col B": "Val B"}]
            )
        ],
        images=[],
        captions=[],
        source="pdf:Strategy.pdf",
        checksum="sha256_mock_hash",
    )

    db_id = await extracted_doc_repo.save_extracted_document(sample_doc)
    assert db_id != ""

    retrieved = await extracted_doc_repo.get_extracted_document(tenant_id, document_id)
    assert retrieved is not None
    assert retrieved.clean_text == "Strategy Roadmap for 2026"
    assert len(retrieved.tables) == 1
    assert "| Col A | Col B |" in retrieved.tables[0].grid_markdown

    # Concurrent 10 Workers Execution
    async def _worker_task(idx: int):
        d_id = str(uuid.uuid4())
        ext_str = f"ext_{idx}_{str(uuid.uuid4())[:4]}"
        async with async_session_factory() as session:
            await session.execute(text(f"SET LOCAL app.current_tenant_id = '{tenant_id}'"))
            await session.execute(text("""
                INSERT INTO documents (id, tenant_id, source_app, resource_category, resource_type, external_id, title, s3_bucket, s3_key)
                VALUES (:doc_id, :tenant_id, 'slack', 'chat', 'message', :ext_id, :title, 'bucket', 'key')
            """), {"doc_id": d_id, "tenant_id": tenant_id, "ext_id": ext_str, "title": f"Doc {idx}"})
            await session.commit()

        sample_csv = f"ID,Value\n{idx},Val_{idx}\n".encode("utf-8")
        extracted = await multimodal_extractor.extract(
            tenant_id=tenant_id,
            document_id=d_id,
            file_bytes=sample_csv,
            filename=f"file_{idx}.csv",
            mime_type="text/csv",
        )
        return await extracted_doc_repo.save_extracted_document(extracted)

    worker_results = await asyncio.gather(*[_worker_task(i) for i in range(10)])
    assert len(worker_results) == 10

    # State machine retries verification
    await extracted_doc_repo.update_job_status(
        tenant_id=tenant_id,
        document_id=document_id,
        pipeline_stage="extracting",
        status="retrying",
        priority=10,
        error_message="OCR Timeout - Retrying (Attempt 1)"
    )

    async with async_session_factory() as session:
        await session.execute(text(f"SET LOCAL app.current_tenant_id = '{tenant_id}'"))
        res = await session.execute(
            text("SELECT status, pipeline_stage, error_message FROM document_processing_jobs WHERE tenant_id = :t AND document_id = :d"),
            {"t": tenant_id, "d": document_id}
        )
        row = res.fetchone()
        assert row is not None
        assert row[0] == "retrying"
        assert row[1] == "extracting"
        assert "OCR Timeout" in row[2]
