"""文档类型识别。

抓取来的内容常常缺少可靠的扩展名（URL 没后缀），或带着错误/笼统的
`Content-Type`（如 application/octet-stream）。因此用三层确定性策略判断类型：

1. 文件 magic 字节（最可靠，不受表层元数据影响）
2. `Content-Type` 头
3. URL 扩展名

对 PDF 还会用 PyMuPDF 探测是否存在文字层，区分"数字版 PDF"（直接抽文本）与
"扫描版 PDF"（需 OCR）。识别结果用于：选择转换器、决定是否调用（付费的）Azure
OCR、以及在后台标记 `needs_ocr` 让人工可见。

本模块不依赖 markitdown，可独立测试。PyMuPDF 探测在缺失时安全降级为"数字版"。
"""

from __future__ import annotations

import zipfile
from enum import StrEnum
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse


class DocumentKind(StrEnum):
    html = "html"
    pdf_digital = "pdf_digital"
    pdf_scanned = "pdf_scanned"
    word = "word"
    powerpoint = "powerpoint"
    excel = "excel"
    image = "image"
    text = "text"
    archive = "archive"
    unknown = "unknown"


# 需要 OCR（扫描件/图片）的类型——转换层据此决定是否走 Azure 文档智能。
OCR_KINDS = frozenset({DocumentKind.pdf_scanned, DocumentKind.image})

# 扩展名 → 类型；".pdf" 用占位符 "pdf"，最终由文字层探测决定 digital/scanned。
_EXT_KIND: dict[str, DocumentKind | str] = {
    ".pdf": "pdf",
    ".doc": DocumentKind.word,
    ".docx": DocumentKind.word,
    ".rtf": DocumentKind.word,
    ".odt": DocumentKind.word,
    ".ppt": DocumentKind.powerpoint,
    ".pptx": DocumentKind.powerpoint,
    ".odp": DocumentKind.powerpoint,
    ".xls": DocumentKind.excel,
    ".xlsx": DocumentKind.excel,
    ".csv": DocumentKind.excel,
    ".ods": DocumentKind.excel,
    ".html": DocumentKind.html,
    ".htm": DocumentKind.html,
    ".txt": DocumentKind.text,
    ".md": DocumentKind.text,
    ".json": DocumentKind.text,
    ".xml": DocumentKind.text,
    ".jpg": DocumentKind.image,
    ".jpeg": DocumentKind.image,
    ".png": DocumentKind.image,
    ".gif": DocumentKind.image,
    ".bmp": DocumentKind.image,
    ".tif": DocumentKind.image,
    ".tiff": DocumentKind.image,
    ".webp": DocumentKind.image,
    ".zip": DocumentKind.archive,
    ".rar": DocumentKind.archive,
    ".7z": DocumentKind.archive,
}


def detect_document_kind(
    raw_path: Path,
    content_type: str | None = None,
    url: str | None = None,
) -> DocumentKind:
    """识别文档类型。优先 magic 字节，其次 Content-Type，再次 URL 扩展名。"""
    header = _read_header(raw_path)
    base = _sniff_magic(header)

    if base == "zip":
        base = _ooxml_kind(raw_path)
    elif base == "ole2":
        base = _legacy_office_kind(content_type, url)

    if base is None:
        base = _kind_from_content_type(content_type)
    if base is None and url:
        base = _kind_from_extension(url)
    if base is None and _looks_like_html(header):
        base = DocumentKind.html
    if base is None:
        base = DocumentKind.unknown

    if base == "pdf":
        if pdf_has_text_layer(raw_path):
            return DocumentKind.pdf_digital
        return DocumentKind.pdf_scanned
    return base


def pdf_has_text_layer(path: Path, max_pages: int = 5, min_chars: int = 20) -> bool:
    """探测 PDF 前若干页是否有可抽取文字层。无法探测时保守返回 True（当作数字版）。"""
    try:
        import fitz
    except ImportError:
        return True
    try:
        doc = fitz.open(path)
    except Exception:
        return True
    chars = 0
    for index, page in enumerate(doc):
        if index >= max_pages:
            break
        chars += len(page.get_text("text").strip())
        if chars >= min_chars:
            return True
    return chars >= min_chars


def _read_header(raw_path: Path, size: int = 2048) -> bytes:
    try:
        with open(raw_path, "rb") as handle:
            return handle.read(size)
    except OSError:
        return b""


def _sniff_magic(header: bytes) -> DocumentKind | str | None:
    if header.startswith(b"%PDF"):
        return "pdf"
    if header[:8] == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
        return "ole2"  # 旧版 Office（.doc/.ppt/.xls）
    if header[:4] == b"PK\x03\x04":
        return "zip"  # 可能是 OOXML（docx/pptx/xlsx）或普通 zip
    if header[:3] == b"\xff\xd8\xff":
        return DocumentKind.image  # jpeg
    if header[:8] == b"\x89PNG\r\n\x1a\n":
        return DocumentKind.image  # png
    if header[:4] == b"GIF8":
        return DocumentKind.image  # gif
    if header[:2] == b"BM":
        return DocumentKind.image  # bmp
    if header[:4] in (b"II*\x00", b"MM\x00*"):
        return DocumentKind.image  # tiff
    if header[:4] == b"RIFF" and header[8:12] == b"WEBP":
        return DocumentKind.image  # webp
    return None


def _ooxml_kind(path: Path) -> DocumentKind:
    try:
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
    except (zipfile.BadZipFile, OSError):
        return DocumentKind.archive
    if any(name.startswith("word/") for name in names):
        return DocumentKind.word
    if any(name.startswith("ppt/") for name in names):
        return DocumentKind.powerpoint
    if any(name.startswith("xl/") for name in names):
        return DocumentKind.excel
    return DocumentKind.archive


def _legacy_office_kind(content_type: str | None, url: str | None) -> DocumentKind:
    by_ext = _kind_from_extension(url) if url else None
    if by_ext in {DocumentKind.word, DocumentKind.powerpoint, DocumentKind.excel}:
        return by_ext
    by_ct = _kind_from_content_type(content_type)
    if by_ct in {DocumentKind.word, DocumentKind.powerpoint, DocumentKind.excel}:
        return by_ct
    return DocumentKind.word  # OLE2 几乎都是 Office，默认按 Word 处理


def _kind_from_content_type(content_type: str | None) -> DocumentKind | str | None:
    ct = (content_type or "").lower()
    if not ct:
        return None
    if "pdf" in ct:
        return "pdf"
    if "html" in ct:
        return DocumentKind.html
    if "wordprocessingml" in ct or "msword" in ct:
        return DocumentKind.word
    if "presentationml" in ct or "powerpoint" in ct:
        return DocumentKind.powerpoint
    if "spreadsheetml" in ct or "ms-excel" in ct or "csv" in ct:
        return DocumentKind.excel
    if ct.startswith("image/"):
        return DocumentKind.image
    if ct.startswith("text/") or "json" in ct or "xml" in ct:
        return DocumentKind.text
    if "zip" in ct:
        return DocumentKind.archive
    return None


def _kind_from_extension(url: str) -> DocumentKind | str | None:
    ext = PurePosixPath(urlparse(url).path).suffix.lower()
    return _EXT_KIND.get(ext)


def _looks_like_html(header: bytes) -> bool:
    lowered = header.lstrip().lower()
    return lowered.startswith((b"<!doctype html", b"<html")) or b"<html" in header[:1024].lower()
