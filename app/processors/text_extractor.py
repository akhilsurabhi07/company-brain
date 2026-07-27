import io
from typing import Optional
from pypdf import PdfReader
from docx import Document

class TextExtractor:
    """
    Document Text Extraction Engine for PDFs, Word Docs, and Text Files.
    Parses attached files from Google Drive, Slack, Confluence, etc. into plain text.
    """

    @staticmethod
    def extract_from_pdf(file_bytes: bytes) -> str:
        """Extracts text content from PDF binary bytes."""
        try:
            reader = PdfReader(io.BytesIO(file_bytes))
            text_parts = []
            for page in reader.pages:
                text = page.extract_text()
                if text:
                    text_parts.append(text)
            return "\n".join(text_parts)
        except Exception as e:
            return f"[PDF Parsing Error: {str(e)}]"

    @staticmethod
    def extract_from_docx(file_bytes: bytes) -> str:
        """Extracts text content from Word (.docx) binary bytes."""
        try:
            doc = Document(io.BytesIO(file_bytes))
            return "\n".join([paragraph.text for paragraph in doc.paragraphs if paragraph.text])
        except Exception as e:
            return f"[DOCX Parsing Error: {str(e)}]"

    @staticmethod
    def extract_from_file(file_bytes: bytes, mime_type: str, filename: str = "") -> str:
        """Dynamically routes file bytes to appropriate text extractor."""
        filename_lower = filename.lower()
        
        if mime_type == "application/pdf" or filename_lower.endswith(".pdf"):
            return TextExtractor.extract_from_pdf(file_bytes)
        elif (
            mime_type == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
            or filename_lower.endswith(".docx")
        ):
            return TextExtractor.extract_from_docx(file_bytes)
        elif mime_type.startswith("text/") or filename_lower.endswith((".txt", ".md", ".py", ".json", ".csv")):
            try:
                return file_bytes.decode("utf-8")
            except UnicodeDecodeError:
                return file_bytes.decode("latin-1", errors="ignore")
                
        return ""

text_extractor = TextExtractor()
