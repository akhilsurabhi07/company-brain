import hashlib
import io
import time
import uuid
from typing import Any, Dict, List, Optional
from app.domain.models import ExtractedDocument, ExtractedImage, ExtractedSection, ExtractedTable
from app.interfaces.extractor_interfaces import DocumentExtractor, OCRProvider, TableExtractor
from app.extractors.ocr_provider import default_ocr_provider
from app.extractors.table_extractor import default_table_extractor

class PDFExtractor(DocumentExtractor):
    """
    Multi-Modal PDF Extractor.
    Extracts layout-aware text, sections, structured tables (JSON + Markdown grid),
    embedded images, and applies Tesseract 5 OCR fallback on scanned pages.
    """

    def __init__(
        self,
        ocr_provider: Optional[OCRProvider] = None,
        table_extractor: Optional[TableExtractor] = None,
    ):
        self.ocr_provider = ocr_provider or default_ocr_provider
        self.table_extractor = table_extractor or default_table_extractor

    @property
    def supported_mime_types(self) -> List[str]:
        return ["application/pdf"]

    @property
    def supported_extensions(self) -> List[str]:
        return [".pdf"]

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

        extracted_text_pages: List[str] = []
        sections: List[ExtractedSection] = []
        extracted_images: List[ExtractedImage] = []
        captions: List[str] = []

        # 1. Extract Structured Tables via pdfplumber
        tables: List[ExtractedTable] = self.table_extractor.extract_tables_from_pdf(file_bytes)

        # 2. Extract Text, Layout, Sections, and Embedded Images via PyMuPDF (fitz)
        try:
            import fitz  # PyMuPDF
            doc = fitz.open(stream=file_bytes, filetype="pdf")

            for page_num in range(len(doc)):
                page = doc[page_num]
                page_text = page.get_text("text").strip()

                # Scanned PDF Detection: If page has virtually no text, trigger OCR fallback
                if len(page_text) < 20:
                    pix = page.get_pixmap(dpi=150)
                    img_bytes = pix.tobytes("png")
                    ocr_text = self.ocr_provider.extract_text_from_image_bytes(img_bytes, mime_type="image/png")
                    if ocr_text:
                        page_text = f"[OCR Page {page_num+1}]\n{ocr_text}"

                if page_text:
                    extracted_text_pages.append(page_text)

                # Extract embedded images
                for img_idx, img_info in enumerate(page.get_images(full=True)):
                    try:
                        xref = img_info[0]
                        base_img = doc.extract_image(xref)
                        img_bytes = base_img["image"]
                        ext = base_img["ext"]
                        img_mime = f"image/{ext}"

                        caption = self.ocr_provider.extract_text_from_image_bytes(img_bytes, mime_type=img_mime)
                        if caption:
                            captions.append(f"Image P.{page_num+1}: {caption[:100]}")

                        extracted_images.append(
                            ExtractedImage(
                                image_id=f"img_p{page_num+1}_{img_idx+1}_{str(uuid.uuid4())[:6]}",
                                page_number=page_num + 1,
                                mime_type=img_mime,
                                caption=caption or f"Embedded image on page {page_num+1}",
                                width=base_img.get("width"),
                                height=base_img.get("height"),
                            )
                        )
                    except Exception:
                        continue

            doc.close()

        except Exception as e:
            # Full Fallback to PyTesseract OCR if PyMuPDF fails
            ocr_text = self.ocr_provider.extract_text_from_scanned_pdf(file_bytes)
            extracted_text_pages.append(f"[Full OCR Fallback]\n{ocr_text}")

        full_clean_text = "\n\n".join(extracted_text_pages)

        # 3. Derive Document Sections from Paragraph Headings
        lines = full_clean_text.splitlines()
        current_section = "Introduction"
        current_content: List[str] = []

        for line in lines:
            line_str = line.strip()
            if line_str.startswith("#") or (len(line_str) < 60 and line_str.isupper() and len(line_str) > 3):
                if current_content:
                    sections.append(ExtractedSection(
                        section_id=f"sec_{len(sections)+1}",
                        heading=current_section,
                        level=1,
                        content="\n".join(current_content)
                    ))
                    current_content = []
                current_section = line_str.lstrip("#").strip()
            else:
                if line_str:
                    current_content.append(line_str)

        if current_content:
            sections.append(ExtractedSection(
                section_id=f"sec_{len(sections)+1}",
                heading=current_section,
                level=1,
                content="\n".join(current_content)
            ))

        return ExtractedDocument(
            tenant_id=tenant_id,
            document_id=document_id,
            metadata={
                **metadata,
                "filename": filename,
                "total_pages": len(extracted_text_pages),
                "total_tables": len(tables),
                "total_images": len(extracted_images),
            },
            clean_text=full_clean_text,
            sections=sections,
            tables=tables,
            images=extracted_images,
            captions=captions,
            source=f"pdf:{filename}",
            checksum=checksum,
            timestamps={
                "extracted_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            },
        )

pdf_extractor = PDFExtractor()
