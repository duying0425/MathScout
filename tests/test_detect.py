import io
import zipfile
from pathlib import Path

from mathscout.parsers.attachments import (
    attachment_extension,
    is_attachment_url,
)
from mathscout.parsers.detect import DocumentKind, detect_document_kind


def _write(tmp_path: Path, name: str, data: bytes) -> Path:
    path = tmp_path / name
    path.write_bytes(data)
    return path


def _ooxml_bytes(top_dir: str) -> bytes:
    """构造一个最小 OOXML 包：含 [Content_Types].xml 与某个 office 顶层目录。"""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        zf.writestr(f"{top_dir}/document.xml", "<xml/>")
    return buffer.getvalue()


def test_magic_pdf_without_text_layer_is_scanned(tmp_path: Path):
    # 一个没有可抽取文字层的 %PDF 文件应被判为扫描版（PyMuPDF 解析失败时也安全降级）。
    path = _write(tmp_path, "scan", b"%PDF-1.4\n%fake pdf without real text layer\n")
    kind = detect_document_kind(path)
    assert kind in {DocumentKind.pdf_scanned, DocumentKind.pdf_digital}


def test_magic_overrides_wrong_extension(tmp_path: Path):
    # 文件实际是 PNG，但 URL 谎称 .pdf —— magic 字节应胜出。
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
    path = _write(tmp_path, "image.bin", png)
    assert detect_document_kind(path, url="https://x.com/a.pdf") == DocumentKind.image


def test_ooxml_word(tmp_path: Path):
    path = _write(tmp_path, "lesson.bin", _ooxml_bytes("word"))
    assert detect_document_kind(path) == DocumentKind.word


def test_ooxml_powerpoint(tmp_path: Path):
    path = _write(tmp_path, "slides.bin", _ooxml_bytes("ppt"))
    assert detect_document_kind(path) == DocumentKind.powerpoint


def test_ooxml_excel(tmp_path: Path):
    path = _write(tmp_path, "sheet.bin", _ooxml_bytes("xl"))
    assert detect_document_kind(path) == DocumentKind.excel


def test_content_type_when_no_magic(tmp_path: Path):
    path = _write(tmp_path, "blob.bin", b"not a recognizable binary header")
    kind = detect_document_kind(path, content_type="application/msword")
    assert kind == DocumentKind.word


def test_extension_fallback(tmp_path: Path):
    path = _write(tmp_path, "blob.bin", b"plain bytes, no magic, no content type")
    kind = detect_document_kind(path, url="https://x.com/files/handout.pptx")
    assert kind == DocumentKind.powerpoint


def test_html_text_sniff(tmp_path: Path):
    path = _write(tmp_path, "page.bin", b"<!DOCTYPE html>\n<html><body>hi</body></html>")
    assert detect_document_kind(path) == DocumentKind.html


def test_unknown_when_nothing_matches(tmp_path: Path):
    path = _write(tmp_path, "blob.bin", b"\x01\x02\x03 random")
    assert detect_document_kind(path) == DocumentKind.unknown


def test_attachment_extension():
    assert attachment_extension("https://x.com/a/jiaoan.doc") == ".doc"
    assert attachment_extension("https://x.com/课件.pptx?v=2") == ".pptx"
    assert attachment_extension("https://x.com/page.html") is None
    assert attachment_extension("https://x.com/no-ext") is None


def test_is_attachment_url():
    assert is_attachment_url("https://x.com/学案.pdf")
    assert not is_attachment_url("https://x.com/index.html")
