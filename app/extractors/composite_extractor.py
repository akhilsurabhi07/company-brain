import hashlib
import time
from typing import Any, Dict, List, Optional
from app.domain.models import ExtractedDocument, ExtractedSection
from app.interfaces.extractor_interfaces import DocumentExtractor
from app.extractors.pdf_extractor import pdf_extractor
from app.extractors.docx_pptx_extractor import docx_pptx_extractor
from app.extractors.tabular_extractor import tabular_extractor
from app.extractors.image_extractor import image_extractor

class MultiModalDocumentExtractor(DocumentExtractor):
    """
    Composite Multi-Modal Document Extractor.
    Automatically detects document type (PDF, DOCX, PPTX, TXT, CSV, HTML, Markdown, PNG, JPEG, scanned PDFs)
    and routes to the specialized extractor engine.
    """

    def __init__(self):
        self._extractors: List[DocumentExtractor] = [
            pdf_extractor,
            docx_pptx_extractor,
            tabular_extractor,
            image_extractor,
        ]

    @property
    def supported_mime_types(self) -> List[str]:
        mimes = []
        for ext in self._extractors:
            mimes.extend(ext.supported_mime_types)
        return list(set(mimes))

    @property
    def supported_extensions(self) -> List[str]:
        extensions = []
        for ext in self._extractors:
            extensions.extend(ext.supported_extensions)
        return list(set(extensions))

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
        ext = "." + filename.split(".")[-1].lower() if "." in filename else ""

        # 1. Match by extension first
        for extractor in self._extractors:
            if ext in extractor.supported_extensions:
                return await extractor.extract(tenant_id, document_id, file_bytes, filename, mime_type, metadata)

        # 2. Match by MIME type
        for extractor in self._extractors:
            if mime_type in extractor.supported_mime_types:
                return await extractor.extract(tenant_id, document_id, file_bytes, filename, mime_type, metadata)

        # 3. Fallback: Parse as Plaintext
        checksum = hashlib.sha256(file_bytes).hexdigest()
        text_content = file_bytes.decode("utf-8", errors="ignore")
        sections = [ExtractedSection(section_id="sec_1", heading="Plaintext Document", level=1, content=text_content)]

        return ExtractedDocument(
            tenant_id=tenant_id,
            document_id=document_id,
            metadata={**metadata, "filename": filename, "fallback": True},
            clean_text=text_content,
            sections=sections,
            tables=[],
            images=[],
            captions=[],
            source=f"raw:{filename}",
            checksum=checksum,
            timestamps={"extracted_at": time.strftime("%Y-%m-%dT%H:%M:%SZ")},
        )

# Global composite extractor instance
multimodal_extractor = MultiModalDocumentExtractor()
