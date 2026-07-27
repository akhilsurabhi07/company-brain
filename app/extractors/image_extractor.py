import hashlib
import io
import time
import uuid
from typing import Any, Dict, List, Optional
from PIL import Image
from app.domain.models import ExtractedDocument, ExtractedImage, ExtractedSection
from app.interfaces.extractor_interfaces import DocumentExtractor, OCRProvider
from app.extractors.ocr_provider import default_ocr_provider

class ImageExtractor(DocumentExtractor):
    """
    Document Extractor for Standalone Image Files (PNG, JPEG, TIFF, BMP).
    Applies Tesseract 5 OCR to extract text from scanned forms, receipts, diagrams, and photos.
    """

    def __init__(self, ocr_provider: Optional[OCRProvider] = None):
        self.ocr_provider = ocr_provider or default_ocr_provider

    @property
    def supported_mime_types(self) -> List[str]:
        return [
            "image/png",
            "image/jpeg",
            "image/jpg",
            "image/tiff",
            "image/bmp",
        ]

    @property
    def supported_extensions(self) -> List[str]:
        return [".png", ".jpg", ".jpeg", ".tiff", ".bmp"]

    async def extract(
        self,
        tenant_id: str,
        document_id: str,
        file_bytes: bytes,
        filename: str,
        mime_type: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ExtractedDocument:
        metadata = metadata or {}
        checksum = hashlib.sha256(file_bytes).hexdigest()

        # Read image properties via PIL
        width, height, format_name = None, None, "UNKNOWN"
        try:
            img = Image.open(io.BytesIO(file_bytes))
            width, height, format_name = img.width, img.height, img.format
        except Exception:
            pass

        # Perform OCR via Tesseract 5
        ocr_text = self.ocr_provider.extract_text_from_image_bytes(file_bytes, mime_type=mime_type)

        image_entry = ExtractedImage(
            image_id=f"img_file_{str(uuid.uuid4())[:6]}",
            page_number=1,
            mime_type=mime_type,
            caption=f"OCR extracted text from image file {filename}",
            width=width,
            height=height,
        )

        sections = [
            ExtractedSection(
                section_id="sec_img_1",
                heading=f"OCR Extracted Content ({filename})",
                level=1,
                content=ocr_text,
            )
        ]

        return ExtractedDocument(
            tenant_id=tenant_id,
            document_id=document_id,
            metadata={
                **metadata,
                "filename": filename,
                "width": width,
                "height": height,
                "image_format": format_name,
            },
            clean_text=ocr_text,
            sections=sections,
            tables=[],
            images=[image_entry],
            captions=[f"Image {filename}: {ocr_text[:100]}"],
            source=f"image:{filename}",
            checksum=checksum,
            timestamps={
                "extracted_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            },
        )

image_extractor = ImageExtractor()
