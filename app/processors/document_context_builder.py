"""
Document Context Builder & Language Detector
============================================
Assembles raw extracted sections, tables, images, and paragraphs into a structured
DocumentContextTree hierarchy prior to chunking.
Detects primary language code (en, es, de, ja, etc.).
"""
from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
from app.domain.models import ExtractedDocument, ExtractedSection, ExtractedTable, ExtractedImage

class ContextElement(BaseModel):
    element_type: str  # 'heading', 'paragraph', 'table', 'image_caption'
    content: str
    page_number: Optional[int] = None
    section_heading: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

class DocumentContextTree(BaseModel):
    document_id: str
    tenant_id: str
    title: str
    language_code: str = "en"
    elements: List[ContextElement] = Field(default_factory=list)
    full_context_text: str = ""

class LanguageDetector:
    """Detects document language."""
    @staticmethod
    def detect_language(text: str) -> str:
        if not text:
            return "en"
        sample = text[:1000].lower()
        if any(w in sample for w in ["el", "la", "los", "las", "para", "por", "como"]):
            return "es"
        if any(w in sample for w in ["der", "die", "das", "und", "ist", "nicht"]):
            return "de"
        return "en"

language_detector = LanguageDetector()

class DocumentContextBuilder:
    """Builds a structured DocumentContextTree from an ExtractedDocument."""

    def build_context_tree(self, doc: ExtractedDocument) -> DocumentContextTree:
        lang = language_detector.detect_language(doc.clean_text)
        elements: List[ContextElement] = []

        # 1. Process Sections & Headings
        if doc.sections:
            for sec in doc.sections:
                if sec.heading:
                    elements.append(
                        ContextElement(
                            element_type="heading",
                            content=sec.heading,
                            section_heading=sec.heading,
                            metadata={"level": sec.level}
                        )
                    )
                if sec.content:
                    elements.append(
                        ContextElement(
                            element_type="paragraph",
                            content=sec.content,
                            section_heading=sec.heading,
                        )
                    )
        else:
            # Fallback for plain text: split paragraphs and detect markdown headings
            for para in doc.clean_text.split("\n"):
                para_clean = para.strip()
                if not para_clean:
                    continue
                if para_clean.startswith("#"):
                    elements.append(
                        ContextElement(
                            element_type="heading",
                            content=para_clean.lstrip("#").strip(),
                            section_heading=para_clean.lstrip("#").strip(),
                        )
                    )
                else:
                    elements.append(
                        ContextElement(
                            element_type="paragraph",
                            content=para_clean,
                        )
                    )

        # 2. Integrate Tables with Markdown Grids
        for tbl in doc.tables:
            elements.append(
                ContextElement(
                    element_type="table",
                    content=tbl.grid_markdown,
                    page_number=tbl.page_number,
                    metadata={"table_id": tbl.table_id, "rows": len(tbl.data_json)}
                )
            )

        # 3. Integrate Image Captions
        for img in doc.images:
            if img.ocr_text or img.caption:
                caption_text = img.caption or img.ocr_text or ""
                elements.append(
                    ContextElement(
                        element_type="image_caption",
                        content=f"[Image Caption: {caption_text}]",
                        page_number=img.page_number,
                        metadata={"image_id": img.image_id}
                    )
                )

        full_context = "\n\n".join([e.content for e in elements])
        return DocumentContextTree(
            document_id=doc.document_id,
            tenant_id=doc.tenant_id,
            title=doc.source,
            language_code=lang,
            elements=elements,
            full_context_text=full_context,
        )

document_context_builder = DocumentContextBuilder()
