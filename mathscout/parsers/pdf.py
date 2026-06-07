from pathlib import Path

import fitz


def pdf_to_text(path: Path) -> str:
    doc = fitz.open(path)
    pages = []
    for index, page in enumerate(doc, start=1):
        text = page.get_text("text")
        pages.append(f"\n\n[page {index}]\n{text}")
    return "".join(pages).strip()
