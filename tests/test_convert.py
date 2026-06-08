import types
from pathlib import Path

import pytest

from mathscout.parsers.convert import (
    DocumentConverter,
    OcrNotConfiguredError,
)
from mathscout.parsers.detect import DocumentKind


def _converter(*, azure_endpoint: str | None = None) -> DocumentConverter:
    conv = DocumentConverter.__new__(DocumentConverter)
    conv.settings = types.SimpleNamespace(
        azure_doc_intel_endpoint=azure_endpoint,
        azure_doc_intel_key=None,
    )
    return conv


def test_html_conversion(tmp_path: Path):
    path = tmp_path / "page.html"
    path.write_bytes(
        b"<html><body><article><h1></h1>"
        b"<p>"
        + "数形结合比较有理数大小：先在数轴上标出两个数，再比较它们到原点的距离。".encode()
        + b"</p></article></body></html>"
    )
    result = _converter().convert(path, DocumentKind.html)
    assert result.converter == "trafilatura"
    assert "数轴" in result.text


def test_text_passthrough(tmp_path: Path):
    path = tmp_path / "note.txt"
    path.write_text("一元一次方程：移项时要变号。", encoding="utf-8")
    result = _converter().convert(path, DocumentKind.text)
    assert result.converter == "raw-text"
    assert "移项" in result.text


def test_image_without_azure_raises_ocr_not_configured(tmp_path: Path):
    path = tmp_path / "scan.png"
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16)
    with pytest.raises(OcrNotConfiguredError):
        _converter(azure_endpoint=None).convert(path, DocumentKind.image)


def test_unsupported_kind_raises_value_error(tmp_path: Path):
    path = tmp_path / "blob.zip"
    path.write_bytes(b"PK\x03\x04whatever")
    with pytest.raises(ValueError):
        _converter().convert(path, DocumentKind.archive)
