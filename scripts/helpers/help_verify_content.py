#!/usr/bin/env python3
"""
verify_chapter_content.py

Helps in the verification of the content of a given chapter.
It takes a chapter number, looks for the chapter PDF, and looks up section info from main.toc.
Then it splits the chapter PDF into per-section PDFs, extracts images, .tex snippets, and bibliography.

Usage:
    python3 scripts/verify_chapter_content.py --chapters 24 25
"""

import argparse
import re
import sys
import shutil
from pathlib import Path
from typing import List, Tuple, Optional, Dict, Set


# Try PyMuPDF (fitz)
try:
    import pymupdf as fitz
except ImportError:
    try:
        import fitz
    except ImportError:
        print("Error: PyMuPDF (fitz) is required for this script.")
        print("Please install it: pip install pymupdf")
        sys.exit(1)

def _read_text(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="ignore")


# ============================================================================
# .tex Content Extraction
# ============================================================================

def find_chapter_tex_file(chapters_dir: Path, ch_num: int) -> Optional[Path]:
    """Find the .tex file for a given chapter number."""
    pattern = f"Chapter_{ch_num}_*.tex"
    matches = list(chapters_dir.glob(pattern))
    if matches:
        return matches[0]
    # Try with zero-padded
    pattern = f"Chapter_{ch_num:02d}_*.tex"
    matches = list(chapters_dir.glob(pattern))
    if matches:
        return matches[0]
    return None


def parse_tex_structure(tex_content: str) -> List[dict]:
    r"""
    Parse .tex content and identify section/subsection boundaries.
    Returns a list of dicts with type, title, start_pos, end_pos.
    Handles both regular \section{} and \begin{enrichment}[title][level] formats.
    """
    markers = []
    
    # Regular sections: \section{Title}
    section_pat = re.compile(r'\\section\{([^}]+)\}', re.MULTILINE)
    for m in section_pat.finditer(tex_content):
        markers.append({
            'type': 'section',
            'title': m.group(1).strip(),
            'pos': m.start(),
            'end_marker': None  # Will be filled by next marker or EOF
        })
    
    # Regular subsections: \subsection{Title}
    subsection_pat = re.compile(r'\\subsection\{([^}]+)\}', re.MULTILINE)
    for m in subsection_pat.finditer(tex_content):
        markers.append({
            'type': 'subsection',
            'title': m.group(1).strip(),
            'pos': m.start(),
            'end_marker': None
        })
    
    # Enrichment sections: \begin{enrichment}[Title][section]
    # Note: title may span multiple lines due to line wrapping
    enrichment_section_pat = re.compile(
        r'\\begin\{enrichment\}\[([^\]]+)\]\s*\[section\]',
        re.MULTILINE | re.DOTALL
    )
    for m in enrichment_section_pat.finditer(tex_content):
        title = re.sub(r'\s+', ' ', m.group(1)).strip()
        markers.append({
            'type': 'section',
            'title': title,
            'title_normalized': title,  # Store both forms
            'pos': m.start(),
            'is_enrichment': True,
            'end_marker': None
        })
    
    # Enrichment subsections: \begin{enrichment}[Title][subsection]
    enrichment_subsection_pat = re.compile(
        r'\\begin\{enrichment\}\[([^\]]+)\]\s*\[subsection\]',
        re.MULTILINE | re.DOTALL
    )
    for m in enrichment_subsection_pat.finditer(tex_content):
        title = re.sub(r'\s+', ' ', m.group(1)).strip()
        markers.append({
            'type': 'subsection',
            'title': title,
            'title_normalized': title,
            'pos': m.start(),
            'is_enrichment': True,
            'end_marker': None
        })
    
    # Sort by position
    markers.sort(key=lambda x: x['pos'])
    
    # Fill end markers based on next item position
    for i, m in enumerate(markers):
        if i + 1 < len(markers):
            m['end_marker'] = markers[i + 1]['pos']
        else:
            m['end_marker'] = len(tex_content)
    
    return markers


def normalize_title(s: str) -> str:
    """Normalize a title for comparison."""
    # Remove latex commands and special chars
    s = re.sub(r'\\[a-zA-Z]+\{([^}]*)\}', r'\1', s)  # \textbf{X} -> X
    s = re.sub(r'\\mbox\s*\{([^}]*)\}', r'\1', s)  # \mbox{X} -> X
    s = re.sub(r'\\[a-zA-Z]+', '', s)  # Remove stray commands
    s = re.sub(r'[~\-\{\}]', ' ', s)  # Replace special chars with space
    s = re.sub(r'\s+', ' ', s).strip().lower()
    return s


def find_matching_marker(markers: List[dict], search_title: str) -> int:
    """
    Find the index of the marker that best matches the search title.
    Uses multiple matching strategies with fallbacks.
    """
    norm_search = normalize_title(search_title)
    
    # Remove "Enrichment:" prefix if present for matching
    search_without_prefix = norm_search
    if search_without_prefix.startswith('enrichment:'):
        search_without_prefix = search_without_prefix[11:].strip()
    
    # Strategy 1: Exact normalized match
    for i, m in enumerate(markers):
        norm_marker = normalize_title(m['title'])
        if norm_marker == norm_search or norm_marker == search_without_prefix:
            return i
    
    # Strategy 2: One contains the other (substring match)
    for i, m in enumerate(markers):
        norm_marker = normalize_title(m['title'])
        if norm_search in norm_marker or search_without_prefix in norm_marker:
            return i
        if norm_marker in norm_search or norm_marker in search_without_prefix:
            return i
    
    # Strategy 3: Word overlap - find the one with most common words
    search_words = set(norm_search.split())
    search_words_no_prefix = set(search_without_prefix.split())
    
    best_idx = -1
    best_overlap = 0
    
    for i, m in enumerate(markers):
        norm_marker = normalize_title(m['title'])
        marker_words = set(norm_marker.split())
        
        overlap1 = len(search_words & marker_words)
        overlap2 = len(search_words_no_prefix & marker_words)
        overlap = max(overlap1, overlap2)
        
        if overlap > best_overlap:
            best_overlap = overlap
            best_idx = i
    
    # Require at least 2 words overlap or 50% of words
    if best_overlap >= 2 or (best_overlap > 0 and best_overlap >= len(search_words) / 2):
        return best_idx
    
    return -1


def extract_tex_for_section(tex_content: str, section_title: str, include_subsections: bool = False, markers: list = None) -> str:
    """
    Extract .tex content for a specific section.
    
    Args:
        tex_content: The full chapter .tex content
        section_title: The title to search for (from TOC name)
        include_subsections: If True and the matched item is a section, include all
                            subsections until the next section. If False, stop at 
                            the next section OR subsection.
        markers: Optional pre-parsed markers (for efficiency)
    """
    if markers is None:
        markers = parse_tex_structure(tex_content)
    
    if not markers:
        return ""
    
    target_idx = find_matching_marker(markers, section_title)
    
    if target_idx == -1:
        return ""
    
    target_marker = markers[target_idx]
    start_pos = target_marker['pos']
    
    if include_subsections and target_marker['type'] == 'section':
        # For sections with include_subsections, find the next section (not subsection)
        end_pos = len(tex_content)
        for i in range(target_idx + 1, len(markers)):
            if markers[i]['type'] == 'section':
                end_pos = markers[i]['pos']
                break
    else:
        # Default: stop at next marker (section or subsection)
        end_pos = target_marker.get('end_marker', len(tex_content))
    
    return tex_content[start_pos:end_pos]


def extract_all_section_content(tex_content: str) -> Dict[str, str]:
    """
    Pre-extract all sections from a .tex file and return a dict mapping 
    normalized titles to their content.
    """
    markers = parse_tex_structure(tex_content)
    result = {}
    
    for m in markers:
        title = m['title']
        start = m['pos']
        end = m.get('end_marker', len(tex_content))
        content = tex_content[start:end]
        
        # Store with both original and normalized titles
        result[title] = content
        result[normalize_title(title)] = content
    
    return result


# ============================================================================
# Bibliography Extraction
# ============================================================================

def extract_citations_from_tex(tex_snippet: str) -> Set[str]:
    r"""
    Extract all citation keys from a .tex snippet.
    Handles \cite{}, \parencite{}, \cites{}{}, \textcite{}, etc.
    """
    citation_keys = set()
    
    # Pattern for various citation commands
    # \cite{key1, key2}, \parencite{key}, \cites{k1}{k2}, \textcite{key}
    patterns = [
        r'\\cite\{([^}]+)\}',
        r'\\parencite\{([^}]+)\}',
        r'\\textcite\{([^}]+)\}',
        r'\\citeauthor\{([^}]+)\}',
        r'\\citeyear\{([^}]+)\}',
        r'\\cites\{([^}]+)\}',
        r'\\citep\{([^}]+)\}',
        r'\\citet\{([^}]+)\}',
    ]
    
    for pattern in patterns:
        for m in re.finditer(pattern, tex_snippet):
            keys_str = m.group(1)
            # Split by comma and clean
            for key in keys_str.split(','):
                key = key.strip()
                if key:
                    citation_keys.add(key)
    
    return citation_keys


def parse_bib_file(bib_path: Path) -> Dict[str, str]:
    """
    Parse a .bib file and return a dict mapping citation keys to full entries.
    """
    if not bib_path.exists():
        return {}
    
    content = _read_text(bib_path)
    entries = {}
    
    # Pattern to find @type{key, ... }
    # This is a simplified parser that handles most cases
    entry_pat = re.compile(r'@(\w+)\s*\{\s*([^,\s]+)\s*,', re.MULTILINE)
    
    matches = list(entry_pat.finditer(content))
    
    for i, m in enumerate(matches):
        key = m.group(2).strip()
        start = m.start()
        
        # Find the matching closing brace
        if i + 1 < len(matches):
            # Approximate: next entry starts
            end = matches[i + 1].start()
        else:
            end = len(content)
        
        # Find actual closing brace by counting
        brace_count = 0
        actual_end = start
        for j, ch in enumerate(content[start:end]):
            if ch == '{':
                brace_count += 1
            elif ch == '}':
                brace_count -= 1
                if brace_count == 0:
                    actual_end = start + j + 1
                    break
        
        if actual_end > start:
            entries[key] = content[start:actual_end].strip()
    
    return entries


def extract_bib_entries(bib_entries: Dict[str, str], citation_keys: Set[str]) -> str:
    """
    Extract bibliography entries for the given citation keys.
    Returns a string with all matching entries.
    """
    result_lines = []
    
    for key in sorted(citation_keys):
        if key in bib_entries:
            result_lines.append(bib_entries[key])
            result_lines.append("")  # Empty line between entries
    
    return "\n".join(result_lines)


def parse_toc_for_chapters(toc_path: Path, target_chapters: List[int]) -> Dict[int, dict]:
    """
    Parses main.toc and extracts info for multiple chapters.
    """
    text = _read_text(toc_path)
    lines = text.splitlines()
    
    # Improved Regexes using (.*) and anchoring to page number to handle nested braces in title
    # Structure: \contentsline {TYPE} { \numberline {NUM} TITLE } { PAGE } { LABEL }
    
    # Chapter
    chapter_pat = re.compile(
        r"\\contentsline\s*\{chapter\}\{\s*\\numberline\s*\{(\d+)\}(.*)\}\{(\d+)\}",
        flags=re.IGNORECASE
    )
    
    # Section
    section_pat = re.compile(
        r"\\contentsline\s*\{section\}\{\s*\\numberline\s*\{(\d+(?:\.\d+)?)\}(.*)\}\{(\d+)\}",
        flags=re.IGNORECASE
    )

    # Subsection
    subsection_pat = re.compile(
        r"\\contentsline\s*\{subsection\}\{\s*\\numberline\s*\{(\d+(?:\.\d+){1,2})\}(.*)\}\{(\d+)\}",
        flags=re.IGNORECASE
    )

    results = {}
    
    current_ch_num = -1
    current_ch_data = None
    
    for line in lines:
        # Check for chapter start
        m_ch = chapter_pat.search(line)
        if m_ch:
            ch_num = int(m_ch.group(1))
            
            # Close previous chapter if it was one we were tracking
            if current_ch_data:
                # The start of this new chapter is the limit for the previous one
                current_ch_data['end_page_limit'] = int(m_ch.group(3))
                results[current_ch_num] = current_ch_data
                current_ch_data = None
                current_ch_num = -1

            # Start new chapter if it's in our target list
            if ch_num in target_chapters:
                current_ch_num = ch_num
                current_ch_data = {
                    'start_page': int(m_ch.group(3)),
                    'end_page_limit': None, # Will be filled by next chapter or EOF logic
                    'sections': [],
                    'raw_toc_lines': [line]
                }
            continue

        # If we are inside a target chapter, capture details
        if current_ch_data:
            current_ch_data['raw_toc_lines'].append(line)
            
            # 1. Section
            m_sec = section_pat.search(line)
            if m_sec:
                num_str = m_sec.group(1)
                title = re.sub(r"\s+", " ", m_sec.group(2)).strip()
                page = int(m_sec.group(3))
                current_ch_data['sections'].append({
                    'type': 'section',
                    'num': num_str,
                    'title': title,
                    'page': page,
                    'full_name': f"{num_str}_{title}"
                })
                continue

            # 2. Subsection
            m_sub = subsection_pat.search(line)
            if m_sub:
                num_str = m_sub.group(1)
                title = re.sub(r"\s+", " ", m_sub.group(2)).strip()
                page = int(m_sub.group(3))
                current_ch_data['sections'].append({
                    'type': 'subsection',
                    'num': num_str,
                    'title': title,
                    'page': page,
                    'full_name': f"{num_str}_{title}"
                })
                continue

    # Handle the very last chapter if it was one of ours
    if current_ch_data:
        results[current_ch_num] = current_ch_data
        
    return results

def calculate_chunks(ch_start_page: int, end_page_limit: int, toc_items: list, doc_page_count: int, max_pages: int = 9) -> List[Tuple[str, Optional[str], int, int]]:
    """
    Decides how to split the chapter into chunks.
    
    Returns list of (SECTION_NAME, SUBDIR_NAME, START_OFFSET_REL, END_OFFSET_REL)
    If SUBDIR_NAME is None, content goes directly into SECTION_NAME dir.
    """
    
    # Filter to only section/subsection
    items = [x for x in toc_items if x['type'] in ('section', 'subsection')]
    
    ch_end_page_abs =  end_page_limit if end_page_limit else (ch_start_page + doc_page_count)
    
    # Group by Section
    grouped = []
    current_section = None
    
    # 1. Check for Chapter Intro (content before first section)
    if items and items[0]['page'] > ch_start_page:
        grouped.append({
            'type': 'intro',
            'name': 'Introduction',
            'start': ch_start_page,
            'end': items[0]['page'] - 1,
            'subs': []
        })
    elif not items:
         # No sections at all
         grouped.append({
            'type': 'full',
            'name': 'Full Chapter',
            'start': ch_start_page,
            'end': ch_end_page_abs - 1, # approximation
            'subs': []
         })
         
    for i, item in enumerate(items):
        if item['type'] == 'section':
            # Finish previous section
            if current_section:
                # End is one page before this new section
                current_section['end'] = item['page'] - 1
                # Also set the last subsection's end if any
                if current_section['subs']:
                    current_section['subs'][-1]['end'] = current_section['end']
            
            # Start new section
            current_section = {
                'type': 'section',
                'name': item['full_name'],
                'start': item['page'],
                'end': -1, # TBD
                'subs': []
            }
            grouped.append(current_section)
            
        elif item['type'] == 'subsection':
            if current_section:
                # We treat subsections as split points within the section.
                if current_section['subs']:
                    # Set previous subsection's end to page before this one
                    prev_end = item['page'] - 1
                    # But ensure end >= start (handles multiple subs on same page)
                    if prev_end < current_section['subs'][-1]['start']:
                        prev_end = current_section['subs'][-1]['start']
                    current_section['subs'][-1]['end'] = prev_end
                
                current_section['subs'].append({
                    'name': item['full_name'],
                    'start': item['page'],
                    'end': -1 # TBD
                })
    
    # Close last section and its last subsection
    if current_section:
        current_section['end'] = ch_end_page_abs - 1
        if current_section['subs']:
             current_section['subs'][-1]['end'] = current_section['end']

    # Now convert to Chunks
    final_chunks = []
    
    for group in grouped:
        start_abs = group['start']
        end_abs = group['end']
        
        # Sanity check: if end < start, fix it
        if end_abs < start_abs:
            end_abs = start_abs

        count = end_abs - start_abs + 1
        
        # Try to keep as one chunk if small or no subs
        if count <= max_pages or not group['subs']:
            final_chunks.append((group['name'], None, start_abs, end_abs))
        else:
            # Split logic with Subsections
            current_chunk_start = start_abs
            
            # Check for intro before first sub
            if group['subs'][0]['start'] > start_abs:
                intro_end = group['subs'][0]['start'] - 1
                final_chunks.append((group['name'], f"{group['name']} (Intro)", start_abs, intro_end))
                current_chunk_start = group['subs'][0]['start']

            # Iterate subs and group them
            temp_sub_group = []
            current_group_start = -1
            
            for sub in group['subs']:
                s_start = sub['start']
                s_end = sub['end']
                
                if current_group_start == -1:
                    current_group_start = s_start
                
                # Check potential length
                curr_len = s_end - current_group_start + 1
                
                if curr_len > max_pages:
                    # Overflow
                    if not temp_sub_group:
                        # Single huge sub
                        final_chunks.append((group['name'], sub['name'], s_start, s_end))
                        current_group_start = -1
                    else:
                        # Flush pending
                        group_name = f"{temp_sub_group[0]['name']} - {temp_sub_group[-1]['name'].split('_')[-1]}" if len(temp_sub_group) > 1 else temp_sub_group[0]['name']
                        group_end = s_start - 1
                        final_chunks.append((group['name'], group_name, current_group_start, group_end))
                        
                        # Handle current
                        if (s_end - s_start + 1) > max_pages:
                             final_chunks.append((group['name'], sub['name'], s_start, s_end))
                             current_group_start = -1
                             temp_sub_group = []
                        else:
                            current_group_start = s_start
                            temp_sub_group = [sub]
                else:
                    temp_sub_group.append(sub)
            
            # Flush remainder
            if temp_sub_group:
                group_name = f"{temp_sub_group[0]['name']} - {temp_sub_group[-1]['name'].split('_')[-1]}" if len(temp_sub_group) > 1 else temp_sub_group[0]['name']
                group_end = group['subs'][-1]['end']
                final_chunks.append((group['name'], group_name, current_group_start, group_end))

    output_ranges = []
    for sec_name, sub_name, s, e in final_chunks:
        rel_s = s - ch_start_page
        rel_e = e - ch_start_page
        rel_s = max(0, rel_s)
        rel_e = min(doc_page_count - 1, rel_e)
        
        if rel_e >= rel_s:
            output_ranges.append((sec_name, sub_name, rel_s, rel_e))
            
    return output_ranges


def extract_images_from_page(doc, page_idx: int, out_dir: Path, img_name: str):
    """Extracts a page as an image."""
    try:
        page = doc[page_idx]
        pix = page.get_pixmap(dpi=150) # 150 DPI is usually sufficient for verification
        out_path = out_dir / img_name
        pix.save(str(out_path))
    except Exception as e:
        print(f"Warning: Failed to save image for page {page_idx}: {e}")

def sanitize_filename(name: str, max_len: int = 40) -> str:
    """Sanitize string to be safe for filenames and enforce max length."""
    # Replace invalid chars with underscore
    clean = re.sub(r'[<>:"/\\|?*]', '_', name)
    # Remove control chars
    clean = "".join(ch for ch in clean if ord(ch) >= 32)
    clean = clean.strip()
    
    if len(clean) > max_len:
        clean = clean[:max_len].strip()
        
    return clean

def main():
    parser = argparse.ArgumentParser(description="Verify Chapter Content by splitting sections, extracting images, .tex, and bibliography.")
    parser.add_argument("--chapters", nargs='+', type=int, required=True, help="List of chapter numbers (e.g. 24 25)")
    parser.add_argument("--toc", default="html_output/main.toc", help="Path to main.toc")
    parser.add_argument("--downloads-dir", default="html_output/downloads", help="Directory containing Chapter PDFs")
    parser.add_argument("--out-dir", default="html_output/verification", help="Output directory root")
    parser.add_argument("--max-pages", type=int, default=7, help="Max pages per chunk before splitting by subsections (default: 7)")
    parser.add_argument("--chapters-dir", default="Chapters", help="Directory containing chapter .tex files")
    parser.add_argument("--bib", default="bibliography.bib", help="Path to bibliography.bib file")
    
    args = parser.parse_args()
    
    target_chapters = args.chapters
    toc_path = Path(args.toc)
    downloads_dir = Path(args.downloads_dir)
    out_dir_root = Path(args.out_dir)
    max_pages = args.max_pages
    chapters_dir = Path(args.chapters_dir)
    bib_path = Path(args.bib)
    
    if not toc_path.exists():
        print(f"Error: TOC file not found at {toc_path}")
        sys.exit(1)

    # Pre-load bibliography
    print(f"Loading bibliography from {bib_path}...")
    bib_entries = parse_bib_file(bib_path)
    print(f"  Loaded {len(bib_entries)} bibliography entries.")

    print(f"Reading TOC from {toc_path}...")
    try:
        chapters_data = parse_toc_for_chapters(toc_path, target_chapters)
    except Exception as e:
         print(f"Error parsing TOC: {e}")
         import traceback
         traceback.print_exc()
         sys.exit(1)

    for ch_num in target_chapters:
        if ch_num not in chapters_data:
            print(f"Warning: Chapter {ch_num} not found in TOC. Skipping.")
            continue
            
        data = chapters_data[ch_num]
        print(f"\nProcessing Chapter {ch_num}...")
        
        # Paths
        chapter_pdf_name = f"Chapter_{ch_num:02d}.pdf"
        chapter_pdf_path = downloads_dir / chapter_pdf_name
        
        if not chapter_pdf_path.exists():
            print(f"  Error: PDF {chapter_pdf_path} not found. Skipping.")
            continue
        
        # Find .tex file for this chapter
        tex_file = find_chapter_tex_file(chapters_dir, ch_num)
        tex_content = ""
        if tex_file and tex_file.exists():
            tex_content = _read_text(tex_file)
            print(f"  Found .tex file: {tex_file.name}")
        else:
            print(f"  Warning: No .tex file found for Chapter {ch_num}")
            
        # Output Dir for Chapter
        verify_chapter_dir = out_dir_root / f"Chapter_{ch_num:02d}"
        verify_chapter_dir.mkdir(parents=True, exist_ok=True)
        print(f"  Output: {verify_chapter_dir}")

        # 1. Copy Context TOCs
        shutil.copy(toc_path, verify_chapter_dir / "full_book.toc")
        ch_toc_path = verify_chapter_dir / f"Chapter_{ch_num:02d}.toc"
        with open(ch_toc_path, 'w', encoding='utf-8') as f:
            f.write("".join(data['raw_toc_lines']))
        
        # Copy full chapter .tex
        if tex_content:
            full_tex_path = verify_chapter_dir / f"Chapter_{ch_num:02d}_full.tex"
            with open(full_tex_path, 'w', encoding='utf-8') as f:
                f.write(tex_content)

        # Load PDF
        doc = fitz.open(chapter_pdf_path)
        n_pages = len(doc)
        
        # Calculate Chunks
        chunks = calculate_chunks(
            ch_start_page=data['start_page'],
            end_page_limit=data['end_page_limit'],
            toc_items=data['sections'],
            doc_page_count=n_pages,
            max_pages=max_pages
        )
        
        print(f"  Found {len(chunks)} output chunks/sections.")

        for sec_name, sub_name, start, end in chunks:
            
            # Directory Logic
            safe_sec_name = sanitize_filename(sec_name)
            
            if sub_name:
                # Nested: Section/Subsection
                safe_sub_name = sanitize_filename(sub_name)
                section_dir = verify_chapter_dir / safe_sec_name / safe_sub_name
                print(f"    Extracting [Nested]: {safe_sec_name}/{safe_sub_name} (Pages {start+1}-{end+1})")
                filename_base = safe_sub_name
                section_title_for_tex = sub_name  # Use subsection name for tex lookup
            else:
                # Flat: Section
                section_dir = verify_chapter_dir / safe_sec_name
                print(f"    Extracting [Flat]: {safe_sec_name} (Pages {start+1}-{end+1})")
                filename_base = safe_sec_name
                section_title_for_tex = sec_name

            section_dir.mkdir(parents=True, exist_ok=True)
            
            # Extract PDF
            try:
                new_doc = fitz.open()
                new_doc.insert_pdf(doc, from_page=start, to_page=end)
                pdf_out_path = section_dir / f"{filename_base}.pdf"
                new_doc.save(str(pdf_out_path), garbage=3, deflate=True)
                new_doc.close()
            except Exception as e:
                print(f"      Failed to extract PDF: {e}")
                
            # Extract Images
            img_idx = 1
            for i in range(start, end + 1):
                if i < len(doc):
                    extract_images_from_page(doc, i, section_dir, f"page_{img_idx}.png")
                img_idx += 1
            
            # Extract .tex content for this section
            if tex_content:
                # Try to extract section title from the original name
                # Remove the number prefix like "24.1_" to get the actual title
                title_parts = section_title_for_tex.split('_', 1)
                if len(title_parts) > 1:
                    search_title = title_parts[1]
                else:
                    search_title = section_title_for_tex
                
                # For flat sections (no sub_name), include all subsections in the content
                include_subs = (sub_name is None)
                section_tex = extract_tex_for_section(tex_content, search_title, include_subsections=include_subs)
                if section_tex:
                    tex_out_path = section_dir / "section_content.tex"
                    with open(tex_out_path, 'w', encoding='utf-8') as f:
                        f.write(section_tex)
                    
                    # Extract bibliography for this section
                    citation_keys = extract_citations_from_tex(section_tex)
                    if citation_keys:
                        bib_content = extract_bib_entries(bib_entries, citation_keys)
                        if bib_content:
                            bib_out_path = section_dir / "references.bib"
                            with open(bib_out_path, 'w', encoding='utf-8') as f:
                                f.write(bib_content)
                            print(f"      Extracted {len(citation_keys)} citations")
                
        doc.close()

    print("\nAll tasks completed.")



if __name__ == "__main__":
    main()

