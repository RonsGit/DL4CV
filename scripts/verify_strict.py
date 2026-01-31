#!/usr/bin/env python3
"""
verify_strict.py (canonical)
Version-agnostic verification of html_output/ and downloads/ artifacts.

Constraints:
- Do NOT assert exact PDF page counts.
- Do check existence, sane size, and first-page heading markers.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import List, Optional

try:
    from pypdf import PdfReader
except Exception:
    from PyPDF2 import PdfReader  # type: ignore


def _read_text(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="ignore")


def _fail(msg: str) -> None:
    raise RuntimeError(msg)


def _pdf_first_page_text(pdf: Path) -> str:
    r = PdfReader(str(pdf))
    try:
        t = r.pages[0].extract_text() or ""
    except Exception:
        t = ""
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _looks_like_bib_heading(text: str) -> bool:
    head = text.lower().lstrip()[:200]
    return ("bibliography" in head) or ("references" in head)


def _html_has(sel: str, html: str) -> bool:
    # Simple marker checks; avoids parser dependency
    return sel in html


def _extract_doc_content(html: str) -> str:
    m = re.search(r'<div class="card-body" id="doc_content">([\s\S]+?)</div>\s*</div>\s*</div>', html)
    if not m:
        # fallback: between markers
        m = re.search(r"<!-- content-start -->([\s\S]+?)<!-- content-end -->", html)
    return m.group(1) if m else ""


def main(argv: List[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default="html_output")
    args = ap.parse_args(argv)

    out_dir = Path(args.out_dir)
    if not out_dir.exists():
        _fail(f"Output dir missing: {out_dir}")

    # 1) Bibliography.pdf checks
    bib_pdf = out_dir / "downloads" / "Bibliography.pdf"
    if not bib_pdf.exists():
        _fail("Missing downloads/Bibliography.pdf")
    if bib_pdf.stat().st_size < 80_000:
        _fail("Bibliography.pdf too small (suspicious)")
    if not _looks_like_bib_heading(_pdf_first_page_text(bib_pdf)):
        _fail("Bibliography.pdf first page does not contain Bibliography/References heading")

    # 2) Gather chapter HTML
    chapters = sorted([p for p in out_dir.glob("*.html") if p.name.lower().startswith(("chapter_", "lecture_"))])
    if not chapters:
        _fail("No Chapter_*.html (or Lecture_*.html) found in html_output/")

    # Representative chapter: middle if possible
    rep = chapters[len(chapters) // 2]
    html = _read_text(rep)

    # 3) Shell markers
    for marker in ["id=\"topbar\"", "id=\"sidebar\"", "id=\"content_area\"", "id=\"local_toc\"", "id=\"sidebar_resizer\"", "id=\"sec_prev\"", "id=\"sec_next\""]:
        if marker not in html:
            _fail(f"Representative chapter missing required UI marker {marker}: {rep.name}")

    # 4) Non-trivial content in card
    doc = _extract_doc_content(html)
    doc_text = re.sub(r"<[^>]+>", " ", doc)
    doc_text = re.sub(r"\s+", " ", doc_text).strip()
    if len(doc_text) < 1200:
        _fail(f"Representative chapter content too short (empty card regression?): {rep.name} len={len(doc_text)}")

    # 5) No bibliography leakage in any chapter
    bib_heading_pat = re.compile(r"<h[12]\b[^>]*>\s*(Bibliography|References)\s*</h[12]>", flags=re.IGNORECASE)
    for p in chapters:
        h = _read_text(p)
        doc2 = _extract_doc_content(h)
        if bib_heading_pat.search(doc2):
            _fail(f"Bibliography/References leaked into chapter HTML: {p.name}")

    # 6) Preface and dependency graph pages (if present) must be non-empty and wrapped
    preface = out_dir / "Auxiliary" / "Preface.html"
    if preface.exists():
        ph = _read_text(preface)
        if "id=\"topbar\"" not in ph or "id=\"doc_content\"" not in ph:
            _fail("Preface.html exists but is not wrapped into canonical shell")
        pdoc = re.sub(r"<[^>]+>", " ", _extract_doc_content(ph))
        pdoc = re.sub(r"\s+", " ", pdoc).strip()
        if len(pdoc) < 600:
            _fail("Preface.html content too short (placeholder/empty)")

        preface_pdf = out_dir / "downloads" / "Preface.pdf"
        if not preface_pdf.exists():
            _fail("Preface.html exists but downloads/Preface.pdf is missing")

    dep = out_dir / "dependency_graph.html"
    if dep.exists():
        dh = _read_text(dep)
        if "id=\"topbar\"" not in dh or "id=\"doc_content\"" not in dh:
            _fail("dependency_graph.html exists but is not wrapped into canonical shell")
        ddoc = re.sub(r"<[^>]+>", " ", _extract_doc_content(dh))
        ddoc = re.sub(r"\s+", " ", ddoc).strip()
        if len(ddoc) < 120:
            _fail("dependency_graph.html content too short (placeholder/empty)")

    # 7) bibliography.html should exist and contain heading markers
    bib_html = out_dir / "bibliography.html"
    if not bib_html.exists():
        _fail("Missing bibliography.html")
    bh = _read_text(bib_html)
    if "Bibliography" not in bh and "References" not in bh:
        _fail("bibliography.html missing Bibliography/References heading text")

    # 8) manifest.json exists
    manifest = out_dir / "manifest.json"
    if not manifest.exists() or manifest.stat().st_size < 50:
        _fail("Missing or empty manifest.json")

    print("[verify_strict] PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
