from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Tuple
from app.domain.models import ExtractedDocument, ExtractedTable, ExtractedImage

class OCRProvider(ABC):
    """Swappable interface for Optical Character Recognition (OCR)."""

    @abstractmethod
    def extract_text_from_image_bytes(self, image_bytes: bytes, mime_type: str = "image/png") -> str:
        """Extracts text from image binary bytes."""
        pass

    @abstractmethod
    def extract_text_from_scanned_pdf(self, pdf_bytes: bytes) -> str:
        """Extracts text from scanned PDF binary bytes."""
        pass

class TableExtractor(ABC):
    """Swappable interface for extracting structured tables as JSON and Markdown grids."""

    @abstractmethod
    def extract_tables_from_pdf(self, pdf_bytes: bytes) -> List[ExtractedTable]:
        """Extracts tables from PDF bytes into ExtractedTable list."""
        pass

    @abstractmethod
    def extract_tables_from_text(self, text_content: str) -> List[ExtractedTable]:
        """Extracts markdown or CSV formatted tables from text."""
        pass

class ImageCaptionProvider(ABC):
    """Swappable interface for image captioning (local/placeholder/VLM)."""

    @abstractmethod
    def generate_caption(self, image_bytes: bytes, mime_type: str = "image/png") -> str:
        """Generates descriptive caption for an image."""
        pass

class DocumentExtractor(ABC):
    """Primary abstract interface for layout-aware document extraction."""

    @property
    @abstractmethod
    def supported_mime_types(self) -> List[str]:
        """List of supported MIME types for this extractor."""
        pass

    @property
    @abstractmethod
    def supported_extensions(self) -> List[str]:
        """List of supported file extensions."""
        pass

    @abstractmethod
    async def extract(
        self,
        tenant_id: str,
        document_id: str,
        file_bytes: bytes,
        filename: str,
        mime_type: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ExtractedDocument:
        """Extracts normalized ExtractedDocument from raw file bytes."""
        pass
