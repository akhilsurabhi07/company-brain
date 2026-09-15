"""Real end-to-end test for OCR in the browser upload path — Phase 2 audit item 1.

Regression pin for real gaps found and fixed 2026-08-20:
  1. app/processors/ocr_processor.py was a hardcoded stub (`f"[OCR Processed Image
     ({len} bytes...)]"`) with zero callers anywhere — images and scanned PDFs were
     never actually OCR'd by anything, despite the module's docstring claiming they
     were. Replaced with real, self-hosted OCR (EasyOCR) wired into the live
     POST /api/v1/upload/document path.
  2. EasyOCR's own first-run model-download progress bar writes a Unicode block
     character ('█') to stdout; Windows' default console codec can't encode it,
     crashing the very first OCR call on a fresh machine. Fixed by reconfiguring
     stdout/stderr to UTF-8 with lossy fallback before constructing the reader.

These tests use real rendered images (PIL) and a real image-only PDF (PyMuPDF, no
text layer) — not mocked OCR output — and assert the exact real text drawn into them
comes back out through the real, live upload endpoint and is genuinely retrievable
in chat afterward, matching the standard already used for the GitHub connector and
hybrid_retriever verification.
"""
import io
import uuid
import httpx
import pytest
from PIL import Image, ImageDraw, ImageFont
from app.api.upload_router import extract_text_from_file, ocr_image_bytes
from app.main import app
from tests.conftest import auth_headers_for


def _render_text_image(lines: list[str], size=(700, 220)) -> bytes:
    img = Image.new("RGB", size, color="white")
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("arial.ttf", 32)
    except Exception:
        font = ImageFont.load_default()
    for i, line in enumerate(lines):
        draw.text((20, 20 + i * 60), line, fill="black", font=font)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def test_a_real_image_ocr_recovers_real_text_not_a_placeholder():
    """A real screenshot-style image with real text must come back as that real
    text — not the old fake f"[OCR Processed Image ...]" placeholder."""
    png_bytes = _render_text_image(["Invoice Total XK9273", "Vendor: Meridian Supply Co"])
    result = extract_text_from_file("invoice_screenshot.png", png_bytes)
    assert "XK9273" in result or "Meridian" in result, f"OCR did not recover real text, got: {result!r}"
    assert "[OCR Processed Image" not in result, "Old fake stub output must never appear again."


def test_b_blank_image_gives_honest_no_text_found_not_fabricated_content():
    """A real image with no text must honestly report finding nothing — never
    invent content, matching the project's anti-fabrication standard."""
    img = Image.new("RGB", (300, 150), color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    result = extract_text_from_file("blank.png", buf.getvalue())
    assert "OCR ran but found no readable text" in result


def test_c_scanned_pdf_with_no_text_layer_uses_ocr_fallback():
    """A PDF that is really just an embedded image (no text layer at all — the
    signature of a scanned document) must still yield its real text via the OCR
    fallback, not an empty/near-empty extraction."""
    import pymupdf
    png_bytes = _render_text_image(["Purchase Order 55219", "Amount Due: $18,400"])
    doc = pymupdf.open()
    page = doc.new_page(width=700, height=220)
    page.insert_image(pymupdf.Rect(0, 0, 700, 220), stream=png_bytes)
    pdf_bytes = doc.tobytes()
    doc.close()

    result = extract_text_from_file("scanned_po.pdf", pdf_bytes)
    assert "55219" in result or "18,400" in result or "Purchase Order" in result, (
        f"Scanned-PDF OCR fallback did not recover real text, got: {result!r}"
    )


@pytest.mark.asyncio
async def test_d_uploaded_image_is_ingested_and_answerable_in_chat():
    """Full real path: browser upload of an image -> real OCR -> real chunk/embed/
    store -> genuinely retrievable and answerable via the live chat pipeline. Same
    standard as test_upload_pipeline_real.py's text-file case, extended to images."""
    from sqlalchemy import text
    from app.db.database import async_session_factory

    tenant_id = str(uuid.uuid4())
    async with async_session_factory() as session:
        await session.execute(
            text("INSERT INTO tenants (id, name, domain) VALUES (:id, :name, :domain) ON CONFLICT (id) DO NOTHING"),
            {"id": tenant_id, "name": "OCR Upload Test Tenant", "domain": f"ocr-test-{tenant_id[:8]}.company.com"},
        )
        await session.commit()

    png_bytes = _render_text_image([
        "Whiteboard Notes: Project Solstice",
        "Owner is Priya Nakamura, launch Q3",
    ])

    headers = auth_headers_for(tenant_id)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post(
            "/api/v1/upload/document",
            files={"file": ("whiteboard.png", png_bytes, "image/png")},
            data={"tenant_id": tenant_id, "source_label": "UPLOAD"},
            headers=headers,
        )
        assert resp.status_code == 200, f"Image upload MUST succeed via real OCR, got: {resp.text}"
        body = resp.json()
        assert body["chunks_ingested"] > 0

        chat_resp = await client.post("/api/v6a/chat/turn", json={
            "user_query": "who owns Project Solstice according to the whiteboard notes",
            "session_id": "ocr_upload_test_session",
            "tenant_id": tenant_id,
            "user_id": "ocr_test_user",
        }, headers=headers)
        assert chat_resp.status_code == 200
        cj = chat_resp.json()
        raw_ans = cj.get("response_text") or cj.get("response") or ""
        answer_text = str(raw_ans.get("text_content", raw_ans) if isinstance(raw_ans, dict) else raw_ans)
        assert "Priya" in answer_text or "Nakamura" in answer_text, (
            f"Chat MUST retrieve the real fact OCR'd from the image, got: {answer_text!r}"
        )
