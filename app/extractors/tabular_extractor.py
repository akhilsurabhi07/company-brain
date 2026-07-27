import csv
import hashlib
import io
import time
import uuid
from typing import Any, Dict, List, Optional, Tuple
from app.domain.models import ExtractedDocument, ExtractedSection, ExtractedTable
from app.interfaces.extractor_interfaces import DocumentExtractor

class TabularExtractor(DocumentExtractor):
    """
    Document Extractor for Tabular Data (CSV, TSV, HTML tables).
    Converts spreadsheets into:
    1. Structured JSON (list of row dicts)
    2. Markdown Grid representation (e.g. "| Col A | Col B |\n| --- | --- |\n| Val A | Val B |")
    """

    @property
    def supported_mime_types(self) -> List[str]:
        return [
            "text/csv",
            "text/tab-separated-values",
            "text/html",
        ]

    @property
    def supported_extensions(self) -> List[str]:
        return [".csv", ".tsv", ".html", ".htm"]

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

        text_content = file_bytes.decode("utf-8", errors="ignore")
        tables: List[ExtractedTable] = []
        clean_text = ""

        if ext in (".csv", ".tsv") or mime_type in ("text/csv", "text/tab-separated-values"):
            delimiter = "\t" if (ext == ".tsv" or mime_type == "text/tab-separated-values") else ","
            tables, clean_text = self._parse_csv(text_content, delimiter)
        else:
            clean_text = text_content

        sections = [
            ExtractedSection(
                section_id="sec_tabular_1",
                heading=f"Tabular Data: {filename}",
                level=1,
                content=clean_text,
            )
        ]

        return ExtractedDocument(
            tenant_id=tenant_id,
            document_id=document_id,
            metadata={
                **metadata,
                "filename": filename,
                "file_extension": ext,
                "total_tables": len(tables),
            },
            clean_text=clean_text,
            sections=sections,
            tables=tables,
            images=[],
            captions=[],
            source=f"tabular:{filename}",
            checksum=checksum,
            timestamps={
                "extracted_at": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            },
        )

    def _parse_csv(self, text_content: str, delimiter: str = ",") -> Tuple[List[ExtractedTable], str]:
        reader = csv.reader(io.StringIO(text_content), delimiter=delimiter)
        rows = [row for row in reader if row]

        if not rows:
            return [], ""

        headers = [str(c).strip().replace("\n", " ") for c in rows[0]]
        data_rows = [[str(c).strip().replace("\n", " ") for c in row] for row in rows[1:]]

        # 1. Build Markdown Grid Representation
        header_line = "| " + " | ".join(headers) + " |"
        separator_line = "| " + " | ".join(["---"] * len(headers)) + " |"
        body_lines = ["| " + " | ".join(row) + " |" for row in data_rows]
        grid_markdown = "\n".join([header_line, separator_line] + body_lines)

        # 2. Build Structured JSON
        data_json = []
        for row in data_rows:
            row_dict = {}
            for col_idx, col_name in enumerate(headers):
                val = row[col_idx] if col_idx < len(row) else ""
                key = col_name if col_name else f"col_{col_idx+1}"
                row_dict[key] = val
            data_json.append(row_dict)

        table = ExtractedTable(
            table_id=f"tbl_csv_{str(uuid.uuid4())[:6]}",
            page_number=1,
            grid_markdown=grid_markdown,
            data_json=data_json,
        )

        clean_text_summary = f"CSV Table with {len(data_rows)} rows and {len(headers)} columns:\n\n{grid_markdown}"
        return [table], clean_text_summary

tabular_extractor = TabularExtractor()
