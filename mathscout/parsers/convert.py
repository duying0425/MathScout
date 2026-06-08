"""统一文档转换层：把抓取来的原始文件转成供 Phase 2 抽取的文本（Markdown）。

各格式用最擅长的工具：

- HTML        → trafilatura（更会去导航/广告噪声）
- 数字版 PDF  → PyMuPDF（快、已是依赖）
- 扫描版 PDF / 图片 → Azure 文档智能（经 markitdown 调用，需配置；未配置则抛
  `OcrNotConfiguredError`，由上层标记 needs_ocr）
- Word/PPT/Excel → markitdown（docx/pptx/xlsx 转 Markdown，保留标题/表格结构）
- 纯文本/CSV/JSON → 直接读取

markitdown 采用懒加载：未安装时只影响 Office/扫描件路径，HTML/数字 PDF 不受影响。
"""

from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from mathscout.config import Settings, get_settings
from mathscout.parsers.detect import DocumentKind
from mathscout.parsers.html import html_to_text
from mathscout.parsers.pdf import pdf_to_text


class OcrNotConfiguredError(RuntimeError):
    """需要 OCR（扫描件/图片）但未配置 Azure 文档智能。"""


class MarkItDownNotInstalledError(RuntimeError):
    """需要 markitdown 但未安装。"""


@dataclass
class ConversionResult:
    text: str
    kind: DocumentKind
    converter: str
    used_ocr: bool = False
    warnings: list[str] = field(default_factory=list)


# 由 markitdown 处理的 Office 类型，及其规范扩展名（确保 markitdown 选对转换器）。
_OFFICE_SUFFIX = {
    DocumentKind.word: ".docx",
    DocumentKind.powerpoint: ".pptx",
    DocumentKind.excel: ".xlsx",
}


class DocumentConverter:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def convert(self, raw_path: Path, kind: DocumentKind) -> ConversionResult:
        if kind == DocumentKind.html:
            html = raw_path.read_bytes().decode("utf-8", errors="ignore")
            return ConversionResult(text=html_to_text(html), kind=kind, converter="trafilatura")
        if kind == DocumentKind.pdf_digital:
            return ConversionResult(text=pdf_to_text(raw_path), kind=kind, converter="pymupdf")
        if kind == DocumentKind.text:
            text = raw_path.read_bytes().decode("utf-8", errors="ignore").strip()
            return ConversionResult(text=text, kind=kind, converter="raw-text")
        if kind in {DocumentKind.pdf_scanned, DocumentKind.image}:
            return self._convert_with_ocr(raw_path, kind)
        if kind in _OFFICE_SUFFIX:
            return self._convert_office(raw_path, kind)
        raise ValueError(f"不支持的文档类型：{kind.value}")

    # ------------------------------------------------------------------ #

    def _convert_office(self, raw_path: Path, kind: DocumentKind) -> ConversionResult:
        text = self._run_markitdown(raw_path, suffix=_OFFICE_SUFFIX[kind])
        return ConversionResult(text=text, kind=kind, converter="markitdown")

    def _convert_with_ocr(self, raw_path: Path, kind: DocumentKind) -> ConversionResult:
        if not self.settings.azure_doc_intel_endpoint:
            raise OcrNotConfiguredError(
                "扫描件/图片需要 OCR，但未配置 Azure 文档智能"
                "（AZURE_DOC_INTEL_ENDPOINT）。"
            )
        suffix = ".pdf" if kind == DocumentKind.pdf_scanned else (raw_path.suffix or ".png")
        text = self._run_markitdown(raw_path, suffix=suffix, use_docintel=True)
        return ConversionResult(
            text=text, kind=kind, converter="markitdown-docintel", used_ocr=True
        )

    def _run_markitdown(self, raw_path: Path, suffix: str, use_docintel: bool = False) -> str:
        md = self._build_markitdown(use_docintel=use_docintel)
        # markitdown 按扩展名选择转换器；确保临时文件后缀正确。
        if raw_path.suffix.lower() == suffix.lower():
            target, cleanup = raw_path, None
        else:
            handle = tempfile.NamedTemporaryFile(suffix=suffix, delete=False)
            handle.close()
            cleanup = Path(handle.name)
            shutil.copyfile(raw_path, cleanup)
            target = cleanup
        try:
            result = md.convert(str(target))
        finally:
            if cleanup is not None:
                cleanup.unlink(missing_ok=True)
        return (getattr(result, "text_content", "") or "").strip()

    def _build_markitdown(self, use_docintel: bool):
        try:
            from markitdown import MarkItDown
        except ImportError as exc:
            raise MarkItDownNotInstalledError(
                "未安装 markitdown，无法转换 Office/扫描件；请运行 "
                'pip install -e ".[dev]"。'
            ) from exc

        if not (use_docintel and self.settings.azure_doc_intel_endpoint):
            return MarkItDown(enable_plugins=False)

        endpoint = self.settings.azure_doc_intel_endpoint
        key = self.settings.azure_doc_intel_key
        if key:
            # 若该版本 markitdown 支持 key 凭据则用之，否则退回端点 + 默认 Azure 凭据。
            try:
                from azure.core.credentials import AzureKeyCredential

                return MarkItDown(
                    enable_plugins=False,
                    docintel_endpoint=endpoint,
                    docintel_credential=AzureKeyCredential(key),
                )
            except (ImportError, TypeError):
                pass
        return MarkItDown(enable_plugins=False, docintel_endpoint=endpoint)
