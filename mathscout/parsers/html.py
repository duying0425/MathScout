from bs4 import BeautifulSoup
from trafilatura import extract


def html_to_text(html: str) -> str:
    text = extract(html)
    if text:
        return text
    soup = BeautifulSoup(html, "html.parser")
    for node in soup(["script", "style", "noscript"]):
        node.decompose()
    return soup.get_text("\n", strip=True)
