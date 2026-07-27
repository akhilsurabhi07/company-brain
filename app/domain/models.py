from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

class ExtractedPage(BaseModel):
    page_id: Optional[str] = None
    page_number: int
    width: Optional[int] = None
    height: Optional[int] = None
    page_text: str = ""
    layout_bbox: Dict[str, Any] = Field(default_factory=dict)

class ExtractedSection(BaseModel):
    section_id: Optional[str] = None
    page_id: Optional[str] = None
    parent_section_id: Optional[str] = None
    heading: str
    level: int = 1
    content: str
    token_count: int = 0

class ExtractedTable(BaseModel):
    table_id: Optional[str] = None
    page_id: Optional[str] = None
    page_number: Optional[int] = None
    table_number: int = 1
    rows_count: int = 0
    cols_count: int = 0
    grid_markdown: str      # Markdown grid representation
    data_json: List[Dict[str, Any]] = Field(default_factory=list)
    data_csv: Optional[str] = None
    confidence: float = 1.0

class ExtractedImage(BaseModel):
    image_id: Optional[str] = None
    page_id: Optional[str] = None
    page_number: Optional[int] = None
    image_index: int = 1
    mime_type: str = "image/png"
    image_hash: Optional[str] = None
    caption: Optional[str] = None
    s3_key: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None

class ExtractedOCR(BaseModel):
    ocr_id: Optional[str] = None
    image_id: Optional[str] = None
    page_id: Optional[str] = None
    ocr_engine: str = "Tesseract 5"
    confidence: float = 1.0
    ocr_text: str

class ExtractedDocument(BaseModel):
    tenant_id: str
    document_id: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
    clean_text: str
    pages: List[ExtractedPage] = Field(default_factory=list)
    sections: List[ExtractedSection] = Field(default_factory=list)
    tables: List[ExtractedTable] = Field(default_factory=list)
    images: List[ExtractedImage] = Field(default_factory=list)
    ocr_records: List[ExtractedOCR] = Field(default_factory=list)
    captions: List[str] = Field(default_factory=list)
    source: str
    checksum: str
    timestamps: Dict[str, str] = Field(default_factory=dict)
