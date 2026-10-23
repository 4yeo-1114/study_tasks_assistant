from io import BytesIO

from knowledge.document_ingestion import ParsedPage


class UnsupportedPdfError(ValueError):
    """Raised when a PDF has no extractable text, usually a scanned PDF."""


def extract_pdf_pages(data: bytes) -> list[ParsedPage]:
    if not data:
        raise UnsupportedPdfError("PDF 为空或不是可解析的文本 PDF")
    try:
        from pypdf import PdfReader

        reader = PdfReader(BytesIO(data))
        pages = [
            ParsedPage(index, (page.extract_text() or "").strip())
            for index, page in enumerate(reader.pages, start=1)
        ]
    except Exception as exc:
        raise UnsupportedPdfError("PDF 无法解析；暂不支持扫描件或加密 PDF") from exc
    pages = [page for page in pages if page.text]
    if not pages:
        raise UnsupportedPdfError("未提取到文本；扫描 PDF 暂不支持 OCR")
    return pages
