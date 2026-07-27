import io
import uuid
from typing import Any, Dict, List, Optional
from app.domain.models import ExtractedTable
from app.interfaces.extractor_interfaces import TableExtractor

class PDFTableExtractor(TableExtractor):
    """
    Table Extractor using pdfplumber.
    Extracts tables from PDF files and converts each table into:
    1. Structured JSON (list of row dicts / lists)
    2. Markdown Grid representation (e.g. "| Col A | Col B |\n| --- | --- |\n| Val A | Val B |")
    """

    def __init__(self):
        self._pdfplumber_available = False
        try:
            import pdfplumber
            self._pdfplumber = pdfplumber
            self._pdfplumber_available = True
        except ImportError:
            self._pdfplumber = None

    def extract_tables_from_pdf(self, pdf_bytes: bytes) -> List[ExtractedTable]:
        if not pdf_bytes or not self._pdfplumber_available or not self._pdfplumber:
            return []

        extracted_tables: List[ExtractedTable] = []
        try:
            with self._pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                for page_num, page in enumerate(pdf.pages, start=1):
                    tables = page.extract_tables()
                    for t_idx, table in enumerate(tables):
                        if not table or len(table) < 2:
                            continue  # Skip empty or single-cell tables

                        # Clean null values in rows
                        clean_rows = []
                        for row in table:
                            clean_rows.append([str(cell or "").strip().replace("\n", " ") for cell in row])

                        headers = clean_rows[0]
                        data_rows = clean_rows[1:]

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

                        extracted_tables.append(
                            ExtractedTable(
                                table_id=f"tbl_page_{page_num}_{t_idx+1}_{str(uuid.uuid4())[:6]}",
                                page_number=page_num,
                                grid_markdown=grid_markdown,
                                data_json=data_json,
                            )
                        )
        except Exception:
            pass  # Fallback to empty table list if pdfplumber encounters invalid PDF structure

        return extracted_tables

    def extract_tables_from_text(self, text_content: str) -> List[ExtractedTable]:
        """Parses markdown grids embedded inside text content."""
        if not text_content:
            return []

        tables = []
        lines = text_content.splitlines()
        in_table = False
        current_table_lines = []

        for line in lines:
            stripped = line.strip()
            if stripped.startswith("|") and stripped.endswith("|"):
                in_table = True
                current_table_lines.append(stripped)
            else:
                if in_table and len(current_table_lines) >= 2:
                    grid = "\n".join(current_table_lines)
                    tables.append(ExtractedTable(
                        table_id=f"tbl_text_{str(uuid.uuid4())[:6]}",
                        page_number=None,
                        grid_markdown=grid,
                        data_json=[]
                    ))
                in_table = False
                current_table_lines = []

        if in_table and len(current_table_lines) >= 2:
            grid = "\n".join(current_table_lines)
            tables.append(ExtractedTable(
                table_id=f"tbl_text_{str(uuid.uuid4())[:6]}",
                page_number=None,
                grid_markdown=grid,
                data_json=[]
            ))

        return tables

default_table_extractor = PDFTableExtractor()
