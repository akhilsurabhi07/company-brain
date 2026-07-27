import hashlib
import io
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple
from app.domain.models import ExtractedDocument, ExtractedImage, ExtractedSection, ExtractedTable
from app.interfaces.extractor_interfaces import DocumentExtractor

class DOCXPPTXExtractor(DocumentExtractor):
    """
    Document Extractor for Word (.docx), PowerPoint (.pptx), Plaintext (.txt), and Markdown (.md).
    Extracts structured text, headings, tables (JSON + Markdown grids), and embedded metadata.
    """

    @property
    def supported_mime_types(self) -> List[str]:
        return [
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            "text/plain",
            "text/markdown",
        ]

    @property
    def supported_extensions(self) -> List[str]:
        return [".docx", ".pptx", ".txt", ".md"]

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
        ext = "." + filename.split(".")[-1].lower() if "." in filename else ""

        clean_text_paragraphs: List[str] = []
        sections: List[ExtractedSection] = []
        tables: List[ExtractedTable] = []

        if ext == ".docx":
            clean_text_paragraphs, sections, tables = self._extract_docx(file_bytes)
        elif ext == ".pptx":
            clean_text_paragraphs, sections = self._extract_pptx(file_bytes)
        else:
            # Plaintext / Markdown
            text_str = file_bytes.decode("utf-8", errors="ignore")
            clean_text_paragraphs = [text_str]
            sections = [ExtractedSection(section_id="sec_1", heading="Main Document", level=1, content=text_str)]

        full_clean_text = "\n\n".join(clean_text_paragraphs)

        return ExtractedDocument(
            tenant_id=tenant_id,
            document_id=document_id,
            metadata={
                **metadata,
                "filename": filename,
                "file_extension": ext,
                "total_tables": len(tables),
            },
            clean_text=full_clean_text,
            sections=sections,
            tables=tables,
            images=[],
            captions=[],
            source=f"doc:{filename}",
            checksum=checksum,
            timestamps={
                "extracted_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            },
        )

    def _extract_docx(self, file_bytes: bytes) -> Tuple[List[str], List[ExtractedSection], List[ExtractedTable]]:
        paragraphs_text = []
        sections = []
        tables = []

        try:
            import docx
            doc = docx.Document(io.BytesIO(file_bytes))

            current_heading = "Document Root"
            current_lines = []

            for p in doc.paragraphs:
                p_text = p.text.strip()
                if not p_text:
                    continue

                paragraphs_text.append(p_text)
                if p.style and p.style.name.startswith("Heading"):
                    if current_lines:
                        sections.append(ExtractedSection(
                            section_id=f"sec_{len(sections)+1}",
                            heading=current_heading,
                            level=1,
                            content="\n".join(current_lines)
                        ))
                        current_lines = []
                    current_heading = p_text
                else:
                    current_lines.append(p_text)

            if current_lines:
                sections.append(ExtractedSection(
                    section_id=f"sec_{len(sections)+1}",
                    heading=current_heading,
                    level=1,
                    content="\n".join(current_lines)
                ))

            # Extract DOCX tables into JSON + Markdown grid
            for t_idx, table in enumerate(doc.tables, start=1):
                raw_grid = []
                for row in table.rows:
                    raw_grid.append([cell.text.strip().replace("\n", " ") for cell in row.cells])

                if len(raw_grid) >= 2:
                    headers = raw_grid[0]
                    data_rows = raw_grid[1:]

                    header_line = "| " + " | ".join(headers) + " |"
                    separator_line = "| " + " | ".join(["---"] * len(headers)) + " |"
                    body_lines = ["| " + " | ".join(r) + " |" for r in data_rows]
                    grid_markdown = "\n".join([header_line, separator_line] + body_lines)

                    data_json = []
                    for r in data_rows:
                        row_dict = {}
                        for c_idx, c_name in enumerate(headers):
                            val = r[c_idx] if c_idx < len(r) else ""
                            key = c_name if c_name else f"col_{c_idx+1}"
                            row_dict[key] = val
                        data_json.append(row_dict)

                    tables.append(ExtractedTable(
                        table_id=f"tbl_docx_{t_idx}_{str(uuid.uuid4())[:6]}",
                        page_number=None,
                        grid_markdown=grid_markdown,
                        data_json=data_json,
                    ))

        except Exception:
            text_fallback = file_bytes.decode("utf-8", errors="ignore")
            paragraphs_text.append(text_fallback)
            sections.append(ExtractedSection(section_id="sec_1", heading="Fallback", level=1, content=text_fallback))

        return paragraphs_text, sections, tables

    def _extract_pptx(self, file_bytes: bytes) -> Tuple[List[str], List[ExtractedSection]]:
        slides_text = []
        sections = []

        try:
            import pptx
            prs = pptx.Presentation(io.BytesIO(file_bytes))
            for idx, slide in enumerate(prs.slides, start=1):
                slide_lines = []
                title = f"Slide {idx}"

                for shape in slide.shapes:
                    if hasattr(shape, "text") and shape.text.strip():
                        txt = shape.text.strip()
                        slide_lines.append(txt)
                        if hasattr(shape, "is_placeholder") and shape.is_placeholder:
                            title = txt[:50]

                combined_slide = "\n".join(slide_lines)
                if combined_slide:
                    slides_text.append(combined_slide)
                    sections.append(ExtractedSection(
                        section_id=f"sec_slide_{idx}",
                        heading=title,
                        level=1,
                        content=combined_slide
                    ))

        except Exception:
            text_fallback = file_bytes.decode("utf-8", errors="ignore")
            slides_text.append(text_fallback)
            sections.append(ExtractedSection(section_id="sec_1", heading="Fallback", level=1, content=text_fallback))

        return slides_text, sections

docx_pptx_extractor = DOCXPPTXExtractor()
