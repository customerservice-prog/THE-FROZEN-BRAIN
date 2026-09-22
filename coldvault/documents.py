from __future__ import annotations

import shutil
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree


@dataclass(frozen=True)
class ExtractedDocument:
    text: str
    media_type: str
    extractor: str


class _HTMLTextExtractor(HTMLParser):
    BLOCKS = {"p", "div", "section", "article", "header", "footer", "li", "br", "h1", "h2", "h3", "h4", "h5", "h6", "tr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._ignored = 0

    def handle_starttag(self, tag: str, attrs):
        tag = tag.lower()
        if tag in {"script", "style", "noscript"}:
            self._ignored += 1
        elif not self._ignored and tag in self.BLOCKS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str):
        tag = tag.lower()
        if tag in {"script", "style", "noscript"} and self._ignored:
            self._ignored -= 1
        elif not self._ignored and tag in self.BLOCKS:
            self.parts.append("\n")

    def handle_data(self, data: str):
        if not self._ignored:
            self.parts.append(data)

    def text(self) -> str:
        lines = [" ".join(line.split()) for line in "".join(self.parts).splitlines()]
        return "\n".join(line for line in lines if line)


TEXT_EXTENSIONS = {
    ".txt", ".md", ".rst", ".py", ".js", ".ts", ".tsx", ".jsx",
    ".json", ".csv", ".yaml", ".yml", ".toml", ".ini", ".log",
}


def _docx_text(path: Path) -> str:
    parts: list[str] = []
    with zipfile.ZipFile(path) as archive:
        names = ["word/document.xml"]
        names += sorted(
            name for name in archive.namelist()
            if name.startswith("word/header") or name.startswith("word/footer")
        )
        for name in names:
            if name not in archive.namelist():
                continue
            root = ElementTree.fromstring(archive.read(name))
            for paragraph in root.iter():
                if paragraph.tag.endswith("}p"):
                    text = "".join(
                        node.text or "" for node in paragraph.iter()
                        if node.tag.endswith("}t")
                    ).strip()
                    if text:
                        parts.append(text)
    return "\n".join(parts)


def _pdf_with_pypdf(path: Path) -> str | None:
    try:
        from pypdf import PdfReader
    except ImportError:
        return None
    reader = PdfReader(str(path))
    pages = []
    for page_number, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        if text.strip():
            pages.append(f"--- PAGE {page_number} ---\n{text.strip()}")
    return "\n\n".join(pages)


def _pdf_with_pdftotext(path: Path) -> str | None:
    executable = shutil.which("pdftotext")
    if not executable:
        return None
    with tempfile.TemporaryDirectory() as td:
        output = Path(td) / "out.txt"
        proc = subprocess.run(
            [executable, "-layout", str(path), str(output)],
            capture_output=True,
            text=True,
            timeout=120,
            shell=False,
        )
        if proc.returncode != 0:
            raise ValueError(f"pdftotext failed: {proc.stderr.strip()[:500]}")
        return output.read_text(encoding="utf-8", errors="replace")


def extract_document(path: Path) -> ExtractedDocument:
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix in TEXT_EXTENSIONS:
        return ExtractedDocument(
            path.read_text(encoding="utf-8", errors="replace"),
            "text/plain",
            "stdlib-text",
        )
    if suffix in {".html", ".htm"}:
        parser = _HTMLTextExtractor()
        parser.feed(path.read_text(encoding="utf-8", errors="replace"))
        return ExtractedDocument(parser.text(), "text/html", "stdlib-html")
    if suffix == ".docx":
        return ExtractedDocument(
            _docx_text(path),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "stdlib-docx",
        )
    if suffix == ".pdf":
        text = _pdf_with_pypdf(path)
        if text is not None:
            return ExtractedDocument(text, "application/pdf", "pypdf")
        text = _pdf_with_pdftotext(path)
        if text is not None:
            return ExtractedDocument(text, "application/pdf", "pdftotext")
        raise ValueError(
            "offline PDF extraction needs either the optional 'pypdf' package or the local 'pdftotext' binary; "
            "archive one of them with ColdVault before going offline"
        )
    raise ValueError(f"unsupported document extension: {suffix or '<none>'}")
