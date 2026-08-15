from __future__ import annotations

import shutil
from pathlib import Path

from conclave.config import settings
from conclave.db.session import DATA_DIR
from conclave.domain.redact import redact_pii

ALLOWED_SUFFIXES = {".md", ".txt", ".csv", ".json", ".pdf", ".docx"}
MAX_READ_CHARS = 12_000
MAX_PDF_PAGES = 50
# OCR is CPU-bound (~1-3s/page): cap pages so one scan can't stall a turn for minutes.
MAX_OCR_PAGES = 10

_ocr_engine = None


def _get_ocr():
    """Lazy singleton: RapidOCR loads its ONNX models once per process."""
    global _ocr_engine
    if _ocr_engine is None:
        from rapidocr_onnxruntime import RapidOCR

        _ocr_engine = RapidOCR()
    return _ocr_engine


def conversation_dir(conversation_id: str) -> Path:
    path = DATA_DIR / "conversations" / conversation_id
    path.mkdir(parents=True, exist_ok=True)
    (path / "files").mkdir(exist_ok=True)
    return path


def remove_conversation_dir(conversation_id: str) -> None:
    path = DATA_DIR / "conversations" / conversation_id
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)


def shared_doc_path(conversation_id: str) -> Path:
    return conversation_dir(conversation_id) / "shared.md"


def read_shared_doc(conversation_id: str) -> str:
    path = shared_doc_path(conversation_id)
    if not path.exists():
        path.write_text("# Shared document\n\n", encoding="utf-8")
    return path.read_text(encoding="utf-8")


def write_shared_doc(conversation_id: str, content: str) -> str:
    path = shared_doc_path(conversation_id)
    path.write_text(content, encoding="utf-8")
    return content


def edit_shared_doc(conversation_id: str, mode: str, content: str) -> str:
    current = read_shared_doc(conversation_id)
    if mode == "replace":
        return write_shared_doc(conversation_id, content)
    return write_shared_doc(conversation_id, current.rstrip() + "\n\n" + content.strip() + "\n")


def _ocr_pdf_text(p: Path) -> str:
    """OCR an image-only PDF locally (RapidOCR — nothing leaves the machine)."""
    try:
        import numpy as np
        import pypdfium2 as pdfium

        ocr = _get_ocr()
        pdf = pdfium.PdfDocument(str(p))
        try:
            pages: list[str] = []
            for i in range(len(pdf)):
                if i >= MAX_OCR_PAGES:
                    pages.append(f"…[{len(pdf) - MAX_OCR_PAGES} more pages not OCRed]")
                    break
                bitmap = pdf[i].render(scale=2.0)  # ~144 dpi: decent recognition, sane speed
                result, _ = ocr(np.array(bitmap.to_pil()))
                if result:
                    pages.append("\n".join(item[1] for item in result))
            return "\n\n".join(pages).strip()
        finally:
            pdf.close()
    except Exception:  # noqa: BLE001 — OCR failure degrades to the no-text note
        return ""


def _extract_pdf_text(p: Path) -> str:
    try:
        from pypdf import PdfReader

        reader = PdfReader(str(p))
        pages: list[str] = []
        for i, page in enumerate(reader.pages):
            if i >= MAX_PDF_PAGES:
                pages.append(f"…[{len(reader.pages) - MAX_PDF_PAGES} more pages truncated]")
                break
            pages.append(page.extract_text() or "")
        text = "\n\n".join(pages).strip()
        if text:
            return text
        ocr_text = _ocr_pdf_text(p)
        if ocr_text:
            return "[OCR — may contain recognition errors]\n" + ocr_text
        return "[PDF contains no extractable text — likely a scanned image]"
    except Exception:  # noqa: BLE001 — malformed uploads must not break a turn
        return "[PDF could not be parsed]"


def _extract_docx_text(p: Path) -> str:
    try:
        import docx

        d = docx.Document(str(p))
        parts = [para.text for para in d.paragraphs if para.text.strip()]
        for table in d.tables:
            for row in table.rows:
                parts.append(" | ".join(cell.text.strip() for cell in row.cells))
        text = "\n".join(parts).strip()
        return text or "[Word document contains no extractable text]"
    except Exception:  # noqa: BLE001 — malformed uploads must not break a turn
        return "[Word document could not be parsed]"


def read_attachment_text(path: str) -> str:
    p = Path(path)
    if not p.exists():
        return ""
    suffix = p.suffix.lower()
    if suffix == ".pdf":
        text = _extract_pdf_text(p)
    elif suffix == ".docx":
        text = _extract_docx_text(p)
    else:
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""
    if settings.redact_pii:
        text = redact_pii(text)
    if len(text) > MAX_READ_CHARS:
        return text[:MAX_READ_CHARS] + "\n…[truncated]"
    return text
