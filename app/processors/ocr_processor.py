"""
DEPRECATED — superseded 2026-08-20 by real OCR in app/api/upload_router.py.

This module used to be a hardcoded stub: extract_text_from_image() returned
f"[OCR Processed Image ({len} bytes...)]" regardless of what was in the image, and
had zero callers anywhere in the codebase (confirmed via grep before this change).

Real, self-hosted OCR (EasyOCR — same self-hosted-model philosophy as BGEEmbedder;
no external API, no system Tesseract binary) now lives in
app.api.upload_router.ocr_image_bytes() / ocr_scanned_pdf(), wired into the live
POST /api/v1/upload/document endpoint. Use those instead of this file.

Left in place (not deleted) so any historical import of this module fails loudly
with a clear pointer rather than silently vanishing.
"""

raise ImportError(
    "app.processors.ocr_processor is deprecated and no longer implements OCR. "
    "Use app.api.upload_router.ocr_image_bytes() / ocr_scanned_pdf() instead — "
    "see the module docstring in this file for why."
)
