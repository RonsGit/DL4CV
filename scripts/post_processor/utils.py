#!/usr/bin/env python3
"""
Utility functions for post-processing.
Includes text normalization, image path fixing, chapter discovery, and validation.
"""
import os
import re
from pathlib import Path
from . import config


def normalize_text(text: str) -> str:
    """Normalize text by replacing ligatures."""
    if not text:
        return ""
    for lig, rep in config.LIGATURES.items():
        text = text.replace(lig, rep)
    return text.strip()


def load_bib_index_map(bib_html_path: Path) -> dict:
    """Load bibliography.html and build key -> global_number map."""
    if not bib_html_path.exists():
        print(f"  Warning: {bib_html_path} not found, citation numbering won't be fixed")
        return {}
    
    content = bib_html_path.read_text(encoding='utf-8', errors='replace')
    entries = re.finditer(
        r'<div[^>]*class="bib-entry"[^>]*id="(bib-[^"]+)"[^>]*>.*?<div[^>]*class="bib-label"[^>]*>\[(\d+)\]</div>', 
        content, re.DOTALL
    )
    
    for e in entries:
        key = e.group(1).replace('bib-', '')
        num = e.group(2)
        config.BIB_INDEX_MAP[key] = num
    
    print(f"  Loaded {len(config.BIB_INDEX_MAP)} bibliography entries for citation numbering")
    return config.BIB_INDEX_MAP


def discover_chapters():
    """Discover chapter HTML files in the output directory."""
    config.CHAPTERS.clear()
    
    chapter_pattern = re.compile(r'Chapter_(\d+)_Lecture_\d+_(.+)\.html$')
    
    for f in sorted(config.HTML_OUTPUT_DIR.glob("Chapter_*.html")):
        m = chapter_pattern.match(f.name)
        if m:
            num = int(m.group(1))
            
            # Content-based title extraction
            title = ""
            try:
                content = f.read_text(encoding='utf-8', errors='replace')
                # Extract <title> content
                title_match = re.search(r'<title>(.*?)</title>', content, re.IGNORECASE | re.DOTALL)
                if title_match:
                    raw_title = title_match.group(1).strip()
                    # Remove "Lecture X: " prefix if present
                    # Matches "Lecture 1: ", "Lecture 22: ", etc.
                    title = re.sub(r'^Lecture\s+\d+:\s+', '', raw_title)
            except Exception as e:
                print(f"  Warning: Could not read title from {f.name}: {e}")
            
            # Fallback to filename if extraction failed
            if not title:
                raw_title_from_file = m.group(2).replace('_', ' ')
                title = re.sub(r'\s+', ' ', raw_title_from_file).strip()
            
            config.CHAPTERS.append({
                'num': num,
                'title': title,
                'file': f.name,
                'path': f
            })
    
    config.CHAPTERS.sort(key=lambda x: x['num'])
    print(f"  Discovered {len(config.CHAPTERS)} chapters")
    return config.CHAPTERS


def fix_image_paths(content: str) -> str:
    """
    Scans content for <img> tags and fixes src attributes for Linux case sensitivity.
    Example: src="Figures/Chapter_1/Img.png" -> src="Figures/Chapter_1/img.png"
    """
    def repl(m):
        raw_src = m.group(1)
        # Skip external links
        if raw_src.startswith(('http:', 'https:', 'data:', '//')):
            return m.group(0)
            
        # Check explicit existence first
        full_path = config.HTML_OUTPUT_DIR / raw_src
        if full_path.exists():
            return m.group(0)
            
        # Path parts processing
        try:
            parts = Path(raw_src).parts
            current_dir = config.HTML_OUTPUT_DIR
            resolved_parts = []
            
            for part in parts:
                if not current_dir.exists():
                    return m.group(0)
                    
                # List dir entries case-insensitively
                found = False
                for entry in os.listdir(current_dir):
                    if entry.lower() == part.lower():
                        current_dir = current_dir / entry
                        resolved_parts.append(entry)
                        found = True
                        break
                
                if not found:
                    return m.group(0)
            
            # Reconstruct path
            new_src = "/".join(resolved_parts)
            if new_src != raw_src:
                print(f"    [ImgFix] {raw_src} -> {new_src}")
                return f'src="{new_src}"'
                
        except Exception as e:
            print(f"    [ImgWarn] Error fixing {raw_src}: {e}")
            
        return m.group(0)

    return re.sub(r'src="([^"]+)"', repl, content)


def validate_output_safety(html_content: str, filename: str) -> tuple:
    """
    Validates that output HTML is safe to write (not empty/corrupted).
    Returns: (is_safe: bool, error_message: str)
    """
    if not html_content:
        return False, f"Empty content for {filename}"
    
    if len(html_content) < config.MIN_CONTENT_LENGTH:
        return False, f"Content too short ({len(html_content)} chars) for {filename}"
    
    # Check for basic HTML structure
    if '<html' not in html_content.lower():
        return False, f"Missing <html> tag in {filename}"
    
    if '<body' not in html_content.lower():
        return False, f"Missing <body> tag in {filename}"
    
    # Check for doc_content (main content area)
    if 'id="doc_content"' not in html_content and 'id=\'doc_content\'' not in html_content:
        # Not all pages have doc_content, so just warn
        pass
    
    return True, ""
