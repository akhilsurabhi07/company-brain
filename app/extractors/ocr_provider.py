import io
from typing import Optional
from PIL import Image
from app.interfaces.extractor_interfaces import OCRProvider

class TesseractOCRProvider(OCRProvider):
    """
    Tesseract 5 OCR Engine Implementation.
    Parses scanned images (PNG, JPEG, TIFF) and image-based PDFs.
    Includes graceful fallback handling if Tesseract binary is omitted.
    """

    def __init__(self):
        self._tesseract_available = False
        try:
            import pytesseract
            self._pytesseract = pytesseract
            self._tesseract_available = True
        except ImportError:
            self._pytesseract = None

    def extract_text_from_image_bytes(self, image_bytes: bytes, mime_type: str = "image/png") -> str:
        """Extracts text from image binary bytes using Tesseract 5 OCR."""
        if not image_bytes:
            return ""

        try:
            image = Image.open(io.BytesIO(image_bytes))
            if image.mode not in ("L", "RGB"):
                image = image.convert("RGB")

            if self._tesseract_available and self._pytesseract:
                text = self._pytesseract.image_to_string(image)
                return text.strip()
            else:
                return f"[OCR Fallback: Image ({image.width}x{image.height} px, format={image.format}) - Tesseract engine offline]"
        except Exception as e:
            return f"[OCR Error processing image: {str(e)}]"

    def extract_text_from_scanned_pdf(self, pdf_bytes: bytes) -> str:
        """Extracts text from scanned PDF by rendering pages to images and running OCR."""
        if not pdf_bytes:
            return ""

        extracted_text_pages = []
        try:
            import fitz  # PyMuPDF
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            for page_num in range(len(doc)):
                page = doc[page_num]
                pix = page.get_pixmap(dpi=150)
                img_bytes = pix.tobytes("png")
                page_text = self.extract_text_from_image_bytes(img_bytes, mime_type="image/png")
                if page_text:
                    extracted_text_pages.append(f"--- Page {page_num + 1} (OCR) ---\n{page_text}")
            doc.close()
            return "\n\n".join(extracted_text_pages)
        except Exception as e:
            return f"[OCR Error processing scanned PDF: {str(e)}]"

# Default singleton provider
default_ocr_provider = TesseractOCRProvider()
