#!/usr/bin/env python3
"""
split_pdf.py (canonical)
Split main.pdf into per-chapter PDFs and Preface.pdf (if detectable),
stopping before bibliography.

Uses PyMuPDF (fitz) for fast extraction when available, falls back to pypdf.
PyMuPDF is 3-5x faster than pypdf for PDF splitting operations.
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path
from typing import List, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor, as_completed

# Try PyMuPDF first (much faster), then pypdf
_USE_PYMUPDF = False
try:
    import pymupdf as fitz  # New import name
    _USE_PYMUPDF = True
except ImportError:
    try:
        import fitz  # Legacy import name
        _USE_PYMUPDF = True
    except ImportError:
        pass

if not _USE_PYMUPDF:
    try:
        from pypdf import PdfReader, PdfWriter
    except ImportError:
        from PyPDF2 import PdfReader, PdfWriter  # type: ignore


def _read_text(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="ignore")


def _page_text_fitz(doc, idx: int) -> str:
    """Extract text from page using PyMuPDF."""
    try:
        page = doc[idx]
        t = page.get_text() or ""
    except Exception:
        t = ""
    return re.sub(r"\s+", " ", t).strip()


def _page_text_pypdf(reader, idx: int) -> str:
    """Extract text from page using pypdf."""
    try:
        t = reader.pages[idx].extract_text() or ""
    except Exception:
        t = ""
    return re.sub(r"\s+", " ", t).strip()


def _looks_like_bib_heading(text: str) -> bool:
    t = text.lower().lstrip()[:200]
    return ("bibliography" in t) or ("references" in t)


def _toc_parse_chapters(toc_text: str) -> List[Tuple[int, int, str]]:
    """
    Parse toc for numbered chapters:
      (chapter_num, page_1based, title)
    """
    pat = re.compile(
        r"\\contentsline\s*\{chapter\}\{\s*\\numberline\s*\{(\d+)\}\s*([^}]*)\}\{(\d+)\}",
        flags=re.IGNORECASE
    )
    out = []
    for m in pat.finditer(toc_text):
        try:
            num = int(m.group(1))
            title = re.sub(r"\s+", " ", m.group(2)).strip()
            page = int(m.group(3))
            out.append((num, page, title))
        except Exception:
            continue
    out.sort(key=lambda x: x[0])
    return out


def _toc_find_bib_page(toc_text: str) -> Optional[int]:
    pat = re.compile(
        r"\\contentsline\s*\{[^}]+\}\{\s*(?:\\numberline\s*\{[^}]*\})?\s*(Bibliography|References)\s*\}\{(\d+)\}",
        flags=re.IGNORECASE
    )
    m = pat.search(toc_text)
    if not m:
        return None
    try:
        return int(m.group(2))
    except Exception:
        return None


def _toc_find_preface_page(toc_text: str) -> Optional[int]:
    pat = re.compile(
        r"\\contentsline\s*\{chapter\}\{\s*(?:\\numberline\s*\{[^}]*\})?\s*Preface\s*\}\{(\d+)\}",
        flags=re.IGNORECASE
    )
    m = pat.search(toc_text)
    if not m:
        return None
    try:
        return int(m.group(1))
    except Exception:
        return None


def _find_bib_start_idx_fitz(doc, toc_hint_1based: Optional[int]) -> Optional[int]:
    """Find bibliography start page using PyMuPDF."""
    n = len(doc)
    hint = (toc_hint_1based - 1) if toc_hint_1based else None

    def scan(lo: int, hi: int) -> Optional[int]:
        lo = max(0, lo)
        hi = min(n - 1, hi)
        for i in range(lo, hi + 1):
            if _looks_like_bib_heading(_page_text_fitz(doc, i)):
                return i
        return None

    if hint is not None:
        found = scan(hint - 12, hint + 60)
        if found is not None:
            return found
    return scan(max(0, n - 350), n - 1)


def _find_bib_start_idx_pypdf(reader, toc_hint_1based: Optional[int]) -> Optional[int]:
    """Find bibliography start page using pypdf."""
    n = len(reader.pages)
    hint = (toc_hint_1based - 1) if toc_hint_1based else None

    def scan(lo: int, hi: int) -> Optional[int]:
        lo = max(0, lo)
        hi = min(n - 1, hi)
        for i in range(lo, hi + 1):
            if _looks_like_bib_heading(_page_text_pypdf(reader, i)):
                return i
        return None

    if hint is not None:
        found = scan(hint - 12, hint + 60)
        if found is not None:
            return found
    return scan(max(0, n - 350), n - 1)


# =============================================================================
# PyMuPDF (fitz) implementation - FAST
# =============================================================================

def _extract_chapter_fitz(doc, start: int, end: int, out_path: Path, ch_num: int, seq: int, total: int) -> str:
    """
    Extract pages using PyMuPDF's select() method - very fast.
    This modifies a copy of the document in memory, then saves it.
    """
    try:
        t0 = time.time()
        # Create a new document with just the pages we need
        # select() is the fastest way - it creates a view, not a copy
        new_doc = fitz.open()  # Empty document
        new_doc.insert_pdf(doc, from_page=start, to_page=end)

        out_path.parent.mkdir(parents=True, exist_ok=True)
        new_doc.save(str(out_path), garbage=3, deflate=True)
        new_doc.close()

        size_mb = out_path.stat().st_size / (1024 * 1024)
        duration = time.time() - t0
        page_count = end - start + 1

        return (f"   [{seq}/{total}] Chapter {ch_num} (Pages {start + 1}-{end + 1}, {page_count} pgs)... "
                f"Done -> {size_mb:.2f} MB ({duration:.2f}s)")
    except Exception as e:
        return f"   [{seq}/{total}] Chapter {ch_num} FAILED: {e}"


def _run_fitz(main_pdf: Path, toc_path: Path, out_dir: Path) -> int:
    """Run PDF splitting using PyMuPDF."""
    print(f"[split_pdf] Using PyMuPDF (fast mode)", flush=True)

    toc_text = _read_text(toc_path)
    chapters = _toc_parse_chapters(toc_text)
    if not chapters:
        raise RuntimeError("No chapters parsed from main.toc (unexpected format).")
    print(f"[split_pdf] Found {len(chapters)} chapters in TOC", flush=True)

    bib_page = _toc_find_bib_page(toc_text)
    preface_page = _toc_find_preface_page(toc_text)
    print(f"[split_pdf] Bibliography TOC page: {bib_page}, Preface TOC page: {preface_page}", flush=True)

    # Load PDF once
    pdf_size_mb = main_pdf.stat().st_size / (1024 * 1024)
    print(f"[split_pdf] Loading main PDF ({pdf_size_mb:.1f} MB)...", flush=True)
    t_load = time.time()
    doc = fitz.open(str(main_pdf))
    n_pages = len(doc)
    print(f"[split_pdf] PDF loaded in {time.time() - t_load:.1f}s — {n_pages} pages. Scanning for bibliography...", flush=True)

    bib_idx = _find_bib_start_idx_fitz(doc, bib_page)
    if bib_idx is None:
        raise RuntimeError("Could not locate bibliography start in PDF (needed to stop splitting).")

    if bib_page is not None:
        offset = bib_idx - (bib_page - 1)
    else:
        offset = 0
    print(f"[split_pdf] Bibliography starts at PDF page {bib_idx + 1}, offset={offset}", flush=True)

    t_start = time.time()
    n_extracted = 0

    # Extract Preface if present
    if preface_page is not None:
        pref_start = (preface_page - 1) + offset
        first_ch_page = chapters[0][1]
        pref_end = (first_ch_page - 1 + offset) - 1
        if 0 <= pref_start <= pref_end < n_pages:
            p_out = out_dir / "Preface.pdf"
            print(f"   [Split] Extracting Preface (Pages {pref_start + 1}-{pref_end + 1})...", end=" ", flush=True)
            t0 = time.time()
            new_doc = fitz.open()
            new_doc.insert_pdf(doc, from_page=pref_start, to_page=pref_end)
            p_out.parent.mkdir(parents=True, exist_ok=True)
            new_doc.save(str(p_out), garbage=3, deflate=True)
            new_doc.close()
            size_mb = p_out.stat().st_size / (1024 * 1024)
            print(f"Done -> {size_mb:.1f} MB ({time.time() - t0:.1f}s)", flush=True)
            n_extracted += 1

    # Build extraction tasks
    tasks = []
    for i, (ch_num, toc_page, _title) in enumerate(chapters):
        start = (toc_page - 1) + offset
        if i < len(chapters) - 1:
            next_start = (chapters[i + 1][1] - 1) + offset
            end = min(next_start - 1, bib_idx - 1)
        else:
            end = bib_idx - 1

        counter_str = f"[{i+1}/{len(chapters)}]"

        if start < 0 or start >= n_pages:
            print(f"   {counter_str} Chapter {ch_num}: SKIP (start={start} out of range)", flush=True)
            continue
        if end < start:
            print(f"   {counter_str} Chapter {ch_num}: SKIP (end={end} < start={start})", flush=True)
            continue

        out_pdf = out_dir / f"Chapter_{ch_num:02d}.pdf"
        tasks.append((start, end, out_pdf, ch_num, i + 1, len(chapters)))

    # PyMuPDF is single-threaded for best performance (GIL + internal optimizations)
    # Sequential extraction from already-loaded document is very fast
    print(f"[split_pdf] Extracting {len(tasks)} chapters sequentially (PyMuPDF optimized)...", flush=True)

    for start, end, out_pdf, ch_num, seq, total in tasks:
        result = _extract_chapter_fitz(doc, start, end, out_pdf, ch_num, seq, total)
        print(result, flush=True)
        if "FAILED" not in result:
            n_extracted += 1

    doc.close()

    elapsed = time.time() - t_start
    total_elapsed = time.time() - t_load
    print(f"[split_pdf] Extraction complete: {n_extracted}/{len(chapters)} PDFs in {elapsed:.2f}s "
          f"(total with load: {total_elapsed:.2f}s)", flush=True)
    print(f"[split_pdf] Summary: bib_idx={bib_idx} offset={offset}", flush=True)
    return 0


# =============================================================================
# pypdf implementation - fallback, slower
# =============================================================================

def _extract_range_pypdf(reader, start: int, end_inclusive: int, out_pdf: Path) -> None:
    """Extract pages using pypdf."""
    writer = PdfWriter()
    for i in range(start, end_inclusive + 1):
        writer.add_page(reader.pages[i])
    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    with out_pdf.open("wb") as f:
        writer.write(f)


def _run_pypdf(main_pdf: Path, toc_path: Path, out_dir: Path) -> int:
    """Run PDF splitting using pypdf (slower fallback)."""
    print(f"[split_pdf] Using pypdf (slower fallback - consider installing pymupdf)", flush=True)

    toc_text = _read_text(toc_path)
    chapters = _toc_parse_chapters(toc_text)
    if not chapters:
        raise RuntimeError("No chapters parsed from main.toc (unexpected format).")
    print(f"[split_pdf] Found {len(chapters)} chapters in TOC", flush=True)

    bib_page = _toc_find_bib_page(toc_text)
    preface_page = _toc_find_preface_page(toc_text)
    print(f"[split_pdf] Bibliography TOC page: {bib_page}, Preface TOC page: {preface_page}", flush=True)

    # Load PDF once
    pdf_size_mb = main_pdf.stat().st_size / (1024 * 1024)
    print(f"[split_pdf] Loading main PDF ({pdf_size_mb:.1f} MB)...", flush=True)
    t_load = time.time()
    reader = PdfReader(str(main_pdf))
    n_pages = len(reader.pages)
    print(f"[split_pdf] PDF loaded in {time.time() - t_load:.1f}s — {n_pages} pages. Scanning for bibliography...", flush=True)

    bib_idx = _find_bib_start_idx_pypdf(reader, bib_page)
    if bib_idx is None:
        raise RuntimeError("Could not locate bibliography start in PDF (needed to stop splitting).")

    if bib_page is not None:
        offset = bib_idx - (bib_page - 1)
    else:
        offset = 0
    print(f"[split_pdf] Bibliography starts at PDF page {bib_idx + 1}, offset={offset}", flush=True)

    t_start = time.time()
    n_extracted = 0

    # Extract Preface if present
    if preface_page is not None:
        pref_start = (preface_page - 1) + offset
        first_ch_page = chapters[0][1]
        pref_end = (first_ch_page - 1 + offset) - 1
        if 0 <= pref_start <= pref_end < n_pages:
            p_out = out_dir / "Preface.pdf"
            print(f"   [Split] Extracting Preface (Pages {pref_start + 1}-{pref_end + 1})...", end=" ", flush=True)
            t0 = time.time()
            _extract_range_pypdf(reader, pref_start, pref_end, p_out)
            size_mb = p_out.stat().st_size / (1024 * 1024)
            print(f"Done -> {size_mb:.1f} MB ({time.time() - t0:.1f}s)", flush=True)
            n_extracted += 1

    # Build extraction tasks
    tasks = []
    for i, (ch_num, toc_page, _title) in enumerate(chapters):
        start = (toc_page - 1) + offset
        if i < len(chapters) - 1:
            next_start = (chapters[i + 1][1] - 1) + offset
            end = min(next_start - 1, bib_idx - 1)
        else:
            end = bib_idx - 1

        counter_str = f"[{i+1}/{len(chapters)}]"

        if start < 0 or start >= n_pages:
            print(f"   {counter_str} Chapter {ch_num}: SKIP (start={start} out of range)", flush=True)
            continue
        if end < start:
            print(f"   {counter_str} Chapter {ch_num}: SKIP (end={end} < start={start})", flush=True)
            continue

        out_pdf = out_dir / f"Chapter_{ch_num:02d}.pdf"
        tasks.append((start, end, out_pdf, ch_num, i + 1, len(chapters)))

    # Sequential extraction (pypdf doesn't parallelize well due to GIL and shared reader)
    print(f"[split_pdf] Extracting {len(tasks)} chapters sequentially...", flush=True)

    for start, end, out_pdf, ch_num, seq, total in tasks:
        try:
            t0 = time.time()
            _extract_range_pypdf(reader, start, end, out_pdf)
            size_mb = out_pdf.stat().st_size / (1024 * 1024)
            duration = time.time() - t0
            page_count = end - start + 1
            print(f"   [{seq}/{total}] Chapter {ch_num} (Pages {start + 1}-{end + 1}, {page_count} pgs)... "
                  f"Done -> {size_mb:.2f} MB ({duration:.2f}s)", flush=True)
            n_extracted += 1
        except Exception as e:
            print(f"   [{seq}/{total}] Chapter {ch_num} FAILED: {e}", flush=True)

    elapsed = time.time() - t_start
    total_elapsed = time.time() - t_load
    print(f"[split_pdf] Extraction complete: {n_extracted}/{len(chapters)} PDFs in {elapsed:.2f}s "
          f"(total with load: {total_elapsed:.2f}s)", flush=True)
    print(f"[split_pdf] Summary: bib_idx={bib_idx} offset={offset}", flush=True)
    return 0


# =============================================================================
# Main entry point
# =============================================================================

def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--main-pdf", default="html_output/downloads/main.pdf")
    ap.add_argument("--toc", default="html_output/main.toc")
    ap.add_argument("--out-dir", default="html_output/downloads")
    args = ap.parse_args(argv)

    main_pdf = Path(args.main_pdf)
    toc_path = Path(args.toc)
    out_dir = Path(args.out_dir)

    if not main_pdf.exists():
        raise FileNotFoundError(f"main.pdf not found: {main_pdf}")
    if not toc_path.exists():
        raise FileNotFoundError(f"main.toc not found: {toc_path}")

    print(f"[split_pdf] Reading TOC from {toc_path}...", flush=True)

    if _USE_PYMUPDF:
        return _run_fitz(main_pdf, toc_path, out_dir)
    else:
        return _run_pypdf(main_pdf, toc_path, out_dir)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
