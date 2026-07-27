"""
Content Normalizer Module
=========================
Normalizes raw extracted content prior to chunking & AI processing.
Responsibilities:
  - UTF-8 clean and Unicode NFKC normalization
  - Whitespace and line-break consolidation
  - Bullet character unification (*, -, • ➔ •)
  - Markdown table grid formatting clean
  - Section heading standardization
"""
import re
import unicodedata
from typing import List
from app.domain.models import ExtractedDocument, ExtractedSection, ExtractedTable

class ContentNormalizer:
    """Enterprise Content Normalizer."""

    @staticmethod
    def normalize_text(text: str) -> str:
        if not text:
            return ""
        # 1. Unicode NFKC Normalization
        text = unicodedata.normalize("NFKC", text)
        
        # 2. Fix UTF-8 replacement characters
        text = text.replace("\ufffd", "").replace("\x00", "")

        # 3. Unify Bullet Characters (*, -, +, •) to standard '•'
        text = re.sub(r"^[ \t]*[*+\-][ \t]+", "• ", text, flags=re.MULTILINE)

        # 4. Standardize multiple newlines (max 2 consecutive newlines)
        text = re.sub(r"\n{3,}", "\n\n", text)

        # 5. Clean trailing/leading whitespace per line
        lines = [line.strip() for line in text.splitlines()]
        return "\n".join(lines).strip()

    def normalize_document(self, doc: ExtractedDocument) -> ExtractedDocument:
        """Normalizes an entire ExtractedDocument instance in-place."""
        doc.clean_text = self.normalize_text(doc.clean_text)
        
        for sec in doc.sections:
            sec.heading = self.normalize_text(sec.heading)
            sec.content = self.normalize_text(sec.content)

        for tbl in doc.tables:
            tbl.grid_markdown = self.normalize_text(tbl.grid_markdown)

        return doc

content_normalizer = ContentNormalizer()
