"""附件链接识别。

初中数学的教师方法常常藏在页面链接出去的附件里（课件 PPT、教案 DOC、学案 PDF），
而不在页面正文。链接发现阶段用这里的规则识别附件链接并入队抓取，再交给转换层
（markitdown 等）转成 Markdown 供 Phase 2 抽取。
"""

from __future__ import annotations

from pathlib import PurePosixPath
from urllib.parse import urlparse

# 视为"可抽取附件"的扩展名。压缩包（.zip/.rar）不直接转换，故不在此列。
ATTACHMENT_EXTENSIONS = frozenset(
    {
        ".pdf",
        ".doc",
        ".docx",
        ".ppt",
        ".pptx",
        ".xls",
        ".xlsx",
        ".csv",
        ".rtf",
        ".odt",
        ".odp",
        ".ods",
    }
)


def attachment_extension(url: str) -> str | None:
    """返回 URL 路径的附件扩展名（小写，含点），非附件则返回 None。"""
    ext = PurePosixPath(urlparse(url).path).suffix.lower()
    return ext if ext in ATTACHMENT_EXTENSIONS else None


def is_attachment_url(url: str) -> bool:
    """URL 是否指向一个可抽取的附件。"""
    return attachment_extension(url) is not None
