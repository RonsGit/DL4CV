#!/usr/bin/env python3
"""
scripts/create_navigation.py (Surgical Merge v4)
10-Point Fix Plan Implementation:
0) Core Rules: Preserve Math Protection & Lazy Loading.
1) Aux Pages: Restore centered card layout (v2), margins, and content for Home, Preface, DepGraph.
2) Top Bar: Restore full UI (Prev/Next, Top, PDF Dropdown) from v2.
3) Bottom Nav: Restore "Lecture X" card design (Gray/Blue) from v2.
4) Sidebar: Fix ordering (Bib BEFORE Chapters), nested TOC (H2/H3), highlight logic.
5) Part Nav: Fix "Prev/Next Part" to traverse subsections (H3) if present.
6) Images: Max-width 85%, keep aspect ratio, strip fixed dims, keep lazy/lightbox.
7) Code: Add Copy button & Syntax Highlighting (highlight.js).
8) Lists: Fix enumerate/itemize spacing via CSS (inline label).
9) Citations: Rewrite links to `bibliography.html#bib-KEY`.
10) Bibliography: Restore "Premium" detail layout & anchors from v2.
11) Idempotency: distinct wrapper detection to prevent nested cards.
"""

import os
import re
import sys
import json
import shutil
import time
import hashlib
from pathlib import Path
import argparse

# --- CONFIGURATION ---
BASE_URL = "" # Set via --base-url
HTML_OUTPUT_DIR = Path("html_output")
BIB_MAPPING = {}
BIB_DATA = {}
BIB_INDEX_MAP = {}  # D0: Maps normalized bib key -> global bibliography number
CHAPTERS = []
LIGATURES = {
    'ﬀ': 'ff', 'ﬂ': 'fl', 'ﬃ': 'ffi', 'ﬄ': 'ffl', 'ﬁ': 'fi', 'ﬅ': 'st'
}

# --- CONTENT SAFETY GUARDRAILS ---
MIN_CONTENT_LENGTH = 500  # Minimum characters in doc_content to prevent content wiping

def load_bib_index_map(bib_html_path: Path) -> dict:
    """D0: Load bibliography.html and build key -> global_number map."""
    global BIB_INDEX_MAP

    # Try multiple possible paths
    paths_to_try = [
        bib_html_path,
        Path("html_output/bibliography.html"),
        Path("./html_output/bibliography.html"),
    ]

    actual_path = None
    for p in paths_to_try:
        if p.exists():
            actual_path = p
            break

    if not actual_path:
        print(f"  Warning: bibliography.html not found in any expected location, citation numbering won't be fixed")
        print(f"    Tried: {[str(p) for p in paths_to_try]}")
        return {}

    print(f"  Loading bibliography from: {actual_path}")
    content = actual_path.read_text(encoding='utf-8', errors='replace')

    # Match: <div class="bib-entry" id="bib-KEY">...<div class="bib-label">[N]</div>
    entries = re.finditer(r'<div[^>]*class="bib-entry"[^>]*id="(bib-[^"]+)"[^>]*>.*?<div[^>]*class="bib-label"[^>]*>\[(\d+)\]</div>', content, re.DOTALL)

    for e in entries:
        key = e.group(1).replace('bib-', '')  # Extract key without "bib-" prefix
        num = e.group(2)
        BIB_INDEX_MAP[key] = num

    print(f"  Loaded {len(BIB_INDEX_MAP)} bibliography entries for citation numbering")
    if len(BIB_INDEX_MAP) > 0:
        # Print first 3 entries for debug
        sample = list(BIB_INDEX_MAP.items())[:3]
        print(f"    Sample entries: {sample}")
    return BIB_INDEX_MAP

def normalize_text(text: str) -> str:
    if not text: return ""
    for lig, rep in LIGATURES.items():
        text = text.replace(lig, rep)
    return text.strip()

# -----------------------------------------------------------------------------
# 0. MATH PROTECTION (Robust - Keep from Current/v3)
# -----------------------------------------------------------------------------
MATH_STORE = {}

def protect_math(content: str) -> str:
    """Replace LaTeX math containers with placeholder tokens."""
    global MATH_STORE
    MATH_STORE = {}
    
    def repl(m):
        token = f"MATH_TOKEN_{len(MATH_STORE)}__"
        MATH_STORE[token] = m.group(0)
        return token

    # 1. Scripts/MathJax/MathML
    content = re.sub(r'<script[^>]*type=["\']math/tex[^"\']*["\'][^>]*>.*?</script>', repl, content, flags=re.DOTALL)
    content = re.sub(r'<mjx-container[^>]*>.*?</mjx-container>', repl, content, flags=re.DOTALL)
    content = re.sub(r'<math[^>]*>.*?</math>', repl, content, flags=re.DOTALL)
    
    # 2. LaTeX Display/Inline (if unprocessed)
    content = re.sub(r'\\\[(.*?)\\\]', repl, content, flags=re.DOTALL)
    content = re.sub(r'\$\$(.*?)\$\$', repl, content, flags=re.DOTALL)
    content = re.sub(r'\\\((.*?)\\\)', repl, content, flags=re.DOTALL)
    
    return content

def restore_math(content: str) -> str:
    """Restore placeholders to original tokens."""
    if not MATH_STORE: return content
    # Reverse order sometimes helps but dict strict replacement is usually fine
    pattern = re.compile("|".join(re.escape(k) for k in MATH_STORE.keys()))
    def repl(m): return MATH_STORE[m.group(0)]
    return pattern.sub(repl, content)

def clean_latex_artifacts(content: str) -> str:
    """Clean specific LaTeX artifacts that escape math processing."""
    # Fix \bm -> \boldsymbol (MathJax supported)
    content = content.replace(r'\bm', r'\boldsymbol')

    # Fix \# inside \mbox{} - MathJax doesn't handle \# in text mode properly
    # Convert \mbox{\#...} to \mbox{#...} (remove the backslash before #)
    content = re.sub(r'(\\mbox\s*\{[^}]*)\\#', r'\1#', content)
    # Also handle \text{} which is similar to \mbox{}
    content = re.sub(r'(\\text\s*\{[^}]*)\\#', r'\1#', content)
    # Handle standalone \# that's not inside a command that needs it
    # In MathJax, \# outside of special contexts should just be #

    # Specific artifact replacements
    # Valid replacement for Checkmark (\mathchar"458) - Handle optional space and quotes
    content = re.sub(r'\\mathchar"?\s*458', '&#10003;', content, flags=re.IGNORECASE)
    content = content.replace(r'\noindent', '')

    # Generic \mathchar removal (hex, octal, decimal) - Aggressive cleanup
    content = re.sub(r'\\mathchar"?\s*[0-9a-fA-F]+', '', content, flags=re.IGNORECASE)
    content = re.sub(r'\\mathchar\'?\s*[0-7]+', '', content, flags=re.IGNORECASE)
    content = re.sub(r'\\mathchar\s*\d+', '', content, flags=re.IGNORECASE)
    
    # Remove \m@th (internal TeX token)
    content = content.replace(r'\m@th', '')

    # Remove \hskip (spacing artifacts)
    content = re.sub(r'\\hskip\s*[\d\.]+[a-z]+', '', content)
    
    # Remove \vskip and \relax
    content = re.sub(r'\\vskip\s*-?[\d\.]+\s*[a-z]{2}', '', content)
    content = content.replace(r'\relax', '')
    
    # Remove long runs of underscores (visual separators)
    content = re.sub(r'_{5,}', '', content)
    return content

# -----------------------------------------------------------------------------
# CSS & TEMPLATES (Merged v2 UI + v3 Fixes)
# -----------------------------------------------------------------------------
# -----------------------------------------------------------------------------
# CSS & TEMPLATES (Merged v2 UI + v3 Fixes)
# -----------------------------------------------------------------------------
def get_asset_url(rel_path: str, is_aux: bool = False) -> str:
    """
    Returns the web-ready URL for an asset.
    If BASE_URL is set, uses absolute path: /CVBook/path/to/file
    Else, uses relative path: ../path/to/file or path/to/file
    """
    if BASE_URL:
        # Absolute path for GitHub Pages
        clean_base = BASE_URL.rstrip('/')
        clean_path = rel_path.lstrip('/')
        return f"{clean_base}/{clean_path}"
    else:
        # Relative path for local filesystem browsing
        prefix = "../" if is_aux else ""
        return f"{prefix}{rel_path}"

def get_common_head(title, is_aux=False):
    css_path = get_asset_url("pagefind/pagefind-ui.css", is_aux)
    js_path = get_asset_url("pagefind/pagefind-ui.js", is_aux)
    
    from datetime import datetime
    build_time = datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")
    return f"""
    <!-- NAV_BUILD_STAMP: {build_time} -->
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <meta name="generator" content="create_navigation.py v2.0 {build_time}">
    <title>{title}</title>
    <link rel="icon" type="image/x-icon" href="{get_asset_url('Pictures/favicon.ico', is_aux)}">
    <link rel="icon" type="image/png" sizes="32x32" href="{get_asset_url('Pictures/favicon-32x32.png', is_aux)}">
    <link href="https://fonts.googleapis.com/css2?family=Lato:wght@300;400;700;900&family=Roboto+Mono:wght@500&family=Outfit:wght@400;700&display=swap" rel="stylesheet">
    <script>
        window.MathJax = {{
            tex: {{ 
                tags: 'ams', 
                inlineMath: [['$', '$'], ['\\\\(', '\\\\)']],
                macros: {{
                    // Text formatting commands - use mathtt for monospace
                    textsc: ['\\\\mathsf{{#1}}', 1],
                    texttt: ['\\\\mathtt{{#1}}', 1],
                    textrm: ['\\\\mathrm{{#1}}', 1],
                    textsf: ['\\\\mathsf{{#1}}', 1],
                    // Matrix compatibility
                    bordermatrix: ['\\\\begin{{array}}{{l}}\\\\text{{[Matrix]}}\\\\end{{array}}', 0],
                    cr: ['\\\\\\\\', 0],
                    // Indicator function
                    ind: ['\\\\mathbb{{1}}', 0],
                    // Fix for rotatebox - render as subset symbol
                    rotatebox: ['\\\\subset', 2],
                    // Fix hdots -> cdots
                    hdots: ['\\\\cdots', 0],
                    // Fix boldsymbolod typo -> mod
                    boldsymbolod: ['\\\\bmod', 0]
                }}
            }},
            options: {{ 
                skipHtmlTags: ['script', 'noscript', 'style', 'textarea', 'pre', 'code'], 
                processEscapes: true,
                ignoreHtmlClass: 'tex2jax_ignore',
                macros: {{
                    bm: ['\\\\boldsymbol{{#1}}', 1],
                }},
                renderActions: {{
                    addMenu: [0, '', '']
                }}
            }},
            startup: {{
                ready: function() {{
                    MathJax.startup.defaultReady();
                }}
            }}
        }};
    </script>
    <script src="https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js" async crossorigin="anonymous"></script>
    <link href="{css_path}" rel="stylesheet">
    <script src="{js_path}"></script>
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.1/css/all.min.css" crossorigin="anonymous">
    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/styles/vs2015.min.css" crossorigin="anonymous">
    <script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/highlight.min.js" crossorigin="anonymous"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/languages/python.min.js" crossorigin="anonymous"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/languages/cpp.min.js" crossorigin="anonymous"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/languages/bash.min.js" crossorigin="anonymous"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/highlight.js/11.9.0/languages/javascript.min.js" crossorigin="anonymous"></script>
    <style>
        :root {{ 
            --primary: #1fa2e0; --bg: #ffffff; --text: #2d3436;
            --gray-50: #fafafa; --gray-100: #f8f9fa; --gray-200: #e9ecef; --gray-300: #dee2e6;
            --header-h: 70px;
            --sidebar-w: 300px;
            --sidebar-w-collapsed: 60px;
            --ocre: #1fa2e0; /* Changed from #C65313 to Blue per user request (Step 3447) */
        }}
        @media (prefers-color-scheme: dark) {{
            :root {{ 
                --bg: #ffffff; /* Revert to white background by default to satisfy user "no reason blue" complaint */
                --text: #2d3436; 
                --gray-50: #fafafa; --gray-100: #f8f9fa; --gray-200: #e9ecef; --gray-300: #dee2e6;
            }}
            /* Only allow dark mode for specifically optimized elements if needed, otherwise keep it clean */
        }}
        * {{ box-sizing: border-box; }}
        html, body {{ height: 100%; overflow: hidden; margin: 0; padding: 0; font-family: 'Outfit', sans-serif; color: var(--text); background: var(--bg); display: flex; line-height: 1.6; }}
        
        /* MathJax error styling - completely hide error boxes */
        mjx-merror {{ display: none !important; }}
        
        /* Bug 4: MathJax equation containers - NO scrollbars or gray artifacts */
        mjx-container, mjx-math,
        .MathJax, .MathJax_Display {{
            overflow: visible !important;
            scrollbar-width: none !important;
            -ms-overflow-style: none !important;
            outline: none !important;
            box-shadow: none !important;
        }}
        /* Background transparent on containers only - NOT on rendering elements like mjx-line */
        mjx-container, mjx-math, mjx-mrow, mjx-mi, mjx-mo, mjx-mn, mjx-mtext,
        mjx-mspace, mjx-mstyle, mjx-merror, mjx-mpadded {{
            background: transparent !important;
        }}

        /* CRITICAL FIX: Constrain stretchy VERTICAL delimiters to prevent long black lines */
        /* The mjx-ext element extends infinitely if not constrained - use clip to cut off overflow */
        mjx-stretchy-v {{
            contain: paint !important;
            overflow: hidden !important;
            max-height: 100% !important;
            display: inline-block !important;
            vertical-align: middle !important;
        }}
        mjx-stretchy-v > mjx-ext {{
            max-height: 100% !important;
            overflow: hidden !important;
            display: block !important;
        }}
        /* The mjx-ext child of stretchy-v draws the extension line - MUST be clipped */
        mjx-stretchy-v mjx-ext {{
            max-height: inherit !important;
            overflow: hidden !important;
            clip-path: inset(0) !important;
        }}
        /* Bracket delimiters in mtd (table cells) - common in matrices */
        mjx-mtd mjx-stretchy-v {{
            contain: strict !important;
            overflow: clip !important;
        }}
        /* Delimited groups (matrices with brackets) */
        mjx-mrow > mjx-mo > mjx-stretchy-v {{
            overflow: clip !important;
        }}
        /* Allow math containers to render naturally */
        mjx-mrow, mjx-math, mjx-frac, mjx-msub, mjx-msup, mjx-msubsup {{
            overflow: visible !important;
        }}

        /* =================================================================== */
        /* UNDERBRACE / OVERBRACE FIX                                         */
        /* =================================================================== */
        /* The horizontal bar issue is caused by mjx-ext (extension element)  */
        /* extending beyond bounds. We clip mjx-ext but keep brace ends visible */
        /* IMPORTANT: Do NOT change display or vertical-align on mjx-munder   */
        /* as it breaks the natural MathJax alignment                         */

        /* Only set overflow, don't touch display or alignment */
        mjx-munder, mjx-mover, mjx-munderover {{
            overflow: visible !important;
        }}

        mjx-munder > mjx-row, mjx-mover > mjx-row, mjx-munderover > mjx-row {{
            overflow: visible !important;
        }}

        /* The stretchy-h container itself - use clip to prevent bar overflow */
        mjx-stretchy-h {{
            overflow: clip !important;
        }}

        /* The extension piece (mjx-ext) draws the connecting line - MUST clip */
        mjx-stretchy-h > mjx-ext {{
            overflow: hidden !important;
        }}

        /* Underbrace labels need visibility */
        mjx-munder > mjx-row > mjx-cell, mjx-munderover > mjx-row > mjx-cell {{
            overflow: visible !important;
        }}

        /* Prevent any child from creating unwanted visual artifacts */
        mjx-c {{
            background: transparent !important;
        }}
        /* Hide assistive MML completely - it can cause gray boxes */
        mjx-assistive-mml {{
            display: none !important;
            visibility: hidden !important;
            position: absolute !important;
            width: 1px !important;
            height: 1px !important;
            padding: 0 !important;
            margin: -1px !important;
            overflow: hidden !important;
            clip: rect(0,0,0,0) !important;
            border: 0 !important;
        }}
        mjx-container::-webkit-scrollbar, mjx-container *::-webkit-scrollbar,
        mjx-math::-webkit-scrollbar, mjx-math *::-webkit-scrollbar,
        .MathJax::-webkit-scrollbar, .MathJax *::-webkit-scrollbar,
        .MathJax_Display::-webkit-scrollbar, .MathJax_Display *::-webkit-scrollbar {{
            display: none !important;
            width: 0 !important;
            height: 0 !important;
            background: transparent !important;
            visibility: hidden !important;
        }}
        mjx-container {{ margin: 0.3em 0 !important; padding: 0 !important; max-width: 100%; }}
        mjx-container[display="true"] {{ margin: 0.5em 0 !important; max-width: 100%; }}

        /* Right-side overflow fix for Ch 20 and other content */
        p, li {{ word-break: break-word; overflow-wrap: break-word; scrollbar-width: none !important; -ms-overflow-style: none !important; }}
        p::-webkit-scrollbar, li::-webkit-scrollbar {{ display: none !important; width: 0 !important; height: 0 !important; }}
        .content-scroll table {{ max-width: 100%; }}
        .content-scroll .card {{ overflow-x: auto; scrollbar-width: none !important; -ms-overflow-style: none !important; }}
        .content-scroll .card::-webkit-scrollbar {{ display: none !important; width: 0 !important; height: 0 !important; }}
        .math-display, .mathjax-block, div.mathjax-block, .mathjax-env, div.mathjax-env {{
            max-width: 100%;
            overflow: visible !important;
            overflow-x: visible !important;
            overflow-y: visible !important;
            scrollbar-width: none !important;
            -ms-overflow-style: none !important;
            display: block !important;
        }}
        .math-display::-webkit-scrollbar, .mathjax-block::-webkit-scrollbar, div.mathjax-block::-webkit-scrollbar,
        .mathjax-env::-webkit-scrollbar, div.mathjax-env::-webkit-scrollbar {{
            display: none !important;
            width: 0 !important;
            height: 0 !important;
            background: transparent !important;
            visibility: hidden !important;
        }}
        /* Equation containers - no scrollbars, allow natural overflow */
        .mathjax-equation, div.mathjax-equation {{
            overflow: visible !important;
            overflow-x: visible !important;
            scrollbar-width: none !important;
            -ms-overflow-style: none !important;
        }}
        .mathjax-equation::-webkit-scrollbar, div.mathjax-equation::-webkit-scrollbar {{
            display: none !important;
            width: 0 !important;
            height: 0 !important;
        }}
        /* Inline math spans - no scrollbars */
        .mathjax-inline {{
            overflow: visible !important;
            scrollbar-width: none !important;
            -ms-overflow-style: none !important;
            display: inline;
        }}
        .mathjax-inline::-webkit-scrollbar {{
            display: none !important;
        }}
        
        /* UNIVERSAL SCROLLBAR HIDING - applies to ALL elements that might show scrollbars */
        /* This is a catch-all to ensure no scrollbar ever appears on any math content */
        #doc_content, #doc_content *, .card, .card *, .card-body, .card-body *,
        p, li, dd, dt, .content-scroll, .content-scroll * {{
            scrollbar-width: none !important;
            -ms-overflow-style: none !important;
        }}
        #doc_content::-webkit-scrollbar, #doc_content *::-webkit-scrollbar,
        .card::-webkit-scrollbar, .card *::-webkit-scrollbar,
        .card-body::-webkit-scrollbar, .card-body *::-webkit-scrollbar,
        p::-webkit-scrollbar, li::-webkit-scrollbar, dd::-webkit-scrollbar,
        .content-scroll *::-webkit-scrollbar {{
            display: none !important;
            width: 0 !important;
            height: 0 !important;
            background: transparent !important;
        }}

        /* Dark Mode Support - use !important to override mobile styles */
        body.dark-mode {{ --bg: #1a1a2e; --text: #e4e4e4; --gray-50: #252540; --gray-100: #2a2a45; --gray-200: #3a3a55; --gray-300: #4a4a65; }}
        body.dark-mode .sidebar {{ background: #1f1f3a !important; border-color: #3a3a55 !important; color: #e4e4e4 !important; }}
        body.dark-mode .card {{ background: #252540 !important; border-color: #3a3a55 !important; }}
        body.dark-mode .top-bar {{ background: #1a1a2e !important; border-color: #3a3a55 !important; color: #e4e4e4 !important; }}
        body.dark-mode pre {{ background: #0d0d1a !important; border-color: #3a3a55 !important; }}
        body.dark-mode .chapter-item > a {{ color: #9ca3af !important; }}
        body.dark-mode table {{ background: #252540 !important; color: #e4e4e4 !important; }}
        body.dark-mode table th, body.dark-mode table td {{ color: #e4e4e4 !important; border-color: #555 !important; }}
        body.dark-mode .accessibility-menu {{ background: #252540 !important; }}
        body.dark-mode p, body.dark-mode li {{ color: #e4e4e4 !important; }}
        /* Dark mode headings - make them light colored for readability */
        body.dark-mode h1, body.dark-mode h2, body.dark-mode h3, body.dark-mode h4, body.dark-mode h5, body.dark-mode h6,
        body.dark-mode .sectionHead, body.dark-mode .subsectionHead, body.dark-mode .subsubsectionHead,
        body.dark-mode .paragraphHead, body.dark-mode .likeparagraphHead, body.dark-mode .page-title {{
            color: #ffffff !important;
        }}
        /* Dark mode sidebar TOC links - fix unreadable dark text on dark background */
        body.dark-mode .toc-h3 > a {{ color: #cbd5e0 !important; }}
        body.dark-mode .toc-h4 > a {{ color: #a0aec0 !important; }}
        body.dark-mode .toc-h5 > a {{ color: #718096 !important; }}
        body.dark-mode .toc-h3.active-scroll > a,
        body.dark-mode .toc-h3.active-parent > a {{ color: #63b3ed !important; }}
        body.dark-mode .toc-h4.active-scroll > a {{ color: #63b3ed !important; }}
        body.dark-mode .toc-h5.active-scroll > a {{ color: #63b3ed !important; }}
        /* Dark mode local TOC background and general link colors */
        body.dark-mode .local-toc {{ background: rgba(255,255,255,0.05) !important; }}
        body.dark-mode .local-toc a {{ color: #e0e0e0 !important; }}

        /* High Contrast Mode - use !important to override mobile styles */
        body.high-contrast {{ --bg: #000; --text: #fff; --primary: #ffff00; --gray-50: #111; --gray-100: #222; --gray-200: #333; --gray-300: #444; }}
        body.high-contrast .sidebar {{ background: #000 !important; border-color: #fff !important; color: #fff !important; }}
        body.high-contrast .card {{ background: #000 !important; border-color: #fff !important; }}
        body.high-contrast .top-bar {{ background: #000 !important; border-color: #fff !important; color: #fff !important; }}
        body.high-contrast a {{ color: #ffff00 !important; }}
        body.high-contrast table {{ background: #000 !important; border-color: #fff !important; }}
        body.high-contrast p, body.high-contrast li {{ color: #fff !important; }}
        /* High contrast headings - make them white for readability on black background */
        body.high-contrast h1, body.high-contrast h2, body.high-contrast h3, body.high-contrast h4, body.high-contrast h5, body.high-contrast h6,
        body.high-contrast .sectionHead, body.high-contrast .subsectionHead, body.high-contrast .subsubsectionHead,
        body.high-contrast .paragraphHead, body.high-contrast .likeparagraphHead, body.high-contrast .page-title {{
            color: #ffffff !important;
        }}
        body.high-contrast table th, body.high-contrast table td {{ color: #fff !important; border-color: #fff !important; }}
        /* High contrast floating buttons - yellow background with black text/icons */
        body.high-contrast .float-btn {{ background: #ffff00 !important; color: #000 !important; border: 3px solid #fff !important; }}
        body.high-contrast .float-btn i {{ color: #000 !important; }}
        body.high-contrast .accessibility-btn {{ background: #ffff00 !important; color: #000 !important; border: 3px solid #fff !important; }}
        body.high-contrast .accessibility-btn i {{ color: #000 !important; }}
        body.high-contrast .accessibility-option {{ color: #000 !important; background: #ffff00 !important; }}
        body.high-contrast .accessibility-option i {{ color: #000 !important; }}
        /* High contrast STAR button in sidebar */
        body.high-contrast .repo-links a {{ background: #ffff00 !important; color: #000 !important; border-color: #fff !important; }}
        /* High contrast dropdown - dark background with yellow text */
        body.high-contrast .dropdown-content {{ background: #000 !important; border-color: #fff !important; }}
        body.high-contrast .dropdown-content a {{ color: #ffff00 !important; background: #000 !important; }}
        body.high-contrast .dropdown-content a:hover {{ background: #333 !important; }}
        /* Dark mode dropdown styling */
        body.dark-mode .dropdown-content {{ background: #252540 !important; border-color: #3a3a55 !important; }}
        body.dark-mode .dropdown-content a {{ color: #e4e4e4 !important; }}
        body.dark-mode .dropdown-content a:hover {{ background: #3a3a55 !important; }}
        
        /* Accessibility Button - positioned above float nav */
        /* Accessibility Button - styled to match float-btn exactly */
        .accessibility-btn {{ 
            width: 46px; height: 46px; border-radius: 50%; background: var(--primary); color: white; border: none; 
            box-shadow: 0 8px 25px rgba(31,162,224,0.4); cursor: pointer; display: flex; align-items: center; justify-content: center; 
            font-size: 1.2rem; transition: opacity 0.2s, transform 0.2s; opacity: 0.5; 
        }}
        .accessibility-btn:hover {{ transform: translateY(-2px); opacity: 1; }}
        .accessibility-menu {{ position: absolute; bottom: 60px; right: 0; background: white; border-radius: 12px; box-shadow: 0 8px 30px rgba(0,0,0,0.15); padding: 0.75rem; min-width: 200px; display: none; z-index: 2500; }}
        .accessibility-menu.open {{ display: block; }}
        .accessibility-option {{ display: flex; align-items: center; gap: 0.75rem; padding: 0.6rem 0.8rem; border-radius: 8px; cursor: pointer; transition: background 0.2s, border 0.2s; color: var(--text); font-size: 0.9rem; border: 2px solid transparent; }}
        .accessibility-option:hover {{ background: var(--gray-100); }}
        .accessibility-option i {{ width: 20px; text-align: center; color: var(--primary); }}
        .accessibility-option.active {{ background: rgba(31,162,224,0.2); border: 2px solid var(--primary); font-weight: 700; box-shadow: 0 2px 8px rgba(31,162,224,0.3); }}
        .accessibility-option.active i {{ color: var(--primary); font-weight: 900; }}
        .accessibility-option.active::after {{ content: '\u2713'; margin-left: auto; color: var(--primary); font-weight: 900; font-size: 1.1rem; }}
        /* Sidebar - Fixed full height */
        .sidebar {{
            position: fixed;
            top: 0;
            left: 0;
            width: var(--sidebar-w);
            height: 100vh;
            background: #f8f9fa;
            border-right: 1px solid #dee2e6;
            display: flex; flex-direction: column; flex-shrink: 0;
            overflow-y: auto;
            z-index: 1000;
            transition: width 0.3s ease;
            padding-bottom: 0; /* Remove bottom padding to eliminate white space */
        }}
        
        /* Mini-sidebar mode */
        .sidebar.collapsed {{
            width: var(--sidebar-w-collapsed) !important;
            overflow: hidden !important;
        }}
        /* Hide text elements in collapsed mode */
        .sidebar.collapsed .chapter-list,
        .sidebar.collapsed .header-title a,
        .sidebar.collapsed .repo-links,
        .sidebar.collapsed hr,
        .sidebar.collapsed .sidebar-header .header-title span {{ display: none !important; }}
        
        /* Center hamburger in collapsed mode */
        .sidebar.collapsed .sidebar-header {{
            height: var(--header-h);
            padding: 0;
            justify-content: center;
            align-items: center;
            display: flex;
        }}
        .sidebar.collapsed .sidebar-toggle {{ margin: 0; font-size: 1.4rem; }}
        
        .main-wrapper {{ 
            margin-left: var(--sidebar-w); 
            flex: 1; 
            width: calc(100% - var(--sidebar-w)); 
            min-height: 100vh; 
            display: flex; 
            flex-direction: column; 
            transition: margin-left 0.3s ease, width 0.3s ease; 
            overflow-x: hidden;
        }}
        
        .sidebar.collapsed ~ .main-wrapper {{ 
            margin-left: var(--sidebar-w-collapsed); 
            width: calc(100% - var(--sidebar-w-collapsed));
        }}
        /* Sidebar resize handle - fixed position for full-height control */
        .resize-handle {{
            position: fixed;
            left: calc(var(--sidebar-w) - 4px);
            top: 0;
            width: 8px;
            height: 100vh;
            cursor: col-resize;
            z-index: 1002;
            transition: background 0.2s, left 0.3s ease;
        }}
        .resize-handle:hover {{ background: var(--primary); }}
        .resize-handle::before {{ content: ''; position: absolute; left: 3px; top: 50%; transform: translateY(-50%); width: 2px; height: 40px; background: var(--gray-300); border-radius: 2px; transition: background 0.2s; }}
        .resize-handle:hover::before {{ background: var(--primary); }}

        /* Hide resize handle on mobile */
        @media (max-width: 768px) {{
            .resize-handle {{ display: none !important; }}
        }}

        /* Sidebar Title */
        .sidebar-header {{ 
            height: var(--header-h); 
            padding: 0 1rem; 
            font-weight: 900; 
            letter-spacing: 1px; 
            color: var(--primary); 
            border-bottom: 2px solid var(--gray-200); 
            font-size: 1.1rem; 
            text-transform: uppercase; 
            display: flex; 
            align-items: center; 
            justify-content: space-between;
            box-sizing: border-box; /* E1: Ensure padding included in height */
            flex-shrink: 0; /* E1: Prevent header from shrinking */
        }}
        
        .sidebar-toggle {{ background: none; border: none; cursor: pointer; font-size: 1.2rem; color: var(--primary); padding: 0.5rem; flex-shrink: 0; }}
        .sidebar-toggle:hover {{ color: var(--text); }}
        
        /* A2: Sidebar font color consistency - uniformly gray by default */
        .chapter-list {{ list-style: none; padding: 0 0 4rem 0; margin: 0; flex: 1; }}
        .chapter-item > a {{ display: block; padding: 0.8rem 1.5rem; text-decoration: none; color: #6b7280; font-size: 1.0rem; font-weight: 500; border-left: 4px solid transparent; transition: all 0.15s; }}
        .chapter-item > a:visited {{ color: #6b7280; }} /* A2: Override visited link color */
        .chapter-item > a:hover {{ background: rgba(0,0,0,0.05); color: #374151; }}
        .chapter-item.active > a {{ border-left-color: var(--primary); background: rgba(31,162,224,0.08); color: var(--primary); font-weight: 700; }}
        
        /* Nested TOC (H2/H3) - Accordion Logic */
        .local-toc {{ list-style: none; padding: 0; margin: 0; background: rgba(0,0,0,0.02); display: none; }}
        .chapter-item.active .local-toc {{ display: block; }}
        
        
        /* Issue 3: Stronger hierarchy styling for H3 parent -> H4 child */
        /* H3 = Parent sections (bold, primary font) */
        .toc-h3 > a {{ display: block; padding: 0.6rem 1rem 0.6rem 1.5rem; font-size: 0.92rem; color: #2d3748; font-weight: 600; text-decoration: none; border-left: 3px solid transparent; transition: background 0.15s; }}
        .toc-h3 > a:hover {{ background: rgba(0,0,0,0.05); }}
        .toc-h3.active-scroll > a {{ color: var(--primary); border-left-color: var(--primary); background: rgba(31,162,224,0.05); }}
        .toc-h3.active-parent > a {{ color: var(--primary); font-weight: 700; }}
        
        /* Default: Hidden sub-lists (Issue 3: accordion) - CRITICAL: high specificity to force hide */
        .sidebar .local-toc .toc-sub-list {{ display: none !important; padding: 0; margin: 0; list-style: none; }}
        .sidebar .local-toc .toc-sub-list.visible {{ display: block !important; }}
        
        /* H4 = Child subsections (smaller, indented, lighter) */
        .toc-h4 > a {{ display: block; padding: 0.35rem 1rem 0.35rem 2.8rem; font-size: 0.83rem; color: #718096; font-weight: 400; text-decoration: none; transition: background 0.15s; }}
        .toc-h4 > a:hover {{ background: rgba(0,0,0,0.05); }}
        .toc-h4.active-scroll > a {{ color: var(--primary); font-weight: 600; }}
        
        /* H5 = Sub-subsections / enrichments (even smaller, more indented) */
        .toc-h5 > a {{ display: block; padding: 0.3rem 1rem 0.3rem 3.5rem; font-size: 0.8rem; color: #a0aec0; font-weight: 400; text-decoration: none; transition: background 0.15s; }}
        .toc-h5 > a:hover {{ background: rgba(0,0,0,0.05); }}
        .toc-h5.active-scroll > a {{ color: var(--primary); font-weight: 600; }}
        
        /* Enrichment emoji in TOC - safe rendering to prevent overlap */
        .toc-emoji {{ display: inline-block; margin-left: 0.4em; vertical-align: middle; font-size: 0.9em; }}
        .toc-enrichment > a {{ display: flex; align-items: center; gap: 0.4em; }}

        /* Main Area */
        .content-scroll {{
            overflow-y: auto; overflow-x: hidden; flex: 1;
            padding: 2rem 1rem;
            scroll-behavior: smooth; font-size: 1.15rem;
        }}
        .container {{ max-width: 90%; margin: 0 auto; width: 100%; }}
        .card {{ background: var(--bg); border: 1px solid var(--gray-300); border-radius: 16px; box-shadow: 0 10px 40px rgba(0,0,0,0.05); padding: 2.5rem; margin: 1.5rem 0; content-visibility: auto; contain-intrinsic-size: 1000px; }}
        @media (max-width: 768px) {{ .card {{ padding: 1.5rem; }} }}

        /* Top Bar - Sticky */
        .top-bar {{ 
            height: var(--header-h); 
            background: var(--bg); 
            border-bottom: 1px solid var(--gray-300); 
            display: flex; align-items: center; justify-content: space-between; 
            padding: 0 2rem; 
            position: sticky; top: 0; z-index: 900; flex-shrink: 0; 
        }}
        .page-title {{ font-weight: 900; font-size: 1.1rem; color: var(--primary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width: 35%; }}
        
        .nav-btns {{ display: flex; gap: 0.75rem; align-items: center; }}
        .nav-btn {{ text-decoration: none; padding: 0.5rem 1rem; border-radius: 6px; font-weight: 700; font-size: 0.85rem; color: var(--text); background: var(--gray-200); transition: 0.2s; white-space: nowrap; border: none; cursor: pointer; display: inline-flex; align-items: center; gap: 0.4rem; }}
        .nav-btn:hover {{ background: var(--gray-300); }}
        .nav-btn:focus {{ outline: none; box-shadow: 0 0 0 2px rgba(31,162,224,0.2); }}
        .nav-btn.primary {{ background: var(--primary); color: #fff; }}
        .nav-btn.primary:hover {{ opacity: 0.9; }}
        .nav-btn.danger {{ background: #ef4444; color: #fff; }}

        /* Remove tap highlight on mobile */
        button, a, input {{
            -webkit-tap-highlight-color: transparent;
        }}
        
        /* Topbar right grouping - search + nav buttons */
        .topbar-right {{ display: flex; align-items: center; gap: 0.75rem; margin-left: auto; }}
        
        /* --- SMART PAGEFIND SEARCH UI (Antigravity v5) --- */
        
        /* 1. Top Bar Search (Expandable Pill) */
        .search-container.expandable {{ 
            display: flex; align-items: center; justify-content: flex-end;
            position: relative; margin-left: 1rem; 
            background: transparent;
            border-radius: 20px;
            transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
            border: 1px solid transparent;
            overflow: visible;
        }}
        
        /* The Trigger Icon */
        .search-trigger {{
            width: 36px; height: 36px;
            display: flex; align-items: center; justify-content: center;
            cursor: pointer; color: var(--text);
            font-size: 1rem;
            border-radius: 50%;
            transition: background 0.2s;
            z-index: 2;
        }}
        .search-trigger:hover {{ background: var(--gray-200); }}
        
        /* The Input Wrapper (Hidden by default) */
        .search-container.expandable .search-input-wrapper {{ 
            width: 0; opacity: 0; padding: 0; overflow: hidden;
            background: transparent; border: none;
            transition: all 0.3s ease; visibility: hidden;
        }}
        
        /* EXPANDED STATE (expands LEFT from the trigger icon) */
        .search-container.expandable.open {{ 
            background: #fff; border-color: var(--gray-300);
            padding-left: 0.5rem; 
            box-shadow: 0 4px 12px rgba(0,0,0,0.08);
        }}
        .search-container.expandable.open .search-input-wrapper {{ 
            width: 200px; opacity: 1; visibility: visible; padding-right: 0.5rem;
        }}
        
        .search-input {{ 
            border: none; background: transparent; 
            font-size: 0.9rem; width: 100%; 
            outline: none; color: var(--text); 
        }}
        
        /* OFFLINE STATE */
        .search-container.expandable.offline .search-trigger {{
            opacity: 0.5; cursor: not-allowed; color: var(--gray-400);
        }}

        /* 2. Homepage Hero Search */
        .hero-search-wrapper {{ 
            max-width: 600px; margin: 1.5rem auto 2rem auto; position: relative; 
        }}
        .hero-search-wrapper .search-input-wrapper {{
            background: #fff; border: 1px solid var(--gray-300);
            padding: 0.8rem 1.2rem; box-shadow: 0 4px 12px rgba(0,0,0,0.04);
            border-radius: 12px; display: flex; align-items: center;
        }}
        .hero-search-wrapper .search-input-wrapper:focus-within {{
            border-color: var(--primary); transform: translateY(-2px);
            box-shadow: 0 8px 20px rgba(31,162,224,0.15);
        }}
        .hero-search-wrapper .search-input {{ width: 100%; font-size: 1.05rem; margin-left: 0.5rem; }}

        /* Results Dropdown */
        .search-results {{ 
            position: absolute; top: calc(100% + 12px); right: 0; width: 400px; 
            max-height: 60vh; overflow-y: auto; 
            background: #fff; border: 1px solid var(--gray-200); 
            border-radius: 12px; box-shadow: 0 15px 40px rgba(0,0,0,0.12); 
            z-index: 2000; display: none; 
        }}
        .search-results.active {{ display: block; }}
        .hero-search-wrapper .search-results {{ width: 100%; left: 0; }}
        
        .search-result-item {{ display: block; padding: 0.85rem 1.25rem; text-decoration: none; color: inherit; border-left: 3px solid transparent; transition: background 0.1s; }}
        .search-result-item:hover {{ background: var(--gray-50); border-left-color: var(--primary); }}
        .search-result-title {{ font-weight: 700; color: var(--primary); font-size: 0.9rem; margin-bottom: 0.2rem; }}
        .search-result-excerpt {{ font-size: 0.85rem; color: #555; line-height: 1.4; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }}
        .search-result-excerpt mark {{ background: rgba(255, 236, 61, 0.4); padding: 0 2px; border-radius: 2px; }}

        @media (max-width: 768px) {{ 
            .search-container {{ display: flex !important; }} 
            .hero-search-wrapper {{ max-width: 90%; }} 
        }}

        /* Dropdown */
        .dropdown {{ position: relative; display: inline-block; }}
        .dropdown-content {{ display: none; position: absolute; right: 0; top: 100%; background-color: #fff; min-width: 200px; box-shadow: 0 8px 16px rgba(0,0,0,0.1); border-radius: 8px; z-index: 2000; border: 1px solid var(--gray-200); overflow: hidden; }}
        .dropdown:hover .dropdown-content {{ display: block; }}
        .dropdown-content a {{ color: var(--text); padding: 12px 16px; text-decoration: none; display: block; font-size: 0.9rem; }}
        .dropdown-content a:hover {{ background-color: var(--gray-100); color: var(--primary); }}

        /* Images - P2: Improved spacing around figures */
        #doc_content img {{ 
            display: block; margin: 2.5rem auto; 
            width: auto; max-width: 85%; height: auto; 
            border-radius: 8px; box-shadow: 0 8px 25px rgba(0,0,0,0.1); 
            cursor: zoom-in; object-fit: contain; 
        }}
        #doc_content .figure, #doc_content figure {{ margin: 2.5rem 0; }}
        #doc_content figcaption, #doc_content .caption {{ margin-top: 1rem; margin-bottom: 2rem; }}

        /* Hide TeX4ht vrule/rule artifacts that create unwanted vertical lines */
        .vrule, [class*="vrule"], hr.vrule, span.vrule,
        .rule, [class*="pict"][class*="rule"], span[style*="width:0."],
        [style*="border-left"][style*="solid"][style*="1px"],
        [style*="border-right"][style*="solid"][style*="1px"] {{
            display: none !important;
            visibility: hidden !important;
            width: 0 !important;
            height: 0 !important;
            border: none !important;
            background: transparent !important;
        }}
        /* Fix any inline vertical bar characters that might render as lines */
        .pict, .picture {{ overflow: hidden !important; }}
        
        /* P1: Enrichment dividers - clean separators */
        .enrichment-divider {{ border: none; height: 1px; background: linear-gradient(to right, transparent, var(--gray-300) 20%, var(--gray-300) 80%, transparent); margin: 2.5rem 0; }}
        
        /* P3: Paragraph titles + subsubsection heads - more prominent hierarchy */
        /* Subsubsection (H4 equivalent) */
        .subsubsectionHead, h4 {{ font-size: 1.25rem; font-weight: 700; color: var(--text); margin-top: 1.75rem; margin-bottom: 0.75rem; }}
        
        /* Paragraph (H5 equivalent) */
        .paragraphHead, .likeparagraphHead, h5 {{ display: block; font-size: 1.1rem; font-weight: 700; color: var(--text); margin: 1.5rem 0 0.5rem 0; }}
        .paragraphHead .cmbx-10x-x-109, .likeparagraphHead .cmbx-10x-x-109 {{ font-weight: 700; }}
        
        /* Override specific tag-class combos if needed */
        h5.subsubsectionHead {{ font-size: 1.25rem; border: none !important; padding: 0; background: none; }}
        
        /* Enrichment titles - ocre color from structure.tex, hierarchy matches section/subsection/subsubsection */
        /* Enrichment titles - ocre color - strict override */
        h3.enrichment-title, [id*="enrichment"] h3, h3[id*="enrichment"], .likesubsectionHead[id*="enrichment"] {{ font-size: 1.3rem; font-weight: 700; color: var(--ocre) !important; margin: 2rem 0 1rem 0; padding: 0; border: none; background: none; }}
        h4.enrichment-title, [id*="enrichment"] h4, h4[id*="enrichment"], .likesubsubsectionHead[id*="enrichment"] {{ font-size: 1.15rem; font-weight: 700; color: var(--ocre) !important; margin: 1.75rem 0 0.75rem 0; padding: 0; border: none; background: none; }}
        h5.enrichment-title, [id*="enrichment"] h5, h5[id*="enrichment"], .likeparagraphHead[id*="enrichment"] {{ font-size: 1rem; font-weight: 600; color: var(--ocre) !important; margin: 1.5rem 0 0.5rem 0; padding: 0; border: none; background: none; }}
        /* Emoji appended AFTER numbering, only if not already present */
        h3.enrichment-title:not([data-emoji])::after, h4.enrichment-title:not([data-emoji])::after, h5.enrichment-title:not([data-emoji])::after {{ content: ' 📘'; }}
        
        /* Code Blocks - VS Code-like styling (vs2015 theme) */
        .code-wrapper {{
            position: relative;
            margin: 1.5rem 0;
            border-radius: 6px;
            overflow: hidden;
        }}
        .copy-btn {{ 
            position: absolute; top: 8px; right: 8px; 
            background: rgba(255,255,255,0.08); border: 1px solid rgba(255,255,255,0.15); 
            color: #9cdcfe; padding: 5px 10px; border-radius: 4px; 
            font-size: 0.75rem; cursor: pointer; transition: all 0.2s ease; z-index: 10;
            font-weight: 500;
        }}
        .copy-btn:hover {{ background: rgba(255,255,255,0.15); color: #fff; border-color: rgba(255,255,255,0.3); }}
        /* VS Code dark theme colors */
        pre {{ 
            background: #1e1e1e; 
            border-radius: 6px; 
            padding: 1rem 1.25rem; 
            overflow-x: auto; 
            color: #d4d4d4; 
            font-family: 'Consolas', 'Monaco', 'Roboto Mono', monospace; 
            font-size: 0.875rem; 
            line-height: 1.6;
            margin: 0; 
            border: 1px solid #333;
            tab-size: 4;
        }}
        pre code {{
            font-family: inherit;
            font-size: inherit;
            background: transparent !important;
            padding: 0 !important;
            color: inherit;
            white-space: pre !important;
            display: block !important;
            text-align: left !important;
        }}
        /* Inline code (not in pre) */
        :not(pre) > code {{ 
            font-family: 'Consolas', 'Monaco', 'Roboto Mono', monospace; 
            background: #f0f0f0;
            color: #c7254e;
            padding: 0.15rem 0.4rem;
            border-radius: 3px;
            font-size: 0.9em;
        }}
        /* Ensure hljs doesn't add extra background */
        pre code.hljs {{ background: transparent !important; padding: 0 !important; }}

        /* Lists - Issue 7 + P4: Fix enumerate/itemize with CSS Grid (NOT for description lists) */
        dl.enumerate, dl.itemize, dl.enumerate-enumitem, dl.compactdesc {{
            display: grid; grid-template-columns: max-content 1fr; column-gap: 0.75rem; row-gap: 0.25rem; margin: 0.75rem 0; padding: 0;
            overflow: visible; scrollbar-width: none; -ms-overflow-style: none;
        }}
        dl.enumerate::-webkit-scrollbar, dl.itemize::-webkit-scrollbar,
        dl.enumerate-enumitem::-webkit-scrollbar, dl.compactdesc::-webkit-scrollbar {{
            display: none; width: 0; height: 0;
        }}
        dl.enumerate > dt, dl.itemize > dt, dl.enumerate-enumitem > dt, dl.compactdesc > dt {{
            grid-column: 1; font-weight: 600; min-width: 1.5em; text-align: right; margin: 0; padding: 0;
            overflow: visible; scrollbar-width: none; -ms-overflow-style: none;
        }}
        dl.enumerate > dd, dl.itemize > dd, dl.enumerate-enumitem > dd, dl.compactdesc > dd {{
            grid-column: 2; margin: 0; padding: 0;
            overflow: visible; scrollbar-width: none; -ms-overflow-style: none;
        }}
        dl.enumerate > dt::-webkit-scrollbar, dl.itemize > dt::-webkit-scrollbar,
        dl.enumerate-enumitem > dt::-webkit-scrollbar, dl.compactdesc > dt::-webkit-scrollbar,
        dl.enumerate > dd::-webkit-scrollbar, dl.itemize > dd::-webkit-scrollbar,
        dl.enumerate-enumitem > dd::-webkit-scrollbar, dl.compactdesc > dd::-webkit-scrollbar {{
            display: none; width: 0; height: 0;
        }}
        /* Description lists - block layout for proper term display */
        dl.description {{ margin: 0.5rem 0; padding: 0; }}
        dl.description > dt {{ font-weight: 700; margin: 0.75rem 0 0.25rem 0; padding: 0; }}
        dl.description > dd {{ margin: 0 0 0.5rem 1.5rem; padding: 0; }}
        dl.description dd p {{ margin: 0.25rem 0; }}
        dl.description dd p:first-child {{ margin-top: 0; }}
        dl.description dd p:last-child {{ margin-bottom: 0; }}
        .itemlabel, .itemcontent {{ display: inline; }}
        /* Nested lists */
        dl dl {{ margin: 0.5rem 0; }}

        /* UL-based itemize lists (tex4ht output) - clear bullet styling */
        ul.itemize1, ul.itemize2, ul.itemize3, ul.itemize4 {{
            list-style-type: disc !important;
            list-style-position: outside !important;
            padding-left: 2rem !important;
            margin: 0.75rem 0 !important;
        }}
        ul.itemize2 {{ list-style-type: circle !important; }}
        ul.itemize3 {{ list-style-type: square !important; }}
        ul.itemize4 {{ list-style-type: disc !important; }}
        li.itemize {{
            display: list-item !important;
            margin-bottom: 0.5rem;
            padding-left: 0.25rem;
        }}
        li.itemize::marker {{
            color: var(--primary);
            font-weight: bold;
            font-size: 1.2em;
        }}

        /* Citations */
        .cite-ref {{ color: var(--primary); font-weight: bold; text-decoration: none; cursor: pointer; padding: 0 2px; }}
        .cite-ref:hover {{ text-decoration: underline; }}
        
        /* Bibliography - Issue 8: scroll-margin for anchor navigation */
        .bib-entry {{ display: flex; gap: 1.5rem; padding: 2rem; background: var(--bg); border: 1px solid var(--gray-200); border-radius: 12px; margin-bottom: 1.5rem; scroll-margin-top: 100px; transition: all 0.3s ease; }}
        .bib-entry:hover {{ transform: translateY(-5px); border-color: var(--primary); box-shadow: 0 15px 30px rgba(31,162,224,0.15); }}
        .bib-label {{ font-family: 'Roboto Mono', monospace; font-weight: 900; color: var(--primary); font-size: 1.1rem; min-width: 3rem; text-align: right; }}
        .bib-content {{ flex: 1; }}
        .bib-author {{ font-weight: 700; font-size: 1.1rem; display: block; color: var(--text); margin-bottom: 0.25rem; }}
        .bib-title {{ font-weight: 400; font-size: 1.1rem; display: block; font-style: italic; color: var(--text); margin-bottom: 0.5rem; }}
        .bib-meta {{ display: flex; gap: 1rem; font-size: 0.95rem; color: #666; margin-bottom: 0.75rem; }}
        .bib-ref-link {{ display: inline-block; font-size: 0.85rem; color: var(--primary); text-decoration: none; font-weight: 700; border: 1px solid var(--primary); padding: 2px 10px; border-radius: 4px; transition: 0.2s; }}
        .bib-ref-link:hover {{ background: var(--primary); color: #fff; }}
        
        
        /* Headings - scroll-margin-top for hash navigation with fixed header (E fix) */
        h1, h2, h3, h4, h5, h6,
        .sectionHead, .subsectionHead, .subsubsectionHead, 
        .paragraphHead, .likeparagraphHead, .enrichment-title,
        [id^="x1-"], [id^="section-"], [id^="subsection-"], [id^="chapter-"], [id^="enrichment-"] {{ 
            scroll-margin-top: 120px; 
        }}

        
        /* Hierarchy: Section (H2) > Subsection (H3) > Subsubsection (H4) */
        /* Hierarchy: Strict Size & Color Control */
        h1, .chapterHead {{ font-size: 3.5rem; font-weight: 900; color: var(--ocre) !important; border-bottom: 4px solid var(--ocre); padding-bottom: 1rem; margin-top: 0; }}
        
        /* Section (H2) */
        .sectionHead, h2, .likesectionHead {{ font-size: 2.0rem; font-weight: 800; color: #000 !important; margin-top: 2.5rem; }}
        
        /* Subsection (H3) */
        .subsectionHead, h3, .likesubsectionHead {{ font-size: 1.6rem; font-weight: 700; color: #000 !important; margin-top: 2.0rem; }}
        
        /* Subsubsection (H4) - use var(--text) for dark mode compatibility */
        .subsubsectionHead, h4, .likesubsubsectionHead {{ font-size: 1.3rem; font-weight: 700; color: var(--text); margin-top: 1.5rem; }}

        /* Paragraph (H5) - Reduced size, use var(--text) for dark mode */
        .paragraphHead, .likeparagraphHead, h5 {{ font-size: 1.1rem; font-weight: 700; color: var(--text); margin-top: 1.25rem; display: block; }}

        /* Subparagraph (H6) - use var(--text) for dark mode */
        .subparagraphHead, h6 {{ font-size: 1.0rem; font-weight: 600; color: var(--text); margin-top: 1.0rem; }}
        
        /* Enrichment Overrides (MUST be Ocre) */
        /* Target the HEADER directly if it has the ID, OR if it's inside a div with the ID */
        h3.enrichment-title, h4.enrichment-title, h5.enrichment-title,
        h3[id^="ocreenrichment"], h4[id^="ocreenrichment"], h5[id^="ocreenrichment"],
        [id^="ocreenrichment"] h3, [id^="ocreenrichment"] h4, [id^="ocreenrichment"] h5 {{
            color: var(--ocre) !important; 
        }}
        
        /* Home Page Info Boxes - Specific Override */
        /* Styles moved to main table block for consolidated cleanup */
        
        /* Specific IDs for Homepage Boxes if needed, or rely on inline styles which we'll update in main() */
        
        /* Empty whitespace cleanup - hide truly empty elements */
        p:empty, p:has(> br:only-child), div.minipage:empty,
        p.noindent:empty {{ display: none !important; margin: 0 !important; padding: 0 !important; }}
        /* Fix spacing before minipages - sometimes there's an empty p before them */
        .minipage {{ margin-top: 0.5rem; }}
        
        /* Issue 9: Figure captions - gray italic with bold label */
        .caption, p.caption, .fig-caption, figcaption {{ 
            font-style: italic; 
            color: #666; 
            text-align: center; 
            margin: 1rem auto; 
            font-size: 0.95rem; 
        }}
        .fig-label {{ font-weight: 700; font-style: normal; }}
        
        /* Lightbox */
        .lightbox {{ display: none; position: fixed; top: 0; left: 0; width: 100%; height: 100%; background: rgba(0,0,0,0.9); z-index: 3000; justify-content: center; align-items: center; }}
        .lightbox.active {{ display: flex; }}
        .lightbox img {{ max-width: 95%; max-height: 95vh; box-shadow: none; border-radius: 0; cursor: zoom-out; width: auto; height: auto; }}

        /* Float Nav */
        .float-nav {{ position: fixed; bottom: 2rem; right: 2rem; display: flex; flex-direction: column; gap: 0.75rem; z-index: 2000; }}
        .float-btn {{ width: 46px; height: 46px; border-radius: 50%; background: var(--primary); color: white; display: flex; align-items: center; justify-content: center; text-decoration: none; font-weight: 700; box-shadow: 0 8px 25px rgba(31,162,224,0.4); cursor: pointer; opacity: 0.5; transition: opacity 0.2s, transform 0.2s; }}
        .float-btn:hover {{ transform: translateY(-2px); opacity: 1; }}

        /* C fix: Dependency graph - full width page layout */
        body.page-depgraph {{ width: 100% !important; }}
        body.page-depgraph .main-wrapper {{ width: 100% !important; flex: 1 !important; }}
        body.page-depgraph #content_area {{ max-width: none !important; width: 100% !important; padding: 1rem !important; }}
        body.page-depgraph .container {{ max-width: 100% !important; width: 100% !important; padding: 0 !important; box-sizing: border-box; }}
        body.page-depgraph .card {{ max-width: none !important; width: 100% !important; padding: 1.5rem !important; box-sizing: border-box; margin: 0 auto; }}
        body.page-depgraph #doc_content {{ 
            width: 100% !important; 
            max-width: none !important; 
            text-align: center;
            box-sizing: border-box;
        }}
        body.page-depgraph #doc_content h1 {{ text-align: left; width: 100%; margin-bottom: 1rem; }}
        /* Robust: match ANY img in depgraph doc_content, not relying on .depgraph-img class */
        body.page-depgraph #doc_content img {{ 
            width: 100% !important; 
            max-width: 100% !important;  /* Override the 85% figure constraint */
            height: auto !important; 
            display: block; 
            margin: 2rem auto !important;
            object-fit: contain;
            box-shadow: none !important;  /* No shadow for full-width graph */
            border-radius: 0 !important;
        }}
        body.page-depgraph .content-scroll {{ overflow-x: hidden; }} /* Safety net only */
        
        /* A5: Make chapter figures smaller by default (0.7x) - only in content, not icons */
        #doc_content .figure img, #doc_content figure img {{ max-width: 70% !important; display: block; margin: 1.5rem auto; }}
        
        /* Fix unwanted spacing - collapse empty paragraphs and reduce description list gaps */
        #doc_content p:empty {{ display: none; margin: 0; padding: 0; }}
        #doc_content p br:only-child {{ display: none; }}
        #doc_content dl.enumerate-enumitem {{ margin: 0.5rem 0; }}
        #doc_content dd.enumerate-enumitem {{ margin-bottom: 0.3rem; }}
        /* Cross-reference styling */
        .cross-ref {{ color: var(--primary); text-decoration: none; font-weight: 500; }}
        .cross-ref:hover {{ text-decoration: underline; }}
        .broken-ref {{ color: #888; font-size: 0.9em; font-style: italic; background: transparent; }}
        
        /* D fix: Booktabs-style tables - academic look matching book */
        /* Wrapper corresponds to div.tabular in TeX4ht */
        div.tabular, .table-wrapper {{ 
            display: block; width: 100%; overflow-x: auto; 
            margin: 2rem 0; padding: 0.5rem 0; 
            text-align: center; /* Centers the auto-width table */
        }}
        /* The table itself - auto width and centering */
        table.book-table, table.tabular {{
            width: auto !important; margin: 0 auto !important;
            border-collapse: collapse !important; border-spacing: 0 !important;
            font-size: 0.9rem !important; line-height: 1.5; background-color: #fff;
            border-top: 2.5px solid #000 !important; border-bottom: 2.5px solid #000 !important;
            border-left: none !important; border-right: none !important;
        }}
        /* Hide hline rows (empty horizontal rule rows from LaTeX booktabs) */
        table.book-table tr.hline, table.tabular tr.hline {{
            display: none !important;
        }}
        /* Header rows - first level (spans) */
        table.book-table thead th, table.tabular thead th {{
            font-weight: 700; font-size: 0.9rem; text-transform: none;
            color: #000; padding: 0.5rem 1rem !important; text-align: center; vertical-align: bottom;
        }}
        /* Handle tables without explicit thead - first row cells */
        table.book-table:not(:has(thead)) tr:first-child td, table.tabular:not(:has(thead)) tr:first-child td {{
            font-weight: 700; font-size: 0.9rem; text-transform: none;
            color: #000; padding: 0.5rem 1rem !important; text-align: center; vertical-align: bottom; 
            background-color: transparent; 
            border: none !important;
            border-bottom: 1px solid #000 !important;
            white-space: normal !important; 
            word-wrap: break-word !important; 
        }}
        /* Last header row gets the final thick rule */
        table.book-table thead tr:last-child th, table.tabular thead tr:last-child th {{ border-bottom: 1.5px solid #000 !important; }}
        /* Multi-row headers: lighter separator for grouped headers (not the final row) */
        table.book-table thead tr:not(:last-child) th, table.tabular thead tr:not(:last-child) th {{ border-bottom: 1px solid #666; }}
        /* Column group separators for multi-column headers */
        table.book-table thead th[colspan], table.tabular thead th[colspan] {{ padding: 6px 16px !important; }}
        table.book-table thead th[colspan]:not(:first-child), table.tabular thead th[colspan]:not(:first-child) {{ border-left: 1px solid #000; }}
        table.book-table .group-start {{ border-left: 1px solid #000; }}
        /* Data rows */
        table.book-table tbody td, table.tabular tbody td, table.book-table td, table.tabular td {{ 
            padding: 6px 16px !important; border-bottom: none !important; 
            vertical-align: middle; color: #222; text-align: center; 
            white-space: nowrap;
        }}
        table.book-table tbody td:first-child, table.tabular tbody td:first-child {{ text-align: left; white-space: normal; }}
        /* Category rows - cells that span all columns */
        table.book-table tbody td[colspan], table.tabular tbody td[colspan] {{ 
            font-style: italic; text-align: center; padding: 8px 16px !important;
            border-top: 1px solid #666 !important; border-bottom: none !important;
        }}
        /* Bold spans in cells */
        table.book-table .cmbx-8, table.book-table .cmbx-10, table.book-table .cmbx-10x-x-109 {{ font-weight: 700; }}
        /* Fallback for tables without thead */
        table.book-table:not(:has(thead)) tbody tr:first-child td, table.tabular:not(:has(thead)) tbody tr:first-child td {{
            font-weight: 700; border-bottom: 1.5px solid #000 !important;
        }}
        /* Style rows with all-bold cells as headers (for tables with hline rows that weren't removed) */
        table.book-table tr:has(> td:first-child > .cmbx-8):has(> td:last-child > .cmbx-8) td,
        table.tabular tr:has(> td:first-child > .cmbx-8):has(> td:last-child > .cmbx-8) td {{
            font-weight: 700 !important;
            border-bottom: 1.5px solid #000 !important;
        }}
        /* Special row classes */
        table.book-table tbody tr.bold-row td {{ font-weight: 700; }}
        table.book-table tbody tr.separator-above td {{ border-top: 1px solid #000 !important; }}
        /* Caption styling - above table, left-aligned */
        .table-caption {{ 
            text-align: left; font-weight: 700; color: #000; 
            margin-bottom: 10px; font-size: 0.95rem; 
            display: block; width: 100%;
        }}
        .table-caption span.note {{ font-weight: 400; color: #444; margin-left: 0.5em; }}
        
        /* Homepage Info Box Color Overrides (Fix for Issue 2) */
        /* Compact Homepage Info Boxes */
        .info-box {{ padding: 0.5rem 0.75rem !important; margin-bottom: 0.5rem !important; }}
        /* Override global !important margin-top for H4 */
        .info-box h4 {{ margin-bottom: 0.25rem !important; margin-top: 0 !important; font-size: 1rem !important; }}
        .info-box p {{ margin-bottom: 0.25rem !important; line-height: 1.3 !important; }}

        /* Force Green for Open Source */
        .info-box h4:has(.fa-code-branch) {{ color: #7FD1B9 !important; }}
        /* Force Brown for Disclaimer */
        .info-box h4:has(.fa-circle-info) {{ color: #7A6563 !important; }}
        /* Fix Heading Sizes */
        /* Fix Heading Sizes - Black for standard sections */
        .subsubsectionHead, h4 {{
            font-size: 1.25rem !important;
            margin-top: 1.75rem !important;
            margin-bottom: 0.75rem !important;
            color: #000 !important;
            font-weight: 700 !important;
        }}
        
        .paragraphHead, .likeparagraphHead, h5 {{
            font-size: 1.15rem !important;
            margin: 1.5rem 0 0.5rem 0 !important;
            color: #000 !important;
            display: block !important;
            font-weight: 600 !important;
        }}
        
        /* Multi-row headers: first header row(s) get lighter separator */
        table.book-table thead tr:not(:last-child) th {{ 
            border-bottom: 1px solid #555 !important; 
        }}
        
        /* Spanning header cells (like "Phase 1 Mask Alignment") */
        table.book-table thead th[colspan] {{ 
            padding: 6px 18px; 
            border-left: 1.5px solid #000 !important;  /* Visual separator for column groups */
        }}
        table.book-table thead th[colspan]:first-child {{ border-left: none !important; }}
        
        /* Group start marker for cells under a colspan */
        table.book-table .group-start, 
        table.book-table thead tr:last-child th.group-start {{
            border-left: 1.5px solid #000 !important;
        }}
        
        /* Data cells */
        table.book-table tbody td {{ 
            padding: 5px 18px; 
            vertical-align: middle; color: #222; text-align: center; 
            white-space: nowrap; /* Keep compact for numbers */
            border: none !important;
        }}
        
        /* First column usually text - allow wrap */
        table.book-table tbody td:first-child {{ 
            text-align: left; 
            white-space: normal; 
            font-weight: 500;
        }}
        
        /* Group separator in data rows (column below a colspan) */
        /* Simple border-left for vertical column separator - NOT stripped by rules above */
        table.book-table tbody td.group-start,
        table.book-table thead th.group-start,
        table.book-table .group-start,
        .group-start {{
            border-left: 1.5px solid #000 !important;
            padding-left: 16px;
        }}
        
        /* Category rows - full-width italic rows like "mip-NeRF 360 (unbounded)" */
        table.book-table tbody td[colspan] {{ 
            font-style: italic; text-align: center; padding: 8px 18px;
            border-top: 1px solid #888 !important; 
            white-space: normal;
        }}
        
        /* Bold text in cells */
        table.book-table .cmbx-8, table.book-table .cmbx-10, table.book-table .cmbx-10x-x-109 {{ font-weight: 700; }}
        

        
        /* Italic fonts from LaTeX - Computer Modern Italic */
        .cmti-8, .cmti-10, .cmti-12, .cmti-10x-x-109,
        span[class*="cmti-"] {{
            font-style: italic !important;
        }}
        
        /* Nested tables in cells (TeX4ht multirow conversion) - flatten display */
        table td > .tabular, table td > div.tabular {{ display: contents !important; }}
        table td .tabular table, table td div.tabular table, td .table-wrapper table {{
            display: inline !important; border: none !important; border-top: none !important; border-bottom: none !important;
            margin: 0 !important; padding: 0 !important; font-size: inherit !important; background: transparent !important;
        }}
        table td .tabular td, table td div.tabular td, td .table-wrapper td {{
            display: block !important; border: none !important; padding: 1px 2px !important; white-space: nowrap; text-align: center; font-size: 0.75rem !important;
        }}
        td > div.tabular > div.table-wrapper {{ display: contents !important; }}
        
        /* Stacked cells (flattened multirow) - proper vertical alignment */
        .stacked-cell {{
            vertical-align: middle !important;
            text-align: center !important;
            line-height: 1.4 !important;
            padding: 4px 8px !important;
        }}
        .stacked-cell br {{ display: block; margin: 2px 0; }}
        
        /* Inferred/synthesized header rows (for tables like Swin Variants) */
        tr.inferred-header {{ background: var(--table-header-bg) !important; }}
        tr.inferred-header th.inferred-th {{
            font-weight: 700 !important;
            text-align: center !important;
            padding: 8px 10px !important;
            border-bottom: 2px solid #000 !important;
            white-space: nowrap !important;
            color: var(--text) !important;
        }}
        
        /* ============ GROUP SEPARATOR (vertical line for grouped columns) ============ */
        /* This creates the single vertical line between "Clicks/clicked frame" and "All" */
        table.book-table .group-start {{
            border-left: 1.5px solid #000 !important;
            padding-left: 14px !important;
        }}
        
        /* Grouped headers with colspan also get the left border */
        table.book-table thead th.group-start {{
            border-left: 1.5px solid #000 !important;
        }}
        
        /* ============ BOLD NUMBERS (best results in row) ============ */
        table.book-table .cmbx-8, 
        table.book-table .cmbx-10, 
        table.book-table .cmbx-10x-x-109,
        table.book-table b,
        table.book-table strong {{
            font-weight: 700;
        }}
        
        /* ============ TABLES WITHOUT THEAD ============ */
        /* Fallback: treat first row as header */
        table.book-table:not(:has(thead)) tbody tr:first-child td {{ 
            font-weight: 700; 
        }}
        table.book-table:not(:has(thead)) tbody tr:first-child {{
            border-bottom: 1.5px solid #000;
        }}
        
        /* ============ CAPTION STYLING ============ */
        .table-caption {{ 
            text-align: left; font-weight: 700; color: #000; 
            margin-bottom: 0px; font-size: 0.95rem; 
            display: block; width: 100%;
        }}
        .table-caption span.note {{ font-weight: 400; color: #444; margin-left: 0.5em; }}
        
        
        /* ===========================================
           MOBILE RESPONSIVE DESIGN
           =========================================== */
        
        /* Tablets and smaller */
        @media (max-width: 1024px) {{
            /* Hide resize handle on tablet/mobile - prevent blue line artifact */
            .resize-handle {{ display: none !important; }}

            /* Sidebar: Hidden by default, overlays content when open */
            html body .sidebar, html body .sidebar.collapsed {{
                position: fixed !important;  /* Fixed instead of absolute */
                left: 0;
                top: 0;
                transform: translateX(-100%) !important;
                width: 280px !important;
                height: 100vh;
                box-shadow: 10px 0 40px rgba(0,0,0,0.3);
                transition: transform 0.3s ease;
                z-index: 2000;  /* Above everything */
            }}
            html body .sidebar.open, html body .sidebar.collapsed.open {{ transform: translateX(0) !important; }}
            
            /* Main content: Full width on mobile (no sidebar margin) */
            .main-wrapper {{ 
                margin-left: 0 !important; 
                width: 100% !important;
                transform: none !important; /* Ensure no shift */
            }}
            .sidebar.collapsed ~ .main-wrapper {{
                margin-left: 0 !important;
                width: 100% !important;
            }}
            
            /* Show hamburger menu toggle */
            #menu_toggle {{ display: block !important; }}
            
            /* Overlay backdrop when sidebar is open */
            .sidebar-overlay {{
                display: none;
                position: fixed;
                top: 0;
                left: 0;
                width: 100vw;
                height: 100vh;
                background: rgba(0,0,0,0.5);
                z-index: 1999;
            }}
            .sidebar.open ~ .sidebar-overlay {{ display: block; }}
        }}
        
        /* Phones */
        @media (max-width: 768px) {{
            /* Use CSS variables so dark mode/high contrast can override */
            html body p, html body li, html body .card {{ color: var(--text) !important; }}
            html body h1, html body h2, html body h3, html body h4, html body h5, html body h6 {{ color: var(--primary) !important; }}
            #menu_toggle svg {{ color: var(--primary) !important; }}
            .top-bar {{
                background: var(--bg) !important;
                color: var(--text) !important;
                border-bottom: 2px solid var(--gray-200) !important;
                position: sticky !important;
                top: 0 !important;
                z-index: 2100 !important;
                display: flex !important;
                visibility: visible !important;
                opacity: 1 !important;
            }}
            .page-title {{ color: var(--primary) !important; font-weight: 800 !important; }}
            .sidebar {{ background: var(--bg) !important; }}

            /* Code blocks - mobile spacing and formatting */
            .code-wrapper, #doc_content .code-wrapper, .card .code-wrapper {{
                margin: 1.5rem 0.5rem !important; /* Visible gap from edges */
                margin-left: 0.5rem !important;
                margin-right: 0.5rem !important;
                border-radius: 4px !important;
                overflow-x: auto !important;
                -webkit-overflow-scrolling: touch;
                box-sizing: border-box !important;
                max-width: calc(100% - 1rem) !important;
            }}
            .code-wrapper pre, #doc_content .code-wrapper pre {{
                padding: 1rem 0.75rem !important; /* Clear internal padding */
                border-radius: 4px !important;
                overflow-x: auto !important;
                text-align: left !important;
                white-space: pre !important;
                margin: 0 !important;
            }}
            .code-wrapper pre code,
            .code-wrapper code,
            #doc_content pre code,
            pre code {{
                text-align: left !important;
                white-space: pre !important;
                display: block !important;
                word-wrap: normal !important;
                word-break: normal !important;
                overflow-wrap: normal !important;
            }}
            
            /* Mobile Overflow Fix - comprehensive (excludes display math, handled separately) */
            p, li, .search-result-excerpt,
            pre, code, .code-block {{
                overflow-wrap: break-word;
                word-wrap: break-word;
                hyphens: auto;
                max-width: 100%;
                overflow-x: auto !important;
                /* Hide scrollbars while keeping horizontal scroll */
                scrollbar-width: none !important; /* Firefox */
                -ms-overflow-style: none !important; /* IE/Edge */
            }}
            /* Hide scrollbars for p, li, pre, code on WebKit/Blink */
            p::-webkit-scrollbar, li::-webkit-scrollbar, 
            pre::-webkit-scrollbar, code::-webkit-scrollbar,
            .code-block::-webkit-scrollbar, .search-result-excerpt::-webkit-scrollbar,
            li.itemize::-webkit-scrollbar, .itemize::-webkit-scrollbar {{
                display: none !important;
                width: 0 !important;
                height: 0 !important;
            }}

            /* Lists - ensure they don't overflow */
            ul, ol {{ max-width: 100%; overflow-x: hidden; padding-right: 0.5rem; }}
            li {{ max-width: 100%; overflow-wrap: break-word; word-break: break-word; }}

            /* UL itemize lists on mobile - explicit bullet styling */
            ul.itemize1, ul.itemize2, ul.itemize3, ul.itemize4 {{
                list-style-type: disc !important;
                list-style-position: outside !important;
                padding-left: 2rem !important;
                margin: 0.5rem 0 !important;
            }}
            ul.itemize2 {{ list-style-type: circle !important; padding-left: 2.5rem !important; }}
            ul.itemize3 {{ list-style-type: square !important; padding-left: 3rem !important; }}
            li.itemize {{
                display: list-item !important;
                margin-bottom: 0.4rem !important;
                padding-left: 0.25rem !important;
            }}
            li.itemize::marker {{
                color: var(--primary) !important;
                font-size: 1.2em !important;
            }}
            /* Ensure nested lists inside li also show bullets */
            li.itemize ul {{
                list-style-type: circle !important;
                list-style-position: outside !important;
                padding-left: 1.5rem !important;
                margin-top: 0.25rem !important;
            }}

            /* ================================================================= */
            /* MOBILE LIST FIX - Ensure bullets/numbers show properly          */
            /* TeX4ht generates dl.enumerate-enumitem with dt + dd pairs       */
            /* dt contains "1.", "2.", etc. - they are NOT empty!              */
            /* Keep using grid on mobile but ensure dt column is visible.      */
            /* ================================================================= */
            dl.enumerate, dl.itemize, dl.enumerate-enumitem, dl.compactdesc {{
                display: grid !important;
                grid-template-columns: auto 1fr !important;
                column-gap: 0.5rem !important;
                row-gap: 0.5rem !important;
                max-width: 100% !important;
                overflow: visible !important;
                margin: 0.75rem 0 !important;
                padding-left: 0.5rem !important;
            }}
            /* dt contains bullet/number - left column */
            dl.enumerate > dt, dl.itemize > dt, dl.enumerate-enumitem > dt, dl.compactdesc > dt {{
                grid-column: 1 !important;
                display: block !important;
                font-weight: 700 !important;
                color: var(--text) !important;
                text-align: right !important;
                min-width: 1.5em !important;
                visibility: visible !important;
            }}
            /* dd contains the content - right column */
            dl.enumerate > dd, dl.itemize > dd, dl.enumerate-enumitem > dd, dl.compactdesc > dd {{
                grid-column: 2 !important;
                display: block !important;
                margin: 0 !important;
                padding: 0 !important;
                max-width: 100% !important;
                word-wrap: break-word !important;
                overflow-wrap: break-word !important;
            }}
            /* Standard UL/OL lists on mobile - ensure bullets show */
            #doc_content ul, #doc_content ol {{
                list-style-position: outside !important;
                padding-left: 1.75rem !important;
                margin: 0.75rem 0 !important;
            }}
            #doc_content ul {{ list-style-type: disc !important; }}
            #doc_content ol {{ list-style-type: decimal !important; }}
            #doc_content ul ul {{ list-style-type: circle !important; }}
            #doc_content ul ul ul {{ list-style-type: square !important; }}
            #doc_content li {{
                display: list-item !important;
                margin-bottom: 0.5rem !important;
                padding-left: 0.25rem !important;
            }}
            /* Nested lists */
            #doc_content li > ul, #doc_content li > ol {{
                margin: 0.5rem 0 0.5rem 0 !important;
            }}
            /* Math inside list items - allow horizontal scroll without gray artifacts */
            dd mjx-container[display="true"], dd .MathJax_Display,
            dd mjx-container[jax="CHTML"][display="true"] {{
                max-width: none !important;
                overflow-x: auto !important;
                overflow-y: hidden !important;
                scrollbar-width: none !important;
                -webkit-overflow-scrolling: touch;
            }}
            dd mjx-container[display="true"]::-webkit-scrollbar,
            dd .MathJax_Display::-webkit-scrollbar {{
                display: none !important;
            }}
            /* MathJax Display - scrollable with COMPLETELY invisible scrollbars */
            /* Uses multiple techniques for cross-browser support */
            /* Include .mathjax-block and .mathjax-env which are TeX4ht's wrappers for display math */
            mjx-container[jax="CHTML"][display="true"], .MathJax_Display, .mathjax-block, .mathjax-env, .mathjax-equation {{
                display: block !important;
                margin: 1rem 0 !important;
                overflow-x: auto !important;
                overflow-y: visible !important;
                max-width: 100% !important;
                /* Firefox */
                scrollbar-width: none !important;
                /* IE/Edge */
                -ms-overflow-style: none !important;
                /* Safari touch scrolling */
                -webkit-overflow-scrolling: touch;
            }}
            /* WebKit/Blink scrollbar hiding - comprehensive selectors */
            mjx-container[jax="CHTML"][display="true"]::-webkit-scrollbar,
            mjx-container[display="true"]::-webkit-scrollbar,
            .MathJax_Display::-webkit-scrollbar,
            .mathjax-block::-webkit-scrollbar,
            .mathjax-env::-webkit-scrollbar,
            .mathjax-equation::-webkit-scrollbar,
            .content-scroll mjx-container::-webkit-scrollbar,
            #doc_content mjx-container::-webkit-scrollbar,
            #doc_content .mathjax-block::-webkit-scrollbar,
            #doc_content .mathjax-env::-webkit-scrollbar {{
                display: none !important;
                width: 0 !important;
                height: 0 !important;
                background: transparent !important;
                visibility: hidden !important;
            }}

            /* Display math inner content - allow natural width so parent can scroll */
            mjx-container[display="true"] > mjx-math,
            mjx-container[jax="CHTML"][display="true"] > mjx-math,
            .MathJax_Display > * {{
                max-width: none !important;
                width: max-content !important;
            }}

            /* MathJax children - visible overflow for stretchy delimiters, no scrollbars */
            mjx-container *, .mjx-chtml, .mjx-math,
            .MathJax *, mjx-math, mjx-math * {{
                overflow: visible !important;
                scrollbar-width: none !important;
                -ms-overflow-style: none !important;
                background: transparent !important;
                box-shadow: none !important;
            }}
            /* Inline MathJax containers - visible overflow */
            mjx-container:not([display="true"]), .MathJax:not(.MathJax_Display) {{
                overflow: visible !important;
                scrollbar-width: none !important;
                -ms-overflow-style: none !important;
            }}
            mjx-container:not([display="true"])::-webkit-scrollbar,
            mjx-container *::-webkit-scrollbar,
            .mjx-chtml::-webkit-scrollbar, .mjx-math::-webkit-scrollbar,
            .MathJax::-webkit-scrollbar, .MathJax *::-webkit-scrollbar,
            mjx-math::-webkit-scrollbar, mjx-math *::-webkit-scrollbar {{
                display: none !important;
                width: 0 !important;
                height: 0 !important;
                background: transparent !important;
            }}

            /* Inline math - natural flow without scrollbars */
            mjx-container[jax="CHTML"]:not([display="true"]) {{
                max-width: 100%;
                overflow: visible !important;
                display: inline-block;
            }}
            
            /* Reduce header height & fix title - ensure it stays visible */
            .top-bar {{ padding: 0 0.5rem; gap: 0.5rem; z-index: 2100 !important; position: sticky !important; }} 
            .page-title {{ 
                font-size: 0.9rem; 
                flex: 1; 
                max-width: none; 
                white-space: nowrap; 
                overflow: hidden; 
                text-overflow: ellipsis; 
            }}
            
            /* Reduce content padding */
            .container {{ padding: 1rem 0.5rem; max-width: 100%; overflow-x: hidden; box-sizing: border-box; }}
            .card {{ padding: 1rem 0.75rem; border-radius: 6px; margin: 0.5rem 0; width: 100%; max-width: 100%; overflow-x: hidden; box-sizing: border-box; }}
            
            /* Hide desktop search, show mobile toggle */
            .search-container {{ display: none !important; }}
            
            /* Smaller floating buttons */
            .float-nav {{ right: 0.75rem; bottom: 0.75rem; }}
            .float-btn {{ width: 44px; height: 44px; font-size: 1rem; }}
            
            /* Adjust images for mobile */
            #doc_content img {{ max-width: 100%; margin: 1.5rem auto; }}
            
            /* Tables scroll horizontally */
            .table-wrapper {{
                overflow-x: auto !important;
                -webkit-overflow-scrolling: touch;
                margin: 1rem -0.75rem;
                padding: 0 0.75rem;
                display: block !important;
                width: calc(100% + 1.5rem) !important;
            }}
            .table-wrapper table {{
                 width: auto !important;
                 min-width: max-content !important;
            }}
            /* Prevent vertical text in table cells - allow horizontal scroll instead */
            .table-wrapper td, .table-wrapper th {{
                white-space: nowrap !important;
                min-width: max-content !important;
            }}
            .table-wrapper td:last-child, .table-wrapper th:last-child {{
                white-space: normal !important;
                min-width: 150px !important;
            }}

            /* NOTE: Code block styling is above at line ~1107 to avoid duplication */

            /* Smaller text sizes with overflow fix */
            .sectionHead {{ font-size: 1.5rem; }}
            .subsectionHead {{ font-size: 1.3rem; }}
            
            /* Reduce header spacing on mobile */
            h2, .sectionHead {{ margin-top: 1.5rem !important; margin-bottom: 0.75rem !important; }}
            h3, .subsectionHead {{ margin-top: 1.25rem !important; margin-bottom: 0.5rem !important; }}
            h4, .subsubsectionHead {{ margin-top: 1rem !important; margin-bottom: 0.5rem !important; }}
            
            /* Fix title text overflow (issue b) */
            h1, h2, h3, h4, h5, .chapterHead, .sectionHead, .subsectionHead {{
                word-break: break-word !important;
                overflow-wrap: break-word !important;
                hyphens: auto !important;
                max-width: 100% !important;
            }}
            
            /* Touch-friendly toc links - consistent gray color for inactive items (issue c) */
            .chapter-item a {{ padding: 0.85rem 1rem; min-height: 44px; display: flex; align-items: center; color: #6b7280 !important; }}
            .chapter-item a:visited {{ color: #6b7280 !important; }}
            .local-toc a {{ color: #6b7280 !important; }}
            .chapter-item.active > a {{ color: var(--primary) !important; font-weight: 700; background: rgba(31,162,224,0.05); }}
            .toc-h3.active-scroll > a, .toc-h3.active-parent > a {{ color: var(--primary) !important; font-weight: 700; }}
            .toc-h4.active-scroll > a {{ color: var(--primary) !important; font-weight: 600; }}
            
            /* Larger images in mobile portrait (issue d) */
            #doc_content img {{ max-width: 95% !important; margin: 1.5rem auto; }}
            #doc_content .figure img, #doc_content figure img {{ max-width: 95% !important; }}
            
            /* Homepage Title Fix */
            .hero h1 {{ color: var(--primary) !important; font-size: 2.2rem !important; }}
        }}
        
        /* Landscape mode fixes (issue e) */
        @media (orientation: landscape) and (max-width: 1024px) {{
            /* Ensure hamburger stays blue in landscape */
            #menu_toggle svg, #menu_toggle {{ color: var(--primary) !important; }}
            .sidebar-toggle {{ color: var(--primary) !important; }}
            
            /* Fix spacing between hamburger and page title */
            .top-bar {{ gap: 0.75rem !important; padding: 0 1rem !important; }}
            .page-title {{ margin-left: 0.5rem !important; }}
            
            /* Ensure consistent header alignment */
            #menu_toggle {{ margin-right: 0.5rem !important; }}
        }}
        
        /* Very small phones */
        @media (max-width: 480px) {{
            .sidebar {{ width: 85vw !important; max-width: 280px; }}
            .topbar-title {{ max-width: 150px; overflow: hidden; text-overflow: ellipsis; }}
            .card {{ padding: 0.75rem; }}
            body {{ font-size: 15px; }}
        }}
    </style>
    <!-- SURGICAL CSS POLISH -->
    <style>
        /* 1. Fix Layout & Overflow - use visible to avoid scrollbar artifacts */
        div.math-display,
        .MathJax_Display, .mjx-container,
        .equation, div[id^="equation"] {{
            overflow: visible !important;
            display: block !important;
            max-width: 100% !important;
            margin-right: 0 !important;
        }}
        /* Pre blocks still need auto for code scrolling */
        pre {{ overflow-x: auto !important; display: block !important; max-width: 100% !important; }}

        /* MathJax Specific - Force container width, no scrollbar */
        mjx-container[jax="CHTML"][display="true"] {{
             min-width: 0 !important;
             max-width: 100% !important;
             overflow: visible !important;
        }}

        /* Mobile: display math needs horizontal scroll with COMPLETELY hidden scrollbars */
        /* Comprehensive cross-browser scrollbar hiding for equations */
        @media (max-width: 768px) {{
            mjx-container[jax="CHTML"][display="true"],
            .MathJax_Display, div.math-display,
            div.mathjax-block, .mathjax-block,
            mjx-container[display="true"] {{
                overflow-x: auto !important;
                overflow-y: hidden !important;
                /* Firefox - hide scrollbar */
                scrollbar-width: none !important;
                /* IE/Edge - hide scrollbar */
                -ms-overflow-style: none !important;
                /* Safari - smooth momentum scrolling */
                -webkit-overflow-scrolling: touch;
                /* Prevent any visible scrollbar track */
                scrollbar-color: transparent transparent !important;
            }}
            /* WebKit/Blink - comprehensive scrollbar hiding */
            mjx-container[jax="CHTML"][display="true"]::-webkit-scrollbar,
            mjx-container[display="true"]::-webkit-scrollbar,
            .MathJax_Display::-webkit-scrollbar,
            div.math-display::-webkit-scrollbar,
            div.mathjax-block::-webkit-scrollbar,
            .mathjax-block::-webkit-scrollbar,
            .card mjx-container::-webkit-scrollbar,
            .card-body mjx-container::-webkit-scrollbar,
            .card .mathjax-block::-webkit-scrollbar,
            #doc_content mjx-container::-webkit-scrollbar,
            #doc_content .mathjax-block::-webkit-scrollbar {{
                display: none !important;
                width: 0 !important;
                height: 0 !important;
                background: transparent !important;
                visibility: hidden !important;
                -webkit-appearance: none !important;
            }}
            /* Scrollbar thumb and track - hide completely */
            mjx-container::-webkit-scrollbar-thumb,
            mjx-container::-webkit-scrollbar-track,
            .MathJax_Display::-webkit-scrollbar-thumb,
            .MathJax_Display::-webkit-scrollbar-track,
            .mathjax-block::-webkit-scrollbar-thumb,
            .mathjax-block::-webkit-scrollbar-track {{
                background: transparent !important;
                border: none !important;
                display: none !important;
            }}
            /* Inner math element must keep natural width for scroll to work */
            mjx-container[display="true"] > mjx-math {{
                max-width: none !important;
                width: max-content !important;
            }}
            /* Mobile equation rendering fixes - ensure no clipping */
            mjx-frac, mjx-mfrac {{
                overflow: visible !important;
            }}
            /* Mobile: fix underbraces and overbraces - container needs visible */
            mjx-munder, mjx-mover, mjx-munderover {{
                overflow: visible !important;
            }}
            /* Mobile: vertical stretchy delimiters (brackets) need hidden to prevent long lines */
            mjx-stretchy-v {{
                overflow: hidden !important;
            }}
            /* ================================================================= */
            /* MOBILE UNDERBRACE/OVERBRACE FIX - CRITICAL                        */
            /* The bar through underbraces is caused by mjx-ext having width:0   */
            /* but with :after/:before pseudo-elements that stretch infinitely.  */
            /* Solution: Target mjx-ext ONLY and limit its pseudo-elements.      */
            /* mjx-beg and mjx-end are the brace endpoints - leave untouched!    */
            /* ================================================================= */
            /* Only clip the extension piece, not the whole brace structure */
            mjx-stretchy-h > mjx-ext {{
                max-width: 100% !important;
                overflow: hidden !important;
            }}
            /* The stretchy container needs visible overflow for brace ends */
            mjx-stretchy-h {{
                overflow: visible !important;
            }}
            /* mjx-beg and mjx-end must remain visible (brace ends) */
            mjx-stretchy-h > mjx-beg,
            mjx-stretchy-h > mjx-end {{
                overflow: visible !important;
            }}
            /* Ensure munder/mover containers allow proper display */
            mjx-munder, mjx-mover, mjx-munderover {{
                overflow: visible !important;
            }}
            /* Ensure equation containers remain scrollable */
            mjx-container[display="true"] {{
                overflow-x: auto !important;
                overflow-y: visible !important;
                -webkit-overflow-scrolling: touch !important;
                max-width: 100vw !important;
            }}
        }}

        body, #doc_content {{ max-width: 100vw !important; overflow-x: hidden !important; box-sizing: border-box !important; }}
        
        /* Buttons - Prevent overflow */
        .btn, button, .nav-btn, .chapter-item a {{ 
            white-space: normal !important; 
            height: auto !important; 
            min-height: 44px !important;
            word-wrap: break-word !important; 
            word-break: break-word !important;
            max-width: 100% !important;
        }}

        /* 2. Fix Colors & Contrast */
        a.nav-btn.danger {{ color: #ffffff !important; background-color: #333333 !important; }}
        input, .pagefind-ui__search-input {{ color: #000000 !important; background-color: #ffffff !important; }}

        /* 3. Fix Mobile Navbar */
        .pagefind-ui__search-clear {{ display: block !important; }}
        .sidebar-toggle {{ margin: 0 !important; padding: 0.25rem !important; }}

        /* Fix Mobile Search Visibility */
        .search-container {{ display: flex !important; margin-left: auto; }} 
        .topbar-right {{ gap: 0.5rem; }}
        .search-container.open {{ position: absolute; top: var(--header-h); left: 0; right: 0; background: #fff; padding: 1rem; border-bottom: 1px solid var(--gray-300); z-index: 999; }}
        .search-container.expandable.open .search-input-wrapper {{ width: 140px; }}
        
        /* Math Readability (Mobile) */
        .mjx-math {{ white-space: normal !important; overflow-wrap: normal !important; }}
        .mjx-char {{ display: inline-block; }}
        #doc_content .MathJax {{ font-size: 105% !important; }}

        /* MOBILE POLISH (Antigravity) */
        @media (max-width: 1024px) {{
            /* 1. Gray Background & White Cards - use CSS vars for dark mode support */
            body:not(.dark-mode):not(.high-contrast) {{ background: #e9ecef !important; }}
            body:not(.dark-mode):not(.high-contrast) .card {{ background: #ffffff !important; box-shadow: 0 2px 8px rgba(0,0,0,0.05); }}
            /* Dark mode on mobile */
            body.dark-mode {{ background: var(--bg) !important; }}
            body.dark-mode .card {{ background: var(--gray-100) !important; }}
            body.dark-mode .sidebar {{ background: var(--bg) !important; color: var(--text) !important; }}
            body.dark-mode .chapter-item > a {{ color: var(--text) !important; }}
            /* High contrast on mobile */
            body.high-contrast {{ background: #000 !important; }}
            body.high-contrast .card {{ background: #000 !important; border-color: #fff !important; }}
            body.high-contrast .sidebar {{ background: #000 !important; color: #fff !important; border-color: #fff !important; }}
            body.high-contrast .chapter-item > a {{ color: #ffff00 !important; }}

            /* 2. Header Spacing */
             /* Add gap to header title path */
            .header-title, .topbar-title {{ gap: 1rem !important; padding-left: 0.5rem !important; }}
            .sidebar-toggle {{ margin-right: 0.5rem !important; }}

            /* 3. Dropdown Link Contrast - respect dark mode */
            body:not(.dark-mode):not(.high-contrast) .dropdown-content a {{ color: #333333 !important; }}
            body.dark-mode .dropdown-content a {{ color: var(--text) !important; }}
            body.high-contrast .dropdown-content a {{ color: #ffff00 !important; }}
            
            /* 4. Sidebar Overlay Style */
            /* We inject this div via JS */
            .sidebar-overlay {{
                display: none;
                position: fixed;
                top: 0; left: 0;
                width: 100vw; height: 100vh;
                background: rgba(0,0,0,0.5);
                z-index: 1500; /* Below sidebar (2000) */
                cursor: pointer;
            }}
            /* Show overlay when sidebar is open (sibling selector works because we append overlay to body end) */
            .sidebar.open ~ .sidebar-overlay {{ display: block !important; }}
        }}
    </style>
    """

def get_js_footer():
    return r"""
    <!-- Lightbox -->
    <div class="lightbox" id="lightbox" onclick="this.classList.remove('active')">
        <img id="lightbox-img" src="" alt="Zoom">
    </div>

    <!-- Floating Nav (Fix 5: Part Nav - Chevron Icons) -->
    <div class="float-nav">
        <a class="float-btn" id="btn_prev_part" style="display:none"><i class="fas fa-chevron-up"></i></a>
        <a class="float-btn" id="btn_next_part" style="display:none"><i class="fas fa-chevron-down"></i></a>
    </div>

    <script>
        // E fix: Save initial hash BEFORE any scroll spy can overwrite it
        const INITIAL_HASH = window.location.hash;
        let initialScrollDone = false;
    document.addEventListener('DOMContentLoaded', () => {
        // 1. Sidebar Resizer
        const sidebar = document.getElementById('sidebar');
        const resizer = document.getElementById('sidebar_resizer');
        if (resizer && sidebar) {
            let x, w;
            const initResize = (e) => {
                x = e.clientX;
                w = parseInt(window.getComputedStyle(sidebar).width, 10);
                document.addEventListener('mousemove', doResize);
                document.addEventListener('mouseup', stopResize);
                document.body.style.cursor = 'col-resize';
                e.preventDefault();
            };
            const doResize = (e) => {
                const nw = w + (e.clientX - x);
                if (nw > 150 && nw < 600) {
                    sidebar.style.width = nw + 'px';
                    document.documentElement.style.setProperty('--sidebar-w', nw + 'px');
                    resizer.style.left = (nw - 4) + 'px';  // Sync handle position
                    localStorage.setItem('sidebar_w', nw + 'px');
                }
            };
            const stopResize = () => {
                document.removeEventListener('mousemove', doResize);
                document.removeEventListener('mouseup', stopResize);
                document.body.style.cursor = 'default';
            };
            resizer.addEventListener('mousedown', initResize);
        }
        const savedW = localStorage.getItem('sidebar_w');
        if(savedW && sidebar) {
            sidebar.style.width = savedW;
            document.documentElement.style.setProperty('--sidebar-w', savedW);
            if(resizer) resizer.style.left = (parseInt(savedW) - 4) + 'px';  // Sync handle on init
        }

        // 2. Syntax Highlight - Standard initialization
        function runHighlight() {
            if (window.hljs) {
                hljs.highlightAll();
                return true;
            }
            return false;
        }
        
        // Multiple attempts to ensure language packs are loaded
        function tryHighlight(attempt) {
            if (attempt > 5) return;
            setTimeout(() => {
                if (!runHighlight() && attempt < 5) {
                    tryHighlight(attempt + 1);
                }
            }, 200 * attempt);
        }
        
        // Start highlighting after DOM and scripts are fully loaded
        window.addEventListener('load', () => tryHighlight(1));
        
        document.querySelectorAll('.code-wrapper').forEach(wrapper => {
            const btn = document.createElement('button');
            btn.className = 'copy-btn';
            btn.textContent = 'Copy';
            wrapper.appendChild(btn);
            btn.onclick = () => {
                const code = wrapper.querySelector('code').innerText;
                const doCopy = () => {
                   btn.textContent = 'Copied!';
                   setTimeout(() => btn.textContent = 'Copy', 2000);
                };
                if (navigator.clipboard) {
                    navigator.clipboard.writeText(code).then(doCopy);
                } else {
                    const ta = document.createElement('textarea');
                    ta.value = code;
                    document.body.appendChild(ta);
                    ta.select();
                    document.execCommand('copy');
                    document.body.removeChild(ta);
                    doCopy();
                }
            };
        });

        // 3. Lightbox (Fix 6)
        document.querySelectorAll('#doc_content img').forEach(img => {
            img.onclick = (e) => {
                e.preventDefault();
                document.getElementById('lightbox-img').src = img.src;
                document.getElementById('lightbox').classList.add('active');
            };
        });

        // 4. Scroll Spy & Floating Part Nav (Fix 4B & 5)
        const scrollEl = document.getElementById('content_area');
        // Expanded selectors for subs - include h1 for Preface
        // Also include elements with id attribute for better anchor coverage
        // Select all headings and section elements with IDs for scroll spy
        const targets = Array.from(document.querySelectorAll('#doc_content h1[id], #doc_content h2[id], #doc_content h3[id], #doc_content h4[id], #doc_content h5[id], #doc_content .subsectionHead[id], #doc_content .sectionHead[id], #doc_content .subsubsectionHead[id]'));
        console.log('Scroll spy targets:', targets.length, 'headings with IDs');
        
        const btnPrev = document.getElementById('btn_prev_part');
        const btnNext = document.getElementById('btn_next_part');

        function updateNav() {
            if(!scrollEl) return;
            if(targets.length === 0) return;
            
            // Container-relative position calculation
            const scrollElRect = scrollEl.getBoundingClientRect();
            const scrollPos = scrollEl.scrollTop;
            
            let activeIdx = -1;
            for(let i=0; i<targets.length; i++) {
                const targetRect = targets[i].getBoundingClientRect();
                const relativeTop = targetRect.top - scrollElRect.top + scrollPos;
                if(relativeTop <= scrollPos + 200) activeIdx = i;
                else break;
            }
            
            // Sidebar Highlight & Accordion Logic
            // 1. Reset: Remove active marks and hide all sub-lists
            document.querySelectorAll('.active-scroll, .active-parent').forEach(e => e.classList.remove('active-scroll', 'active-parent'));
            document.querySelectorAll('.toc-sub-list').forEach(el => el.classList.remove('visible'));
            
            if(activeIdx >= 0 && targets[activeIdx].id) {
                const id = targets[activeIdx].id;
                // FIX: Do NOT use CSS.escape in href selector - iterate and match instead
                const tocLinks = document.querySelectorAll('.local-toc a');
                let matchedLink = null;
                for(let link of tocLinks) {
                    if(link.getAttribute('href') === '#' + id) {
                        matchedLink = link;
                        break;
                    }
                }
                
                if(matchedLink) {
                    const li = matchedLink.parentElement;
                    li.classList.add('active-scroll');
                    
                    // IF we are an H4 (child under H3):
                    const parentUl = li.closest('.toc-sub-list');
                    if(parentUl) {
                        // Show my parent UL
                        parentUl.classList.add('visible');
                        // Highlight my parent H3 LI
                        if(parentUl.parentElement) parentUl.parentElement.classList.add('active-parent');
                    }
                    
                    // IF we are an H3 (parent):
                    if(li.classList.contains('toc-h3')) {
                        li.classList.add('active-parent');
                        const subList = li.querySelector('.toc-sub-list');
                        if(subList) subList.classList.add('visible');
                    }
                }
                
                // A3: Auto-update URL hash without scrolling (for deep linking)
                // E fix: Don't overwrite hash until initial hash scroll is complete
                if(initialScrollDone) {
                    const newHash = '#' + id;
                    if(window.location.hash !== newHash) {
                        history.replaceState(null, '', newHash);
                    }
                }
            }
            
            // Float Nav (Subsection aware) - container-relative scrolling
            if(activeIdx > 0) {
                btnPrev.style.display = 'flex';
                btnPrev.onclick = () => {
                    const target = targets[activeIdx-1];
                    const targetRect = target.getBoundingClientRect();
                    const scrollElRect = scrollEl.getBoundingClientRect();
                    const relativeTop = targetRect.top - scrollElRect.top + scrollEl.scrollTop;
                    scrollEl.scrollTo({top: relativeTop - 100, behavior:'smooth'});
                };
            } else {
                btnPrev.style.display = 'none';
            }
            
            if(activeIdx < targets.length - 1 && activeIdx >= -1) {
                btnNext.style.display = 'flex';
                btnNext.onclick = () => {
                    const target = targets[activeIdx+1];
                    const targetRect = target.getBoundingClientRect();
                    const scrollElRect = scrollEl.getBoundingClientRect();
                    const relativeTop = targetRect.top - scrollElRect.top + scrollEl.scrollTop;
                    scrollEl.scrollTo({top: relativeTop - 100, behavior:'smooth'});
                };
            } else {
                btnNext.style.display = 'none';
            }
        }
        
        if(scrollEl) {
            // Debounce scroll for performance
            let scrollTimeout;
            const debouncedUpdateNav = () => {
                if (scrollTimeout) return;
                scrollTimeout = setTimeout(() => {
                    updateNav();
                    scrollTimeout = null;
                }, 100);
            };
            scrollEl.addEventListener('scroll', debouncedUpdateNav, { passive: true });
            updateNav();
        }

        // 4B. Robust in-page anchor navigation (Issue 1 fix)
        // Intercept anchor clicks and scroll within the scrolling container
        document.querySelectorAll('a[href^="#"]').forEach(anchor => {
            anchor.addEventListener('click', function(e) {
                const href = this.getAttribute('href');
                const targetId = decodeURIComponent(href.slice(1));
                if (!targetId) return; // Empty hash
                
                const targetEl = document.getElementById(targetId);
                if (!targetEl) return;
                
                e.preventDefault();
                
                // Close sidebar if on mobile
                const sb = document.getElementById('sidebar');
                if(sb && window.innerWidth <= 1024) sb.classList.remove('open');
                
                // Update URL hash for shareable links BEFORE scrolling to avoid race
                if(window.location.hash !== href) {
                    history.replaceState(null, '', href);
                }
                
                // Use a more robust scrolling strategy
                const performScroll = () => {
                    if (scrollEl) {
                        const targetRect = targetEl.getBoundingClientRect();
                        const scrollElRect = scrollEl.getBoundingClientRect();
                        const relativeTop = targetRect.top - scrollElRect.top + scrollEl.scrollTop;
                        scrollEl.scrollTo({ top: Math.max(0, relativeTop - 120), behavior: 'smooth' });
                    } else {
                        targetEl.scrollIntoView({ behavior: 'smooth', block: 'start' });
                    }
                };
                
                // Double-pass scroll to handle dynamic font/math loading shifts
                performScroll();
                setTimeout(performScroll, 300); 
            });
        });
        
        // E fix: Runtime scroll container detection
        function getScrollContainer() {
            for (const sel of ['#content_area', '.content-scroll', 'main']) {
                const el = document.querySelector(sel);
                if (el && el.scrollHeight > el.clientHeight) return el;
            }
            return document.scrollingElement || document.documentElement;
        }
        
        // Handle hash navigation (cross-page and in-page)
        // E fix: Use saved INITIAL_HASH instead of current location.hash
        function scrollToHash(useInitialHash = false) {
            const hash = useInitialHash ? INITIAL_HASH : window.location.hash;
            if (!hash) return false;
            let targetId = decodeURIComponent(hash.slice(1));
            let targetEl = document.getElementById(targetId);

            // If not found and looks like a bib link, try normalizing the key
            // Bibliography links may have prefixes like "bib-0@key" but elements have "bib-key"
            if (!targetEl && targetId.startsWith('bib-')) {
                const bibKey = targetId.slice(4); // Remove "bib-" prefix
                // Normalize: strip numeric@ prefix (e.g., "0@eigen2014" -> "eigen2014")
                const normalizedKey = bibKey.replace(/^\d+@/, '');
                if (normalizedKey !== bibKey) {
                    const normalizedId = 'bib-' + normalizedKey;
                    targetEl = document.getElementById(normalizedId);
                    if (targetEl) {
                        targetId = normalizedId;
                        // Update URL to use normalized hash (cleaner URLs)
                        history.replaceState(null, '', '#' + normalizedId);
                    }
                }
            }

            if (!targetEl) {
                // Diagnostic: log closest matches for debugging TeX4ht IDs
                console.log('Hash not found:', targetId);
                return false;
            }

            const container = getScrollContainer();
            const scrollTop = container === document.scrollingElement ? window.scrollY : container.scrollTop;
            const containerRect = container.getBoundingClientRect();
            const targetRect = targetEl.getBoundingClientRect();
            const relativeTop = targetRect.top - containerRect.top + scrollTop;

            // Increase offset for mobile to account for different header sizes
            const isMobile = window.innerWidth <= 1024;
            const headerOffset = isMobile ? 180 : 120;

            container.scrollTo({ top: Math.max(0, relativeTop - headerOffset), behavior: 'auto' });
            console.log('Scrolled to:', targetId, 'offset:', headerOffset);
            return true;
        }
        
        // MathJax: wait for startup.promise (NOT typesetPromise which re-typesets)
        function scrollAfterMathJax() {
            if (typeof MathJax !== 'undefined' && MathJax.startup && MathJax.startup.promise) {
                MathJax.startup.promise.then(() => {
                    scrollToHash(true);  // Use INITIAL_HASH
                    initialScrollDone = true;
                    removeMathScrollbars(); fixUnderbraces(); fixStretchyVertical(); // Fix all MathJax rendering issues
                }).catch(() => {
                    scrollToHash(true);
                    initialScrollDone = true;
                    removeMathScrollbars(); fixUnderbraces(); fixStretchyVertical();
                });
            } else {
                scrollToHash(true);  // Use INITIAL_HASH
                initialScrollDone = true;
            }
        }

        // Fix underbrace/overbrace rendering - clip only the mjx-ext element
        // The mjx-ext element stretches infinitely; mjx-beg and mjx-end are brace endpoints
        function fixUnderbraces() {
            // Target only the extension piece inside stretchy-h, not the whole structure
            document.querySelectorAll('mjx-stretchy-h > mjx-ext').forEach(ext => {
                ext.style.maxWidth = '100%';
                ext.style.overflow = 'hidden';
            });
            // The stretchy-h container itself needs visible overflow for brace ends
            document.querySelectorAll('mjx-stretchy-h').forEach(stretchyH => {
                stretchyH.style.overflow = 'visible';
            });
            // mjx-beg and mjx-end (brace endpoints) must stay visible
            document.querySelectorAll('mjx-stretchy-h > mjx-beg, mjx-stretchy-h > mjx-end').forEach(el => {
                el.style.overflow = 'visible';
            });
            // Ensure munder/mover containers have visible overflow for proper display
            document.querySelectorAll('mjx-munder, mjx-mover, mjx-munderover').forEach(el => {
                el.style.overflow = 'visible';
            });
        }

        // Fix vertical stretchy elements (brackets on matrices/vectors)
        function fixStretchyVertical() {
            document.querySelectorAll('mjx-stretchy-v').forEach(stretchyV => {
                stretchyV.style.overflow = 'hidden';
                stretchyV.style.maxHeight = '100%';
                stretchyV.style.display = 'inline-block';
                // The ext element inside stretchy-v extends infinitely
                const ext = stretchyV.querySelector('mjx-ext');
                if (ext) {
                    ext.style.maxHeight = '100%';
                    ext.style.overflow = 'hidden';
                }
            });
        }

        // Remove scrollbar artifacts and gray boxes from MathJax elements
        function removeMathScrollbars() {
            // Hide assistive MML elements (common cause of gray boxes)
            document.querySelectorAll('mjx-assistive-mml').forEach(el => {
                el.style.display = 'none';
                el.style.visibility = 'hidden';
                el.style.position = 'absolute';
                el.style.width = '1px';
                el.style.height = '1px';
                el.style.overflow = 'hidden';
                el.style.clip = 'rect(0,0,0,0)';
            });

            // Fix all MathJax containers and children
            // NOTE: Do NOT set border:none on children - it breaks MathJax internal rendering (fraction lines, delimiters)
            // But DO set background:transparent on children to prevent gray artifacts
            const isMobile = window.innerWidth <= 768;
            document.querySelectorAll('mjx-container, mjx-math, .MathJax, .MathJax_Display, .math-display').forEach(el => {
                const isDisplay = el.getAttribute('display') === 'true' || el.classList.contains('MathJax_Display') || el.classList.contains('math-display');
                if (isMobile && isDisplay) {
                    // Display math on mobile: scrollable with hidden scrollbars (no clipping)
                    el.style.overflowX = 'auto';
                    el.style.overflowY = 'hidden';
                } else {
                    el.style.overflow = 'visible';
                    el.style.overflowX = 'visible';
                    el.style.overflowY = 'visible';
                }
                el.style.scrollbarWidth = 'none';
                el.style.msOverflowStyle = 'none';
                el.style.background = 'transparent';
                el.style.outline = 'none';
                el.style.boxShadow = 'none';
                // Fix children: overflow, scrollbar, and background - but NOT border
                // Handle stretchy elements specially:
                // - mjx-stretchy-h (horizontal braces): allow visible overflow
                // - mjx-stretchy-v (vertical brackets): need clipping to prevent long lines
                el.querySelectorAll('*').forEach(child => {
                    const tagName = child.tagName ? child.tagName.toLowerCase() : '';
                    // Vertical stretchy elements need hidden overflow (prevents long black lines)
                    const isVerticalStretchy = tagName === 'mjx-stretchy-v';
                    const inVerticalStretchy = child.closest('mjx-stretchy-v');
                    if (isVerticalStretchy || inVerticalStretchy) {
                        // Keep overflow hidden for vertical stretchy (set by fixStretchyVertical)
                    } else {
                        // Everything else (including horizontal stretchy) gets visible overflow
                        child.style.overflow = 'visible';
                    }
                    child.style.scrollbarWidth = 'none';
                    // Don't set transparent background on mjx-line/mjx-rule (they draw the lines!)
                    if (tagName !== 'mjx-line' && tagName !== 'mjx-rule') {
                        child.style.background = 'transparent';
                    }
                });
            });

            // Fix enumerate/itemize list elements (source of gray scrollbar artifacts)
            document.querySelectorAll('dl.enumerate, dl.itemize, dl.enumerate-enumitem, dl.compactdesc').forEach(el => {
                el.style.overflow = 'visible';
                el.style.scrollbarWidth = 'none';
                el.style.msOverflowStyle = 'none';
                // Fix dt and dd children
                el.querySelectorAll('dt, dd').forEach(child => {
                    child.style.overflow = 'visible';
                    child.style.scrollbarWidth = 'none';
                    child.style.msOverflowStyle = 'none';
                });
            });
        }
        
        // 4B. Robust in-page anchor navigation & Bib Link Fix
        window.addEventListener('load', () => {
            scrollAfterMathJax();
            // Retry scrolling multiple times to handle dynamic loading/layout shifts
            // Also remove math scrollbars at each interval
            [100, 500, 1000, 2000].forEach(delay => {
                setTimeout(() => {
                    if(!initialScrollDone || window.location.hash) scrollToHash(true);
                    removeMathScrollbars(); fixUnderbraces(); fixStretchyVertical(); // Keep fixing MathJax rendering
                }, delay);
            });

            // Mobile header fix: Ensure viewport never scrolls (only .content-scroll should)
            // On mobile, browser's native hash-scroll can scroll viewport instead of .content-scroll,
            // pushing the sticky header out of view. Fix: intercept and redirect to correct container.
            if (window.innerWidth <= 768) {
                const contentScroll = document.querySelector('.content-scroll');
                if (contentScroll) {
                    // Function to reset viewport and scroll correct container
                    const fixMobileScroll = (scrollToTarget = true) => {
                        const viewportScrolled = window.scrollY > 0 ||
                            document.documentElement.scrollTop > 0 ||
                            document.body.scrollTop > 0;

                        if (viewportScrolled) {
                            // Reset viewport scroll
                            window.scrollTo(0, 0);
                            document.documentElement.scrollTop = 0;
                            document.body.scrollTop = 0;

                            // Scroll to hash in correct container
                            if (scrollToTarget && window.location.hash) {
                                scrollToHash(true);
                            }
                        }
                    };

                    // Immediate check on load
                    fixMobileScroll(true);

                    // Check again after browser might have scrolled
                    [50, 100, 200, 300, 500].forEach(delay => {
                        setTimeout(() => fixMobileScroll(true), delay);
                    });

                    // Scroll listener as ongoing guard
                    window.addEventListener('scroll', () => {
                        if (window.scrollY > 0) {
                            fixMobileScroll(!initialScrollDone);
                        }
                    }, { passive: true });
                }
            }
        });

        // Handle bfcache restore - re-scroll to hash in correct container
        window.addEventListener('pageshow', (event) => {
            if (event.persisted) {
                // Reset any viewport scroll that might have persisted
                if (window.innerWidth <= 768 && document.querySelector('.content-scroll')) {
                    window.scrollTo(0, 0);
                }
                if (window.location.hash) {
                    setTimeout(() => scrollToHash(false), 50);
                }
            }
        });

        // Handle in-page hash changes (TOC clicks, back/forward)
        window.addEventListener('hashchange', () => {
            // On mobile, reset viewport first
            if (window.innerWidth <= 768 && document.querySelector('.content-scroll')) {
                window.scrollTo(0, 0);
                document.documentElement.scrollTop = 0;
            }
            scrollToHash(false);
        });

        // 5. Sidebar Toggle (Fix ghost sidebar issue a)
        const menuBtn = document.getElementById('menu_toggle');
        if(menuBtn && sidebar) {
            menuBtn.onclick = (e) => {
                e.stopPropagation();
                // Clean toggle: On mobile, handle open/close properly
                if (sidebar.classList.contains('open')) {
                    sidebar.classList.remove('open');
                } else {
                    // Remove any stale width adjustments and collapsed state before opening on mobile
                    sidebar.style.width = '';
                    if (window.innerWidth <= 1024) {
                        sidebar.classList.remove('collapsed');  // Clear collapsed on mobile
                    }
                    sidebar.classList.add('open');
                }
            };
        }
        
        // 6. Top Button
        const btnTop = document.getElementById('btn_top');
        if(btnTop && scrollEl) btnTop.onclick = () => scrollEl.scrollTo({top:0, behavior:'smooth'});
        
        // 7. Sidebar Collapse Toggle (inside sidebar) - only works on desktop
        const sidebarToggle = document.getElementById('sidebar_toggle');
        if(sidebarToggle && sidebar) {
            sidebarToggle.onclick = (e) => {
                e.stopPropagation();
                // On mobile this should just close the sidebar, not toggle collapsed
                if (window.innerWidth <= 1024) {
                    sidebar.classList.remove('open');
                } else {
                    sidebar.classList.toggle('collapsed');
                }
            };
        }

        // MOBILE POLISH JS: Overlay & Auto-Close
        if (window.innerWidth <= 1024) {
            // 1. Inject Overlay if missing
            if (!document.getElementById('sidebar_overlay')) {
                const ov = document.createElement('div');
                ov.id = 'sidebar_overlay';
                ov.className = 'sidebar-overlay';
                document.body.appendChild(ov);
                
                // 2. Click Handler (Close sidebar)
                ov.addEventListener('click', () => {
                    const sb = document.getElementById('sidebar');
                    if(sb) sb.classList.remove('open');
                });
            }
            
            // 3. Auto-close sidebar on link click (including TOC links)
            document.querySelectorAll('.chapter-item a, .local-toc a, .nav-btn, .dropdown-content a').forEach(el => {
                el.addEventListener('click', () => {
                   const sb = document.getElementById('sidebar');
                   if(sb) sb.classList.remove('open');
                });
            });
        }
        
        // 8. Smart Pagefind Search (Expandable & Offline-aware)
        (async function initSearch() {
            const inputs = document.querySelectorAll('.pagefind-trigger');
            const topSearchEl = document.getElementById('top_search');
            const topTrigger = document.getElementById('search_trigger');
            
            if (inputs.length === 0) return;

            // Helper: Offline State
            const setOffline = () => {
                if(topSearchEl) {
                    topSearchEl.classList.add('offline');
                    if(topTrigger) topTrigger.title = "Search unavailable (Build required)";
                }
                inputs.forEach(inp => {
                    inp.placeholder = "Search unavailable";
                    inp.disabled = true;
                });
            };

            // Enable expanding logic for Top Bar BEFORE Pagefind loads (so it works offline too)
            if (topSearchEl && topTrigger) {
                topTrigger.addEventListener('click', (e) => {
                    e.stopPropagation();
                    topSearchEl.classList.toggle('open');
                    if (topSearchEl.classList.contains('open')) {
                        const inp = topSearchEl.querySelector('input');
                        if(inp) setTimeout(() => inp.focus(), 100);
                    }
                });
                document.addEventListener('click', (e) => {
                    if (topSearchEl.classList.contains('open') && !topSearchEl.contains(e.target)) {
                        const inp = topSearchEl.querySelector('input');
                        const isMobile = window.innerWidth <= 768;
                        // On mobile: always close on outside click. On desktop: only close if empty
                        if (isMobile || (inp && !inp.value.trim())) {
                            topSearchEl.classList.remove('open');
                        }
                    }
                });
            }

            try {
                // Use relative path for GitHub Pages subpath compatibility (e.g., /DL4CV/)
                const base = document.querySelector('base')?.href || window.location.origin + window.location.pathname.split('/').slice(0, -1).join('/') + '/';
                const pagefindUrl = new URL('pagefind/pagefind.js', base).href;
                const pagefind = await import(pagefindUrl);
                await pagefind.init();
                
                // --- ONLINE MODE ---
                console.log('Pagefind loaded successfully');

                // 2. Enable Search Logic for all inputs
                inputs.forEach(inp => {
                    inp.disabled = false;
                    inp.placeholder = inp.dataset.activePlaceholder || "Search...";
                    
                    let debounce;
                    inp.addEventListener('input', (e) => {
                        const query = e.target.value.trim();
                        const wrapper = inp.closest('.search-container') || inp.closest('.hero-search-wrapper');
                        const resultsDiv = wrapper ? wrapper.querySelector('.search-results') : null;
                        if (!resultsDiv) return;
                        
                        clearTimeout(debounce);
                        debounce = setTimeout(async () => {
                            if (!query) { resultsDiv.classList.remove('active'); return; }
                            
                            const search = await pagefind.search(query);
                            const allResults = search.results;
                            
                            // Header
                            let html = `<div style="padding:0.5rem 1rem; font-size:0.85rem; color:#666; border-bottom:1px solid #eee;">${allResults.length} results</div>`;
                            
                            // Render function
                            const renderBatch = async (start, count) => {
                                const batch = allResults.slice(start, start + count);
                                const data = await Promise.all(batch.map(r => r.data()));
                                return data.map(r => {
                                    let targetUrl = r.url;

                                    // Find the anchor that best matches the displayed excerpt
                                    // Pagefind's sub_results contain anchors for sections where matches appear
                                    if (r.sub_results && r.sub_results.length > 0) {
                                        const mainExcerpt = r.excerpt.replace(/<[^>]*>/g, '').toLowerCase().trim();

                                        // Extract highlighted words from excerpt (text within <mark> tags)
                                        const markMatches = r.excerpt.match(/<mark>([^<]+)<\/mark>/gi) || [];
                                        const highlightedWords = markMatches.map(m => m.replace(/<\/?mark>/gi, '').toLowerCase().trim());

                                        let bestMatch = null;
                                        let bestScore = -1;

                                        // Sort sub_results by specificity (prefer deeper anchors with more specific content)
                                        const sortedSubs = [...r.sub_results].sort((a, b) => {
                                            const aAnchor = (a.url || '').split('#')[1] || '';
                                            const bAnchor = (b.url || '').split('#')[1] || '';
                                            return bAnchor.length - aAnchor.length;
                                        });

                                        for (const sub of sortedSubs) {
                                            if (!sub.url || !sub.url.includes('#')) continue;

                                            const subExcerpt = (sub.excerpt || '').replace(/<[^>]*>/g, '').toLowerCase().trim();
                                            const anchor = sub.url.split('#')[1] || '';

                                            // Calculate match score
                                            let score = 0;

                                            // CRITICAL: Check if sub_result's excerpt matches the displayed excerpt
                                            // This is the key fix - we want the anchor for the DISPLAYED text
                                            if (subExcerpt === mainExcerpt) {
                                                score += 500; // Exact match - this is the one!
                                            } else if (mainExcerpt.includes(subExcerpt.substring(0, 40)) || subExcerpt.includes(mainExcerpt.substring(0, 40))) {
                                                score += 200; // Strong overlap
                                            }

                                            // Check if highlighted words appear in this sub_result's excerpt
                                            for (const word of highlightedWords) {
                                                if (word.length > 2 && subExcerpt.includes(word)) {
                                                    score += 50; // Matching highlighted word
                                                }
                                            }

                                            // Word-level overlap for fuzzy matching
                                            const mainWords = mainExcerpt.split(/\s+/).filter(w => w.length > 3);
                                            const subWords = subExcerpt.split(/\s+/);
                                            const overlap = mainWords.filter(w => subWords.includes(w)).length;
                                            score += overlap * 10;

                                            // Bonus for specific/deep anchors (but don't overwhelm text matches)
                                            if (anchor.includes('-') && anchor.length > 10) {
                                                score += 5; // Small bonus for specific section IDs
                                            }

                                            if (score > bestScore) {
                                                bestScore = score;
                                                bestMatch = sub;
                                            }
                                        }

                                        // Use best match if we found a good one
                                        if (bestMatch && bestScore > 0) {
                                            targetUrl = bestMatch.url;
                                        } else if (r.sub_results.length > 0) {
                                            // Fallback: use first sub_result with anchor (sorted by specificity)
                                            const withAnchor = sortedSubs.find(s => s.url && s.url.includes('#'));
                                            if (withAnchor) {
                                                targetUrl = withAnchor.url;
                                            }
                                        }
                                    }

                                    return `
                                    <a href="${targetUrl}" class="search-result-item">
                                        <div class="search-result-title">${r.meta.title || 'Untitled'}</div>
                                        <div class="search-result-excerpt">${r.excerpt}</div>
                                    </a>`;
                                }).join('');
                            };
                            
                            // Initial Render
                            const initialBatchHtml = await renderBatch(0, 5);
                            html += `<div class="results-list">${initialBatchHtml}</div>`;
                            
                            // Load More Button
                            if (allResults.length > 5) {
                                html += `<button class="search-load-more" data-loaded="5" style="width:100%; padding:0.8rem; border:none; background:#f8f9fa; color:var(--primary); cursor:pointer; font-weight:600; border-top:1px solid #eee;">Load more (${allResults.length - 5} remaining)</button>`;
                            }
                            
                            if (allResults.length === 0) {
                                html = '<div style="padding:1rem; text-align:center; color:#666;">No results found</div>';
                            }
                            
                            resultsDiv.innerHTML = html;
                            resultsDiv.classList.add('active');

                            // Helper function to bind search result click handlers for proper anchor scrolling
                            const bindSearchResultHandlers = (container) => {
                                container.querySelectorAll('.search-result-item').forEach(link => {
                                    link.addEventListener('click', (e) => {
                                        // ALWAYS close search dropdown immediately on any click
                                        const topSearch = document.getElementById('top_search');
                                        if (topSearch) {
                                            topSearch.classList.remove('open');
                                            // Also clear/hide results
                                            const results = topSearch.querySelector('.search-results');
                                            if (results) results.classList.remove('active');
                                        }
                                        // Also close hero search if on homepage
                                        const heroResults = document.querySelector('.hero-search-wrapper .search-results');
                                        if (heroResults) heroResults.classList.remove('active');

                                        const href = link.getAttribute('href');
                                        if (href && href.includes('#')) {
                                            const [url, hash] = href.split('#');
                                            const currentPath = window.location.pathname;
                                            const targetPath = url || currentPath;

                                            // Same page: prevent default and scroll manually with proper offset
                                            if (targetPath === currentPath || url === '') {
                                                e.preventDefault();
                                                window.location.hash = '#' + hash;
                                                // Delay for layout
                                                setTimeout(() => {
                                                    const targetEl = document.getElementById(hash);
                                                    if (targetEl) {
                                                        const scrollContainer = document.querySelector('.content-scroll') || document.scrollingElement;
                                                        const scrollTop = scrollContainer === document.scrollingElement ? window.scrollY : scrollContainer.scrollTop;
                                                        const containerRect = scrollContainer.getBoundingClientRect();
                                                        const targetRect = targetEl.getBoundingClientRect();
                                                        const relativeTop = targetRect.top - containerRect.top + scrollTop;
                                                        // Use mobile-aware offset like scrollToHash
                                                        const isMobile = window.innerWidth <= 768;
                                                        const headerOffset = isMobile ? 180 : 120;
                                                        scrollContainer.scrollTo({ top: Math.max(0, relativeTop - headerOffset), behavior: 'smooth' });
                                                    }
                                                }, 150);
                                            }
                                            // Cross-page navigation: let browser handle, search already closed above
                                        }
                                    });
                                });
                            };

                            // Bind handlers to initial results
                            bindSearchResultHandlers(resultsDiv);

                            // Bind Load More Click
                            const loadBtn = resultsDiv.querySelector('.search-load-more');
                            if(loadBtn) {
                                loadBtn.onclick = async (e) => {
                                    e.stopPropagation();
                                    const loaded = parseInt(loadBtn.dataset.loaded);
                                    loadBtn.innerText = "Loading...";
                                    const nextBatchHtml = await renderBatch(loaded, 10);

                                    const list = resultsDiv.querySelector('.results-list');
                                    list.insertAdjacentHTML('beforeend', nextBatchHtml);

                                    const newLoaded = loaded + 10;
                                    loadBtn.dataset.loaded = newLoaded;
                                    const remaining = allResults.length - newLoaded;

                                    if(remaining <= 0) {
                                        loadBtn.style.display = 'none';
                                    } else {
                                        loadBtn.innerText = `Load more (${remaining} remaining)`;
                                    }

                                    // Re-bind handlers for newly loaded results
                                    bindSearchResultHandlers(resultsDiv);
                                };
                            }
                        }, 200);
                    });
                });

            } catch (e) {
                console.warn("Pagefind not found (Local Mode). Search disabled.");
                setOffline();
            }
        })();

        // 9. Syntax Highlighting (Robust)
        function runHighlight() {
            if (window.hljs) {
                hljs.highlightAll();
                return true;
            }
            return false;
        }
        function tryHighlight(count) {
            if (runHighlight()) return;
            if (count < 10) setTimeout(() => tryHighlight(count + 1), 200);
        }
        // Trigger logic
        window.addEventListener('load', () => tryHighlight(0));

        // Bug 5: Escape key closes search
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                const topSearch = document.getElementById('top_search');
                if (topSearch && topSearch.classList.contains('open')) {
                    topSearch.classList.remove('open');
                    const resultsDiv = topSearch.querySelector('.search-results');
                    if (resultsDiv) resultsDiv.classList.remove('active');
                }
            }
        });

        // Feature: Accessibility Button
        (function initAccessibility() {
            // Find existing float-nav
            const floatNav = document.querySelector('.float-nav');
            if(!floatNav) return; // Should exist if core.py creates it
            
            const fab = document.createElement('div');
            fab.style.position = 'relative'; // Container for button + menu
            
            fab.innerHTML = `
                <button class="accessibility-btn" title="Accessibility Options" aria-label="Accessibility menu">
                    <i class="fas fa-universal-access"></i>
                </button>
                <div class="accessibility-menu">
                    <div class="accessibility-option" data-action="dark-mode">
                        <i class="fas fa-moon"></i><span>Dark Mode</span>
                    </div>
                    <div class="accessibility-option" data-action="font-increase">
                        <i class="fas fa-text-height"></i><span>Larger Text</span>
                    </div>
                    <div class="accessibility-option" data-action="font-decrease">
                        <i class="fas fa-font"></i><span>Smaller Text</span>
                    </div>
                    <div class="accessibility-option" data-action="high-contrast">
                        <i class="fas fa-adjust"></i><span>High Contrast</span>
                    </div>
                </div>
            `;
            
            // Prepend to float-nav to be at the "top" of the column (visually above prev/next)
            floatNav.insertBefore(fab, floatNav.firstChild);
            
            const btn = fab.querySelector('.accessibility-btn');
            const menu = fab.querySelector('.accessibility-menu');
            
            btn.addEventListener('click', (e) => {
                e.stopPropagation();
                menu.classList.toggle('open');
            });
            document.addEventListener('click', (e) => {
                if (!fab.contains(e.target)) menu.classList.remove('open');
            });
            // Load persisted font size or default to 100
            let fontSize = parseInt(localStorage.getItem('fontSize')) || 100;
            if (fontSize !== 100) {
                document.documentElement.style.fontSize = fontSize + '%';
            }

            fab.querySelectorAll('.accessibility-option').forEach(opt => {
                opt.addEventListener('click', () => {
                    const action = opt.dataset.action;
                    if (action === 'dark-mode') {
                        document.body.classList.toggle('dark-mode');
                        opt.classList.toggle('active', document.body.classList.contains('dark-mode'));
                        localStorage.setItem('darkMode', document.body.classList.contains('dark-mode'));
                    } else if (action === 'font-increase') {
                        fontSize = Math.min(fontSize + 10, 150);
                        document.documentElement.style.fontSize = fontSize + '%';
                        localStorage.setItem('fontSize', fontSize);
                    } else if (action === 'font-decrease') {
                        fontSize = Math.max(fontSize - 10, 80);
                        document.documentElement.style.fontSize = fontSize + '%';
                        localStorage.setItem('fontSize', fontSize);
                    } else if (action === 'high-contrast') {
                        document.body.classList.toggle('high-contrast');
                        opt.classList.toggle('active', document.body.classList.contains('high-contrast'));
                        localStorage.setItem('highContrast', document.body.classList.contains('high-contrast'));
                    }
                });
            });
            // Restore persisted accessibility settings
            if (localStorage.getItem('darkMode') === 'true') {
                document.body.classList.add('dark-mode');
                fab.querySelector('[data-action="dark-mode"]').classList.add('active');
            }
            if (localStorage.getItem('highContrast') === 'true') {
                document.body.classList.add('high-contrast');
                fab.querySelector('[data-action="high-contrast"]').classList.add('active');
            }
        })();

    });
    </script>
    """

def build_sidebar(active_mk, is_aux=False, local_toc_content=""):
    home_url = get_asset_url("index.html", is_aux)
    preface_url = get_asset_url("Auxiliary/Preface.html", is_aux)
    dep_url = get_asset_url("dependency_graph.html", is_aux)
    bib_url = get_asset_url("bibliography.html", is_aux)
    repo_url = "https://github.com/RonsGit/DL4CV"
    star_url = "https://github.com/RonsGit/DL4CV/stargazers"
    
    html = f'''
    <div class="sidebar-header">
        <div class="header-title" style="display: flex; align-items: center; gap: 0.75rem;">
            <button id="sidebar_toggle" class="sidebar-toggle"><i class="fas fa-bars"></i></button>
            <a href="{home_url}" style="text-decoration:none; color:inherit; font-size: 1.1rem;"><span>CVBook</span></a>
        </div>
        <div class="repo-links" style="display: flex; align-items: center; gap: 10px; margin-top: 0.75rem; padding-left: 0.5rem;">
             <!-- Repo -->
             <a href="{repo_url}" target="_blank" style="color: #333; font-size: 1.6rem; text-decoration: none;"><i class="fab fa-github"></i></a>
             <!-- Star -->
             <a href="{star_url}" target="_blank" onclick="event.preventDefault(); window.open('https://github.com/login?return_to=%2FDLCVBook%2FCVBook', '_blank');" style="text-decoration: none; color: #24292e; background-color: #eff3f6; border: 1px solid rgba(27,31,35,0.2); border-radius: 4px; padding: 2px 8px; font-size: 12px; font-weight: 600; display: inline-flex; align-items: center; gap: 4px;">
                <i class="far fa-star"></i> Star
             </a>
        </div>
    </div>
    
    <!-- Fix 4: Ordering (Home -> Preface -> Dep -> Bib -> Chapters) -->
    <ul class="chapter-list">
        <li class="chapter-item {'active' if str(active_mk) == 'index' or str(active_mk) == 'home' else ''}"><a href="{home_url}">Home</a></li>
        <li class="chapter-item {'active' if str(active_mk) == 'preface' or 'preface' in str(active_mk) else ''}"><a href="{preface_url}">Preface</a></li>
        <li class="chapter-item {'active' if str(active_mk) == 'dep' or 'dependency' in str(active_mk) else ''}"><a href="{dep_url}">Dependency Graph</a></li>
        <li class="chapter-item {'active' if str(active_mk) == 'bib' or 'bibliography' in str(active_mk) else ''}"><a href="{bib_url}">Bibliography</a></li>
    '''
    
    current_num = -1
    if isinstance(active_mk, int): current_num = active_mk
    
    for ch in CHAPTERS:
        active = " active" if ch['num'] == current_num else ""
        ch_url = get_asset_url(ch["file"], is_aux)
        html += f'<li class="chapter-item{active}">'
        html += f'<a href="{ch_url}">Lecture {ch["num"]}: {ch["title"]}</a>'
        if ch['num'] == current_num and local_toc_content:
            html += f'<ul class="local-toc" style="display:block;">{local_toc_content}</ul>'
        html += '</li>'
        
    html += '</ul>'
    return html

# -----------------------------------------------------------------------------
# 2.5. TABLE PROCESSING (A4: Booktabs style)
# -----------------------------------------------------------------------------
def process_tables_antigravity(html_content):
    """
    A4: Transforms generic HTML tables into 'Book-Native' responsive components.
    Features:
    1. Wraps tables in <div class="table-wrapper"> for scrolling.
    2. Adds 'book-table' class.
    3. Elevates captions to the top if they are buried.
    Idempotent: per-table check - skips tables already inside table-wrapper.
    """
    try:
        from bs4 import BeautifulSoup
        import re as regex  # Local import to avoid closure issues
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # D3: Capture captions BEFORE processing for comparison
        captions_before = [cap.get_text(strip=True) for cap in soup.find_all('caption')]
        
        tables_wrapped = 0
        for table in soup.find_all('table'):
            # Skip tables that are nested inside another table cell (will be flattened separately)
            if table.find_parent('td') or table.find_parent('th'):
                continue

            # Safety check - table must still exist
            if not table or not table.name:
                continue
            
            # CLEANING: Remove \m@th and \mathchar artifacts from table cells
            for cell in table.find_all(['td', 'th']):
                if cell.string:
                    cell.string = cell.string.replace(r'\m@th', '').replace(r'@th', 'th')
                    cell.string = regex.sub(r'\\mathchar\d+', '', cell.string)

            already_wrapped = table.find_parent(class_='table-wrapper') is not None
            
            # 1) Add book-table class
            # 1) Add book-table class - Ensure it's robust
            existing_class = table.get('class', [])
            if isinstance(existing_class, str):
                existing_class = [existing_class]
            if 'book-table' not in existing_class:
                table['class'] = existing_class + ['book-table']
            
            # 1.5) CRITICAL: Strip ALL make4ht inline styles and IDs from cells
            # make4ht generates inline styles on EVERY cell - strip them ALL
            for cell in table.find_all(['td', 'th']):
                # Remove ALL style attributes to let our CSS control rendering
                if cell.get('style'):
                    del cell['style']
                # Remove make4ht-generated IDs (TBL-X-Y pattern)
                cell_id = cell.get('id', '')
                if cell_id.startswith('TBL-') or (cell_id and regex.match(r'^TBL-\d+-\d+', cell_id)):
                    del cell['id']
            
            # 1.6) Remove cmidrule spans - they create broken partial horizontal rules
            for cmidrule in table.find_all('span', class_='cmidrule'):
                cmidrule.decompose()
            
            # 1.65) Fix colgroup positioning - move to start of table (before thead/tbody)
            # Colgroups must come before thead, but make4ht sometimes puts them after
            colgroups = table.find_all('colgroup')
            if colgroups:
                # Get first child that's not a colgroup
                first_non_colgroup = None
                for child in table.children:
                    if child.name and child.name != 'colgroup':
                        first_non_colgroup = child
                        break

                # Move all colgroups before first non-colgroup element
                if first_non_colgroup:
                    for colgroup in colgroups:
                        colgroup.extract()  # Remove from current position
                        first_non_colgroup.insert_before(colgroup)  # Insert before thead/tbody

            # 1.7) Remove empty rows (often created by cmidrule conversion) and hline rows
            # Collect rows to remove first (don't modify while iterating)
            rows_to_remove = []
            for row in table.find_all('tr'):
                # Remove rows with class="hline" (these are empty horizontal rule rows from booktabs)
                if row.get('class') and 'hline' in row.get('class'):
                    rows_to_remove.append(row)
                    continue

                # Check if row has no visible text content
                cells = row.find_all(['td', 'th'])
                if cells and all(not c.get_text(strip=True) for c in cells):
                    # Only remove if it's purely empty (no colspan spans either)
                    if not row.find(class_='multicolumn'):
                        rows_to_remove.append(row)

            # Now remove all collected rows
            for row in rows_to_remove:
                row.decompose()
            
            # 1.75) FLATTEN NESTED TABLES: Convert nested tables in cells to stacked text
            # This fixes tables like Swin Variants where multirow cells become nested tables
            for cell in table.find_all(['td', 'th']):
                nested_tables = cell.find_all('table', recursive=False)
                # Also check inside .tabular divs
                tabular_divs = cell.find_all('div', class_='tabular', recursive=False)
                for tabular_div in tabular_divs:
                    nested_tables.extend(tabular_div.find_all('table'))
                
                if nested_tables:
                    # Extract text from each row of nested table and stack them
                    stacked_lines = []
                    for nested in nested_tables:
                        for nested_row in nested.find_all('tr'):
                            # Heuristic: If a nested row has multiple cells (>2), it's likely a structural table 
                            # (like a misplaced header) and not just stacked lines of text. Skip it.
                            nested_cells = nested_row.find_all(['td', 'th'])
                            if len(nested_cells) > 2:
                                continue
                                
                            # Join with spaces to prevent "StageDownsample" concatenation
                            row_text = " ".join(c.get_text(strip=True) for c in nested_cells).strip()
                            if row_text:
                                stacked_lines.append(row_text)
                        nested.decompose()
                    
                    # Remove remaining tabular wrapper divs
                    for tabular_div in cell.find_all('div', class_='tabular'):
                        tabular_div.decompose()
                    for wrapper_div in cell.find_all('div', class_='table-wrapper'):
                        wrapper_div.decompose()
                    
                    # Create stacked content with line breaks
                    if stacked_lines:
                        cell.clear()
                        for i, line in enumerate(stacked_lines):
                            cell.append(soup.new_string(line))
                            if i < len(stacked_lines) - 1:
                                cell.append(soup.new_tag('br'))
                        cell_class = cell.get('class', [])
                        if 'stacked-cell' not in cell_class:
                            cell['class'] = cell_class + ['stacked-cell']
            
            # 1.77) FIX INCOMPLETE DIVIDERS (Category Rows like "Chairs", "Cars" in Ch23)
            # Detect rows with single cell that should span entire table
            # Calculate max columns in the table first
            max_cols = 0
            for row in table.find_all('tr'):
                col_count = 0
                for cell in row.find_all(['td', 'th']):
                    # Add colspan to count
                    colspan = int(cell.get('colspan', 1))
                    col_count += colspan
                max_cols = max(max_cols, col_count)
            
            if max_cols > 1:
                for row in table.find_all('tr'):
                    cells = row.find_all(['td', 'th'])
                    # If row has exactly 1 cell (and it's not the only column in table)
                    if len(cells) == 1:
                        cell = cells[0]
                        colspan = int(cell.get('colspan', 1))
                        # If meaningful text content exists (not just empty spacer)
                        text = cell.get_text(strip=True)
                        if text and colspan < max_cols:
                            # It's likely a category divider. Expand to full width.
                            cell['colspan'] = max_cols
                            # Ensure it has appropriate styling (bold, left align)
                            cell['style'] = cell.get('style', '') + '; text-align: left; font-weight: bold;'
                            # Add a class for cleaner styling control
                            existing_c = cell.get('class', [])
                            if 'category-divider' not in existing_c:
                                cell['class'] = existing_c + ['category-divider']
            
            # 1.76) SYNTHESIZE HEADER ROW for Swin Variants-like tables
            # Detect tables with Stage 1,2,3,4 rows and stacked cells but missing header
            # Remove any existing inferred headers if a real thead exists (for idempotency)
            thead = table.find('thead')
            existing_inferred = table.find('tr', class_='inferred-header')
            if thead and existing_inferred:
                existing_inferred.decompose()
                existing_inferred = None

            # Only create header if table doesn't already have a <thead> or inferred-header
            if not thead and not existing_inferred:
                rows = table.find_all('tr', recursive=False)
                if not rows:
                    tbody = table.find('tbody')
                    rows = tbody.find_all('tr', recursive=False) if tbody else []

                if rows:
                    first_row = rows[0]
                    first_row_text = first_row.get_text(strip=True)
                    # Check if first row contains "Stage 1" (indicates missing header)
                    if 'Stage 1' in first_row_text or 'Stage1' in first_row_text:
                        # Count stacked cells to determine number of model columns
                        stacked_cells = first_row.find_all('td', class_='stacked-cell')
                        if len(stacked_cells) >= 4:  # Swin-T, Swin-S, Swin-B, Swin-L
                            # Create synthetic header row
                            header_row = soup.new_tag('tr')
                            # Use thead class for styling
                            header_row['class'] = ['inferred-header']

                            # Determine header labels based on content
                            first_stacked = stacked_cells[0].get_text() if stacked_cells else ''
                            if 'dim' in first_stacked.lower():
                                # Swin Transformer pattern
                                headers = ['Stage', 'Downsample Rate', 'Swin-T', 'Swin-S', 'Swin-B', 'Swin-L']
                            else:
                                # Generic pattern
                                headers = ['Index', 'Scale']
                                headers += [f'Model {i+1}' for i in range(len(stacked_cells))]

                            for h_text in headers[:len(first_row.find_all(['td', 'th']))]:
                                th = soup.new_tag('th')
                                th['class'] = ['inferred-th']
                                th.string = h_text
                                header_row.append(th)

                            # Insert before first data row
                            first_row.insert_before(header_row)
            
            # 1.8) Fix corrupted characters from make4ht (UTF-8 encoding issues)
            # Common issue: > becomes ¿ or similar in table headers
            table_html = str(table)
            # Fix IoU¿ -> IoU> and similar patterns
            table_html = table_html.replace('IoU¿', 'IoU>')
            table_html = table_html.replace('¿', '>')  # General fix for > symbol
            table_html = table_html.replace('&amp;gt;', '>')  # Escaped HTML entities
            table_html = table_html.replace('&gt;', '>')
            # Fix corrupted numbers (e.g., "96296" -> "96", pattern: number followed by "296")
            table_html = regex.sub(r'\b(\d+)296\b', r'\1', table_html)
            # Rebuild table if changes were made
            if str(table) != table_html:
                new_table = BeautifulSoup(table_html, 'html.parser').find('table')
                if new_table:
                    table.replace_with(new_table)
                    table = new_table
            
            # 2) Extract caption if present (only for unwrapped tables)
            caption_html = ""
            if not already_wrapped:
                caption = table.find('caption')
                if caption:
                    raw_cap = caption.get_text(strip=True)
                    # Move caption outside table
                    caption.decompose()
                    # Format caption
                    import re
                    split_cap = re.match(r'(Table\s*[\d\.]+[:\.])\s*(.*)', raw_cap, re.IGNORECASE)
                    if split_cap:
                        caption_html = f'<div class="table-caption">{split_cap.group(1)}<span class="note">{split_cap.group(2)}</span></div>\n'
                    elif raw_cap:
                        caption_html = f'<div class="table-caption">{raw_cap}</div>\n'
            
            # 2.4) FIX MALFORMED MULTICOLUMN: move div.multicolumn content into preceding empty <th>
            # make4ht sometimes puts multicolumn content as sibling divs after empty th cells
            for mcol in table.find_all('div', class_='multicolumn'):
                # Find the preceding sibling cell (th or td) to absorb this content
                prev = mcol.find_previous_sibling(['th', 'td'])
                if prev and not prev.get_text(strip=True):
                    # Previous cell is empty - move multicolumn content into it
                    prev.append(mcol)
                else:
                    # Try parent's previous sibling
                    parent = mcol.parent
                    if parent and parent.name == 'tr':
                        # Find last empty th/td in this row
                        for cell in reversed(parent.find_all(['th', 'td'])):
                            if not cell.get_text(strip=True):
                                cell.append(mcol)
                                break
            
            # 2.45) AUTO-FIX COLSPAN MISMATCH: make4ht often outputs wrong colspan values
            # Calculate the actual total columns from data rows and fix header colspans
            # This fixes issues like Table 15.3 where colspan="2" should be colspan="4"
            tbody = table.find('tbody')
            data_rows = (tbody or table).find_all('tr', recursive=False)[1:] if not tbody else tbody.find_all('tr', recursive=False)
            if data_rows:
                # Find actual column count from a data row (rows without colspan)
                actual_cols = 0
                for row in data_rows:
                    cols = sum(int(c.get('colspan', 1)) for c in row.find_all(['td', 'th']))
                    if cols > actual_cols:
                        actual_cols = cols
                
                # Check header rows for colspan mismatches
                thead = table.find('thead')
                header_rows = thead.find_all('tr') if thead else []
                
                for row in header_rows:
                    cells = row.find_all(['th', 'td'])
                    row_cols = sum(int(c.get('colspan', 1)) for c in cells)
                    
                    # If row has fewer columns due to colspan, find the cell with colspan and fix it
                    if row_cols < actual_cols:
                        shortfall = actual_cols - row_cols
                        # Find the grouped header (cell with colspan > 1) and adjust it
                        for cell in cells:
                            colspan = int(cell.get('colspan', 1))
                            if colspan > 1:
                                # Increase this cell's colspan to account for missing columns
                                new_colspan = colspan + shortfall
                                cell['colspan'] = str(new_colspan)
                                break
            
            # 2.5) ROBUST MULTI-ROW HEADER RECONSTRUCTION
            # Score rows for "header-likeness" and move contiguous header block to <thead>
            # Criteria: presence of <th>, colspan/rowspan, bold spans (cmbx), unit rows like "(s)", low numeric density
            thead = table.find('thead')
            if thead:
                # Existing thead - ensure cells are <th> and mark group boundaries
                for cell in thead.find_all('td'):
                    cell.name = 'th'
                
                # Mark first cell of colspan groups with .group-start for vertical separator
                first_row = thead.find('tr')
                if first_row:
                    cells = first_row.find_all(['th', 'td'])
                    col_idx = 0
                    group_start_cols = []
                    for cell in cells:
                        colspan = int(cell.get('colspan', 1))
                        if col_idx > 0 and colspan > 1:
                            # This is a grouped header starting at col_idx
                            group_start_cols.append(col_idx)
                            # Also mark the spanning cell itself
                            existing_class = cell.get('class', [])
                            if isinstance(existing_class, str):
                                existing_class = [existing_class]
                            if 'group-start' not in existing_class:
                                cell['class'] = existing_class + ['group-start']
                            cell['style'] = 'border-left: 1.5px solid #000 !important;'
                        col_idx += colspan
                    
                    # Mark cells in ALL rows at group boundaries
                    if group_start_cols:
                        tbody = table.find('tbody')
                        all_rows = list(thead.find_all('tr')) + list((tbody or table).find_all('tr'))
                        for row in all_rows:
                            cells = row.find_all(['th', 'td'])
                            curr_col = 0
                            for cell in cells:
                                if curr_col in group_start_cols:
                                    existing_class = cell.get('class', [])
                                    if isinstance(existing_class, str):
                                        existing_class = [existing_class]
                                    if 'group-start' not in existing_class:
                                        cell['class'] = existing_class + ['group-start']
                                    # INLINE STYLE: highest CSS priority
                                    cell['style'] = 'border-left: 1.5px solid #000 !important;'
                                curr_col += int(cell.get('colspan', 1))
            else:
                # No thead - detect multi-row header block
                tbody = table.find('tbody')
                rows = tbody.find_all('tr', recursive=False) if tbody else table.find_all('tr', recursive=False)
                
                def score_row_for_header(row):
                    """Score a row for header-likeness. Higher = more likely header."""
                    score = 0
                    cells = row.find_all(['td', 'th'])
                    if not cells:
                        return -1
                    
                    # Has <th> elements
                    if row.find('th'):
                        score += 5
                    
                    # Has colspan (grouped headers)
                    for cell in cells:
                        if cell.get('colspan') and int(cell.get('colspan', 1)) > 1:
                            score += 3
                        if cell.get('rowspan') and int(cell.get('rowspan', 1)) > 1:
                            score += 2
                    
                    # Has bold spans (class contains 'cmbx')
                    bold_spans = row.find_all(class_=lambda c: c and ('cmbx' in str(c).lower() if isinstance(c, str) else any('cmbx' in str(x).lower() for x in c if x)))
                    if bold_spans:
                        score += 4
                    
                    # Contains unit indicators like "(s)", "(%)", "(ms)", etc.
                    row_text = row.get_text()
                    if regex.search(r'\([s%ms]\)', row_text, regex.IGNORECASE):
                        score += 3
                    
                    # Low numeric density (headers have more text, less pure numbers)
                    total_text = row_text.strip()
                    numeric_parts = regex.findall(r'\d+\.?\d*', total_text)
                    if len(total_text) > 0:
                        numeric_ratio = len(''.join(numeric_parts)) / len(total_text)
                        if numeric_ratio < 0.3:
                            score += 2
                    
                    return score
                
                # Find contiguous header block from top
                header_rows = []
                for row in rows[:5]:  # Check first 5 rows max
                    if score_row_for_header(row) >= 3:  # Threshold for header-likeness
                        header_rows.append(row)
                    else:
                        break  # Stop at first non-header row
                
                if header_rows:
                    # Create thead and move header rows
                    thead = soup.new_tag('thead')
                    for row in header_rows:
                        for cell in row.find_all('td'):
                            cell.name = 'th'
                        row_copy = row.extract()
                        thead.append(row_copy)
                    
                    # Insert at beginning (after colgroup if present)
                    colgroups = table.find_all('colgroup')
                    if colgroups:
                        colgroups[-1].insert_after(thead)
                    elif tbody:
                        tbody.insert_before(thead)
                    else:
                        table.insert(0, thead)
                    
                    # Mark column group boundaries for vertical separator styling
                    # Find cells with colspan > 1 and mark following columns as .group-start
                    if thead:
                        first_row = thead.find('tr')
                        if first_row:
                            cells = first_row.find_all(['th', 'td'])
                            col_idx = 0
                            group_start_cols = []
                            for cell in cells:
                                colspan = int(cell.get('colspan', 1))
                                if col_idx > 0 and colspan > 1:
                                    # This is a grouped header starting at col_idx
                                    group_start_cols.append(col_idx)
                                col_idx += colspan
                            
                            # Mark cells in second header row and body at group boundaries
                            if group_start_cols:
                                all_rows = list(thead.find_all('tr')) + list((tbody or table).find_all('tr'))
                                for row in all_rows:
                                    cells = row.find_all(['th', 'td'])
                                    curr_col = 0
                                    for cell in cells:
                                        if curr_col in group_start_cols:
                                            existing_class = cell.get('class', [])
                                            if isinstance(existing_class, str):
                                                existing_class = [existing_class]
                                            if 'group-start' not in existing_class:
                                                cell['class'] = existing_class + ['group-start']
                                            # INLINE STYLE: highest CSS priority, cannot be overridden
                                            cell['style'] = 'border-left: 1.5px solid #000 !important;'
                                        curr_col += int(cell.get('colspan', 1))
            
            # 3) Wrap table in table-wrapper div (only if not already wrapped)
            if not already_wrapped:
                wrapper = soup.new_tag('div')
                wrapper['class'] = ['table-wrapper']
                table.wrap(wrapper)
                
                # Insert caption before table in wrapper
                if caption_html:
                    caption_soup = BeautifulSoup(caption_html, 'html.parser')
                    wrapper.insert(0, caption_soup)
                
                tables_wrapped += 1
        
        # D3: Capture captions AFTER processing and compare
        result_soup = BeautifulSoup(str(soup), 'html.parser')
        captions_after = [cap.get_text(strip=True) for cap in result_soup.find_all('caption')]
        captions_after += [div.get_text(strip=True) for div in result_soup.find_all(class_='table-caption')]
        
        if captions_before and captions_before != captions_after[:len(captions_before)]:
            print(f"  D3 WARNING: Table captions may have changed during processing")
            print(f"    Before: {captions_before[:2]}")
            print(f"    After:  {captions_after[:2]}")
        
        return str(soup)
    
    except ImportError:
        # Fallback: regex-based (original logic, but per-table check)
        table_pattern = re.compile(r'(<table[^>]*>)(.*?)(</table>)', re.DOTALL | re.IGNORECASE)

        def replacer(match):
            full_match = match.group(0)
            # Skip if already wrapped (check surrounding context)
            start = max(0, match.start() - 50)
            prefix = html_content[start:match.start()]
            if 'table-wrapper' in prefix:
                return full_match
            
            open_tag = match.group(1)
            content = match.group(2)
            close_tag = match.group(3)

            # 1) Inject class
            if 'class="' in open_tag:
                open_tag = re.sub(r'class="([^"]*)"', r'class="\1 book-table"', open_tag)
            else:
                open_tag = open_tag.replace('<table', '<table class="book-table"')

            # 2) Extract caption
            caption_match = re.search(r'<caption[^>]*>(.*?)</caption>', content, re.DOTALL | re.IGNORECASE)
            caption_html = ""

            if caption_match:
                content = content.replace(caption_match.group(0), "")
                raw_cap = caption_match.group(1).strip()

                split_cap = re.match(r'(Table\s*[\d\.]+[:\.])\s*(.*)', raw_cap, re.IGNORECASE)
                if split_cap:
                    caption_html = f'<div class="table-caption">{split_cap.group(1)}<span class="note">{split_cap.group(2)}</span></div>'
                else:
                    caption_html = f'<div class="table-caption">{raw_cap}</div>'

            # 3) Wrap
            return f'<div class="table-wrapper">\n{caption_html}\n{open_tag}{content}{close_tag}\n</div>'

        return table_pattern.sub(replacer, html_content)

# -----------------------------------------------------------------------------
# 3. CONTENT EXTRACTION (TOC & Idempotency)
# -----------------------------------------------------------------------------

def extract_toc_from_body(body_html: str, lecture_num: int = 1) -> str:
    """
    Extract TOC with proper hierarchy using a two-pass algorithm:
    
    Pass 1: Collect all h3/h4 headings and identify enrichments
    Pass 2: Detect consecutive h3 enrichments and renumber them as subsections
    
    Rules:
    - H3 sectionHead = section (X.Y format)
    - H4 subsectionHead = subsection (X.Y.Z format) 
    - H3 enrichments: First in a consecutive group = section, rest = subsections
    - Skip h5 (subsubsections)
    """
    # Match h3, h4, and h5 headings with IDs
    matches = list(re.finditer(r'<(h[345])\b[^>]*(?:id=["\']([^"\']+)["\'])[^>]*>(.*?)</\1>', body_html, re.IGNORECASE | re.DOTALL))
    
    # Pass 1: Collect and classify all headings
    headings = []
    for m in matches:
        tag, eid, content = m.groups()
        tag = tag.lower()
        
        if not eid:
            continue
        
        # Extract text content
        text = re.sub(r'<[^>]+>', '', content).strip()
        text = restore_math(text)
        if not text:
            continue
        
        # Skip noise
        if re.search(r'Chapter\s*\d+', text, re.IGNORECASE):
            continue
        if re.match(r'^Lecture\s+\d+:', text, re.IGNORECASE):
            continue
        if tag == 'h5':  # Skip subsubsections
            continue
        
        # Rewrite 1.x -> N.x
        if lecture_num > 1:
            text = re.sub(r'^1\.', f'{lecture_num}.', text)
        
        # Check if enrichment
        enr_match = re.match(r'Enrichment\s+([\d.]+):?\s*(.*)', text, re.IGNORECASE)
        is_enrichment = bool(enr_match)
        enr_num = enr_match.group(1) if enr_match else None
        enr_title = enr_match.group(2).strip() if enr_match else None
        
        # Rewrite enrichment number 1.x -> N.x
        if enr_num and lecture_num > 1:
            enr_num = re.sub(r'^1\.', f'{lecture_num}.', enr_num)
        
        headings.append({
            'tag': tag,
            'eid': eid,
            'text': text,
            'is_enrichment': is_enrichment,
            'enr_num': enr_num,
            'enr_title': enr_title,
        })
    
    # Pass 2: Renumber consecutive h3 enrichments
    # Group them so first in group is section, rest are subsections
    i = 0
    while i < len(headings):
        h = headings[i]
        
        if h['is_enrichment'] and h['tag'] == 'h3':
            # Start of potential enrichment group
            # Find parent enrichment number (base for subsection numbering)
            parent_parts = h['enr_num'].split('.')
            parent_num = '.'.join(parent_parts[:2])  # Keep X.Y as parent
            
            # Check for following consecutive h3 enrichments
            j = i + 1
            subsection_counter = 1
            
            while j < len(headings) and headings[j]['tag'] == 'h3' and headings[j]['is_enrichment']:
                # This is a consecutive h3 enrichment - make it a subsection
                child = headings[j]
                corrected_num = f"{parent_num}.{subsection_counter}"
                child['display_text'] = f"{corrected_num} {child['enr_title']}"
                child['is_subsection'] = True
                subsection_counter += 1
                j += 1
            
            # First enrichment keeps its original number as section
            h['display_text'] = f"{parent_num} {h['enr_title']}"
            h['is_subsection'] = False
            
            # Advance past the group
            i = j
        else:
            # Not enrichment or h4 - process normally
            if h['is_enrichment']:
                h['display_text'] = f"{h['enr_num']} {h['enr_title']}"
            else:
                h['display_text'] = h['text']
            
            # Determine subsection status from tag and numbering
            if h['tag'] == 'h4':
                h['is_subsection'] = True
            else:
                num_match = re.match(r'^(\d+(?:\.\d+)*)', h['text'])
                if num_match:
                    parts = num_match.group(1).split('.')
                    h['is_subsection'] = len(parts) >= 3
                else:
                    h['is_subsection'] = False
            i += 1
    
    # Pass 3: Generate HTML with proper hierarchy
    html = ""
    current_parent_id = None
    
    for h in headings:
        text = h.get('display_text', h['text'])
        is_subsection = h.get('is_subsection', False)
        is_enrichment = h['is_enrichment']
        eid = h['eid']
        
        # Build link with emoji for enrichments
        if is_enrichment:
            link_html = f'<a href="#{eid}">{text}<span class="toc-emoji" aria-hidden="true">📘</span></a>'
        else:
            link_html = f'<a href="#{eid}">{text}</a>'
        
        if is_subsection:
            toc_class = 'toc-h4 toc-enrichment' if is_enrichment else 'toc-h4'
            if not current_parent_id:
                continue  # Skip orphan subsections
            html += f'<li class="{toc_class}">{link_html}</li>'
        else:
            toc_class = 'toc-h3 toc-enrichment' if is_enrichment else 'toc-h3'
            if current_parent_id:
                html += '</ul></li>'
            html += f'<li class="{toc_class}">{link_html}<ul class="toc-sub-list">'
            current_parent_id = eid
    
    if current_parent_id:
        html += '</ul></li>'
    
    return html


# -----------------------------------------------------------------------------
# 3.5. UNIFIED PAGE RENDERER - Single Source of Truth
# -----------------------------------------------------------------------------
def render_page_html(title: str, body_content: str, sidebar_html: str, nav_buttons_html: str, 
                     bottom_nav_html: str = "", extra_styles: str = "", is_aux: bool = False, body_class: str = "") -> str:
    """
    Unified page renderer - THE ONLY function that creates the HTML skeleton.
    Includes the Shared Layout: Sidebar, Sticky Top Bar, Floating Buttons (via JS), and Content Card.
    """
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    {get_common_head(title, is_aux=is_aux)}
    <style>{extra_styles}</style>
</head>
<body id="page-top-body" class="{body_class}">
    <aside class="sidebar" id="sidebar">
        {sidebar_html}
    </aside>
    <div class="resize-handle" id="sidebar_resizer"></div>
    <div class="main-wrapper">
        <header class="top-bar" id="topbar">
            <div id="menu_toggle" class="menu-toggle" style="display:none; cursor:pointer;">
                <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <line x1="3" y1="12" x2="21" y2="12"></line>
                    <line x1="3" y1="6" x2="21" y2="6"></line>
                    <line x1="3" y1="18" x2="21" y2="18"></line>
                </svg>
            </div>
            <div class="page-title">{title}</div>
            <div class="topbar-right">
                <!-- Pagefind Search UI (Expandable, expands LEFT from buttons) -->
                <div class="search-container expandable" id="top_search">
                    <div class="search-input-wrapper">
                        <input type="text" class="search-input pagefind-trigger" placeholder="Search..." data-active-placeholder="Search..." disabled>
                    </div>
                    <div class="search-trigger" id="search_trigger">
                        <i class="fas fa-search"></i>
                    </div>
                    <div class="search-results"></div>
                </div>
                {nav_buttons_html}
            </div>
        </header>
        <main class="content-scroll" id="content_area">
            <div class="container">
                <div class="card">
                    <div class="card-body" id="doc_content" data-pagefind-body>
                        <!-- content-start -->
                        {body_content}
                        <!-- content-end -->
                    </div>
                    {bottom_nav_html}
                </div>
            </div>
        </main>
    </div>
    {get_js_footer()}
</body>
</html>"""

# -----------------------------------------------------------------------------
# 3.6. CONTENT SAFETY VALIDATION (CRITICAL - Prevents Content Wiping)
# -----------------------------------------------------------------------------
def validate_output_safety(html_content: str, filename: str) -> tuple:
    """
    Validates that output HTML is safe to write (not empty/corrupted).
    Returns: (is_safe: bool, error_message: str)
    
    This is a CRITICAL guardrail to prevent the script from overwriting
    chapter files with empty or corrupted content.
    """
    # Check 1: Exactly one doc_content
    doc_content_count = html_content.count('id="doc_content"')
    if doc_content_count != 1:
        return False, f"Invalid doc_content count: {doc_content_count} (expected 1)"
    
    # Check 2: Extract content and verify length using content markers
    match = re.search(r'<!-- content-start -->(.*?)<!-- content-end -->', html_content, re.DOTALL)
    if not match:
        # Fallback: just check total HTML length as sanity check
        if len(html_content) < 5000:
            return False, f"Total HTML too short: {len(html_content)} chars"
        content = html_content  # Use full content for heading check
    else:
        content = match.group(1)
        content_len = len(content)
        if content_len < MIN_CONTENT_LENGTH:
            return False, f"Content too short: {content_len} chars (minimum {MIN_CONTENT_LENGTH})"
    
    # Check 3: Has at least one heading (h1 or h2)
    if not re.search(r'<h[12][^>]*>', content, re.IGNORECASE):
        return False, "No headings (h1/h2) found in content"
    
    # Check 4: No unrestored MATH_TOKEN_ placeholders
    if 'MATH_TOKEN_' in html_content:
        token_match = re.search(r'(MATH_TOKEN_\d+)', html_content)
        token_example = token_match.group(1) if token_match else "MATH_TOKEN_*"
        return False, f"Unrestored math placeholder found: {token_example}"
    
    # Check 5: Has exactly one sidebar
    sidebar_count = html_content.count('class="sidebar"')
    if sidebar_count != 1:
        return False, f"Invalid sidebar count: {sidebar_count} (expected 1)"
    
    # Check 6: Has exactly one top-bar
    topbar_count = html_content.count('class="top-bar"')
    if topbar_count != 1:
        return False, f"Invalid top-bar count: {topbar_count} (expected 1)"
    
    # All checks passed
    return True, ""

# -----------------------------------------------------------------------------
# 4. PROCESS CHAPTER
# -----------------------------------------------------------------------------
def process_chapter(html_file: Path, chapter_data: dict):
    print(f"Processing {html_file.name}...")
    original_content = html_file.read_text(encoding='utf-8', errors='replace')
    
    # --- Issue 5: ROBUST IDEMPOTENCY WITH CHROME STRIPPING ---
    doc_content = ""
    if '<!-- content-start -->' in original_content:
        # Already wrapped! Extract inner content to re-wrap.
        m = re.search(r'<!-- content-start -->(.*?)<!-- content-end -->', original_content, re.DOTALL)
        if m:
            print(f"  Re-wrapping content in {html_file.name}")
            doc_content = m.group(1)
        else:
            doc_content = original_content
    elif 'id="doc_content"' in original_content:
        # Fallback: extract from doc_content div using BeautifulSoup for robustness
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(original_content, 'html.parser')
            doc_div = soup.find(id='doc_content')
            if doc_div:
                doc_content = str(doc_div.decode_contents())
            else:
                # Fallback to body
                m_body = re.search(r'<body[^>]*>(.*?)</body>', original_content, re.DOTALL | re.IGNORECASE)
                doc_content = m_body.group(1) if m_body else original_content
        except ImportError:
            # BeautifulSoup not available, use regex
            m_body = re.search(r'<body[^>]*>(.*?)</body>', original_content, re.DOTALL | re.IGNORECASE)
            doc_content = m_body.group(1) if m_body else original_content
    else:
        # Raw make4ht output
        m_body = re.search(r'<body[^>]*>(.*?)</body>', original_content, re.DOTALL | re.IGNORECASE)
        doc_content = m_body.group(1) if m_body else original_content

    # Clean old artifacts
    doc_content = re.sub(r'<div class="crosslinks">.*?</div>', '', doc_content, flags=re.DOTALL)
    
    # Issue 5: Strip any nested chrome elements using BeautifulSoup
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(doc_content, 'html.parser')
        # Remove nested chrome elements that shouldn't be in content
        for selector in ['.sidebar', '.top-bar', '.main-wrapper', '.content-scroll', '.nav-btns', '.float-nav']:
            for elem in soup.select(selector):
                elem.decompose()
        # Remove all script tags from content (JS injected once via footer)
        for script in soup.find_all('script'):
            script.decompose()
        # Remove nested doc_content divs (keep only innermost content)
        doc_divs = soup.find_all(id='doc_content')
        if len(doc_divs) > 0:
            # Extract from innermost
            doc_content = str(doc_divs[-1].decode_contents()) if doc_divs else str(soup)
        else:
            doc_content = str(soup)
    except ImportError:
        # BeautifulSoup not available, use regex fallback
        pass
    
    # FIX 1: AGGRESSIVE UNWRAP - Strip nested card/container wrappers using string ops
    # Loop 10 times (safety limit) to strip all nested wrappers
    unwanted_starts = [
        '<div class="card"', '<div class="container"', '<div class="content-scroll"',
        '<div class="card-body"', "<div class='card'", "<div class='container'",
        "<div class='content-scroll'", "<div class='card-body'"
    ]
    for _ in range(10):
        content_stripped = doc_content.strip()
        found_wrapper = False
        for start_tag in unwanted_starts:
            if content_stripped.lower().startswith(start_tag.lower()):
                # Find the first ">" (end of opening tag)
                first_gt = content_stripped.find('>')
                if first_gt == -1:
                    break
                # Find the LAST "</div>"
                last_div = content_stripped.rfind('</div>')
                if last_div == -1 or last_div <= first_gt:
                    break
                # Extract the substring between them
                doc_content = content_stripped[first_gt + 1:last_div].strip()
                found_wrapper = True
                break
        if not found_wrapper:
            break  # No more wrappers
    
    # Issue 2: Remove empty whitespace elements (empty p, div with only whitespace/nbsp)
    # Using BeautifulSoup for safe DOM manipulation
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(doc_content, 'html.parser')
        
        # Remove truly empty paragraphs
        for p in soup.find_all('p'):
            # Get text content, considering &nbsp;
            text = p.get_text(strip=True).replace('\xa0', '').replace('&nbsp;', '')
            # Check if it contains only whitespace and no meaningful children
            has_children = p.find_all(['img', 'a', 'span', 'math', 'svg', 'table', 'figure'])
            if not text and not has_children:
                # Check for data-bearing attributes
                if not p.get('id'):
                    p.decompose()
        
        # Remove empty divs that are layout wrappers (minipage, parbox, etc)
        for div in soup.find_all('div', class_=re.compile(r'minipage|parbox|center')):
            text = div.get_text(strip=True).replace('\xa0', '').replace('&nbsp;', '')
            has_children = div.find_all(['img', 'a', 'math', 'svg', 'table', 'figure', 'pre', 'code'])
            if not text and not has_children:
                div.decompose()
        
        doc_content = str(soup)
    except ImportError:
        pass  # BeautifulSoup not available, skip this cleanup
    
    # 0a. Handle \bordermatrix - this LaTeX command doesn't work in MathJax
    # Just remove the \bordermatrix command and replace with placeholder text
    # The nested braces make this too complex to convert reliably
    # Instead, we'll rely on the MathJax macro fallback which shows [Matrix]
    pass  # bordermatrix handled by MathJax macro definition
    
    # 0b. Sanitize LaTeX commands in math content BEFORE protection
    # Fix \textsc {Word} -> \textsc{Word} (remove space before brace)
    doc_content = re.sub(r'\\textsc\s+\{', r'\\textsc{', doc_content)
    doc_content = re.sub(r'\\texttt\s+\{', r'\\texttt{', doc_content)
    doc_content = re.sub(r'\\textrm\s+\{', r'\\textrm{', doc_content)
    doc_content = re.sub(r'\\mbox\s+\{', r'\\mbox{', doc_content)

    # Fix LaTeX compilation errors/typos that MathJax can't handle
    # \boldsymbolod -> \bmod (typo in source)
    doc_content = re.sub(r'\\boldsymbolod\b', r'\\bmod', doc_content)
    # \hdots -> \cdots (proper MathJax command)
    doc_content = re.sub(r'\\hdots\b', r'\\cdots', doc_content)
    # \rotatebox[origin=c]{90}{$\subset$} -> \subset (simplify rotation)
    doc_content = re.sub(r'\\rotatebox\s*\[[^\]]*\]\s*\{[^}]*\}\s*\{\s*\$?\\subset\$?\s*\}', r'\\subset', doc_content)
    
    # Fix escaped underscores inside text commands: \mbox{norm\_const} -> \mbox{norm_const}
    # This makes the underscore render properly in MathJax text mode
    def fix_escaped_underscores_in_text(m):
        cmd = m.group(1)  # mbox, text, texttt, etc.
        content = m.group(2)  # content inside braces
        # Replace \_ with _ inside the text command
        content = content.replace(r'\_', '_')
        return f'\\{cmd}{{{content}}}'
    
    # Apply to common text commands in math
    doc_content = re.sub(r'\\(mbox|text|texttt|textrm|textsc|textsf|mathrm)\{([^}]+)\}', 
                         fix_escaped_underscores_in_text, doc_content)
    
    # Convert \textsc{Word} to \text{Word} for MathJax compatibility (inside math spans)
    # This is safer than relying on MathJax macros
    def fix_textsc_in_math(m):
        content = m.group(0)
        # Replace \textsc{...} with \text{...} (MathJax-compatible)
        content = re.sub(r'\\textsc\{([^}]+)\}', r'\\text{\\small \\textsf{\1}}', content)
        return content
    
    # Apply to math spans
    doc_content = re.sub(r'<span class="mathjax-inline">[^<]+</span>', fix_textsc_in_math, doc_content)
    doc_content = re.sub(r'<div class="mathjax-[^"]*">[^<]+</div>', fix_textsc_in_math, doc_content)
    
    # 0. Protect Math
    doc_content = protect_math(doc_content)

    # 0.5. Generate READABLE anchor IDs for all headings
    # Replace cryptic TeX4ht IDs like "x1-36000" with meaningful slugs like "training-rpns"
    # This improves SEO and makes URLs shareable/understandable
    used_ids = set()
    old_to_new_id_map = {}  # Track ID changes for updating internal links

    def clean_text_for_slug(text):
        """Clean text for generating URL-friendly slugs"""
        # Remove HTML tags first
        text = re.sub(r'<[^>]+>', '', text).strip()
        # Remove section numbers like "14.3.1" at the start
        text = re.sub(r'^\d+(\.\d+)*\s*', '', text).strip()
        # Remove ALL math-related tokens and placeholders (various formats)
        text = re.sub(r'MATH_TOKEN_\d+__', '', text, flags=re.IGNORECASE)  # protect_math format
        text = re.sub(r'MATHPROTECT_\d+', '', text, flags=re.IGNORECASE)
        text = re.sub(r'math-token-\d+', '', text, flags=re.IGNORECASE)  # slug format
        text = re.sub(r'math_token_\d+', '', text, flags=re.IGNORECASE)
        text = re.sub(r'\$[^$]*\$', '', text)  # Remove inline LaTeX $...$
        text = re.sub(r'\\[a-zA-Z]+\{[^}]*\}', '', text)  # Remove LaTeX commands like \textbf{...}
        text = re.sub(r'\\[a-zA-Z]+', '', text)  # Remove standalone LaTeX commands like \alpha
        # Clean up resulting text - collapse multiple spaces
        text = re.sub(r'\s+', ' ', text).strip()
        return text

    def generate_slug(text, used_ids_set):
        """Generate a unique, readable slug from text"""
        text = clean_text_for_slug(text)
        # Generate slug from cleaned text
        slug = re.sub(r'[^a-zA-Z0-9]+', '-', text).strip('-').lower()
        # Remove any remaining empty dashes
        slug = re.sub(r'-+', '-', slug)
        # Limit length but try to keep it meaningful
        if len(slug) > 60:
            # Cut at word boundary
            slug = slug[:60].rsplit('-', 1)[0]

        if not slug or slug == '-':
            slug = "section"

        # Ensure uniqueness by appending counter for duplicates
        base_slug = slug
        counter = 2  # Start at 2 so first duplicate becomes "slug-2"
        while slug in used_ids_set:
            slug = f"{base_slug}-{counter}"
            counter += 1
        used_ids_set.add(slug)
        return slug

    def generate_readable_id(m):
        tag = m.group(1)  # h1, h2, h3, etc.
        attrs = m.group(2)
        content = m.group(3)

        slug = generate_slug(content, used_ids)

        # Check if there's an existing ID to map
        old_id_match = re.search(r'id=["\']([^"\']+)["\']', attrs)
        if old_id_match:
            old_id = old_id_match.group(1)
            old_to_new_id_map[old_id] = slug
            # Replace the old ID with the new readable one
            attrs = re.sub(r'id=["\'][^"\']+["\']', f'id="{slug}"', attrs)
            return f'<{tag}{attrs}>{content}</{tag}>'
        else:
            # No existing ID, add one
            return f'<{tag} id="{slug}"{attrs}>{content}</{tag}>'

    doc_content = re.sub(r'<(h[1-6])([^>]*)>(.*?)</\1>', generate_readable_id, doc_content, flags=re.DOTALL)

    # Also process sectionHead, subsectionHead etc. classes (TeX4ht generates these)
    def generate_readable_id_span(m):
        tag = m.group(1)
        attrs = m.group(2)
        content = m.group(3)

        slug = generate_slug(content, used_ids)

        old_id_match = re.search(r'id=["\']([^"\']+)["\']', attrs)
        if old_id_match:
            old_id = old_id_match.group(1)
            old_to_new_id_map[old_id] = slug
            attrs = re.sub(r'id=["\'][^"\']+["\']', f'id="{slug}"', attrs)
            return f'<{tag}{attrs}>{content}</{tag}>'
        else:
            return f'<{tag} id="{slug}"{attrs}>{content}</{tag}>'

    # Process span/div elements with section-like classes
    doc_content = re.sub(
        r'<(span|div)([^>]*class="[^"]*(?:sectionHead|subsectionHead|subsubsectionHead|paragraphHead)[^"]*"[^>]*)>(.*?)</\1>',
        generate_readable_id_span, doc_content, flags=re.DOTALL
    )

    # Update internal links to use new IDs
    def update_internal_link(m):
        href = m.group(1)
        if href.startswith('#'):
            old_id = href[1:]
            if old_id in old_to_new_id_map:
                return f'href="#{old_to_new_id_map[old_id]}"'
        return m.group(0)

    doc_content = re.sub(r'href="(#[^"]+)"', update_internal_link, doc_content)

    # 6. Fix Images (Size, Attrs, Lazy)
    def img_repl(m):
        raw = m.group(0)
        # Strip width/height/style
        clean = re.sub(r'\s(width|height|style)=["\'][^"\']*["\']', '', raw)
        clean = re.sub(r'/?>$', '', clean)
        # Add keys
        if 'loading=' not in clean: clean += ' loading="lazy" decoding="async"'
        return clean + ' />'
    doc_content = re.sub(r'<img\s+[^>]+>', img_repl, doc_content)

    # FIX INTRA-CHAPTER EQUATION REFERENCES
    # Extract equation labels from MathJax blocks and build a label->number map
    # Then replace broken Eq. (??) refs with proper equation numbers
    chapter_num = chapter_data['num']
    eq_label_map = {}
    eq_label_order = []  # Track order of labels for sequential numbering

    # First, get equation numbers from tex4ht comments (these are authoritative)
    # Pattern: >20.41<!-- tex4ht:ref: eq:chapter20_xxx -->
    for match in re.finditer(r'>(\d+\.\d+)<!-- tex4ht:ref:\s*(eq:chapter\d+_[^>]+)\s*-->', doc_content):
        eq_num = match.group(1)
        label = match.group(2).strip()
        eq_label_map[label] = eq_num

    # Find all equation labels in MathJax blocks (in document order)
    all_labels_in_doc = re.findall(r'label\s*\{(eq:chapter' + str(chapter_num) + r'_[^}]+)\}', doc_content)

    # For labels without tex4ht numbers, infer from position
    # tex4ht numbers some equations but skips others in align environments
    if all_labels_in_doc:
        # Find the highest equation number from tex4ht
        max_eq_num = 0
        for label, num_str in eq_label_map.items():
            try:
                num = int(num_str.split('.')[1])
                if num > max_eq_num:
                    max_eq_num = num
            except:
                pass

        # Count how many labels are missing numbers
        missing_count = sum(1 for label in all_labels_in_doc if label not in eq_label_map)

        if missing_count > 0:
            # Assign sequential numbers to missing labels based on their position
            # relative to labeled equations
            current_eq = 1
            for label in all_labels_in_doc:
                if label in eq_label_map:
                    # Use the existing number
                    try:
                        current_eq = int(eq_label_map[label].split('.')[1]) + 1
                    except:
                        current_eq += 1
                else:
                    # Assign the next number
                    eq_label_map[label] = f'{chapter_num}.{current_eq}'
                    current_eq += 1

    if eq_label_map:
        print(f"  [Eq Labels] Found {len(eq_label_map)} equation labels in chapter {chapter_num}")

    # Fix broken LaTeX cross-references (§?? patterns, cmbx-wrapped ??, and already-converted [§] patterns)
    # These are unresolved cross-chapter \ref commands. Try to provide useful info.
    # Known cross-chapter references with their targets:
    KNOWN_CROSS_REFS = {
        # === Transposed Convolution / Deconvolution (Chapter 15) ===
        'transpose-convolution': ('Chapter_15_Lecture_15_Image_Segmentation.html#bridging-to-transposed-convolution', '§15.2'),
        'transposed_convolution': ('Chapter_15_Lecture_15_Image_Segmentation.html#bridging-to-transposed-convolution', '§15.2'),
        'transposed convolution': ('Chapter_15_Lecture_15_Image_Segmentation.html#bridging-to-transposed-convolution', '§15.2'),
        'deconvolution': ('Chapter_15_Lecture_15_Image_Segmentation.html#bridging-to-transposed-convolution', '§15.2'),
        
        # === U-Net / Segmentation (Chapter 15) ===
        'u-net': ('Chapter_15_Lecture_15_Image_Segmentation.html#enrichment-unet-architecture-for-image-segmentation', '§15.6'),
        'unet': ('Chapter_15_Lecture_15_Image_Segmentation.html#enrichment-unet-architecture-for-image-segmentation', '§15.6'),
        'encoder-decoder': ('Chapter_15_Lecture_15_Image_Segmentation.html#enrichment-unet-architecture-for-image-segmentation', '§15.6'),
        'skip connection': ('Chapter_15_Lecture_15_Image_Segmentation.html#enrichment-unet-architecture-for-image-segmentation', '§15.6'),
        'biomedical': ('Chapter_15_Lecture_15_Image_Segmentation.html#enrichment-unet-architecture-for-image-segmentation', '§15.6'),
        'segmentation task': ('Chapter_15_Lecture_15_Image_Segmentation.html', '§15'),
        
        # === Chapter links ===
        'chapter7': ('Chapter_7_Lecture_7_Convolutional_Networks.html', 'Lecture 7'),
        'chapter15': ('Chapter_15_Lecture_15_Image_Segmentation.html', 'Lecture 15'),
        'chapter 19': ('Chapter_19_Lecture_19_Generative_Models_I.html', 'Lecture 19'),
        
        # === LoRA / PEFT (Chapter 10) ===
        'lora': ('Chapter_10_Lecture_10_Training_Neural_Networks_II.html', '§10'),
        'peft': ('Chapter_10_Lecture_10_Training_Neural_Networks_II.html', '§10'),
        
        # === CLIP / Self-Supervised Learning (Chapter 22) ===
        'clip': ('Chapter_22_Lecture_22_SelfSupervised_Learning.html', '§22'),
        'infonce': ('Chapter_22_Lecture_22_SelfSupervised_Learning.html', '§22'),
        
        # === Diffusion (Chapter 20) ===
        'diffusion': ('Chapter_20_Lecture_20_Generative_Models_II.html', '§20'),
        'classifier-free': ('Chapter_20_Lecture_20_Generative_Models_II.html', '§20'),
        'guidance': ('Chapter_20_Lecture_20_Generative_Models_II.html', '§20'),
        
        # === SVMs / Hinge Loss (Chapter 3) ===
        'svm': ('Chapter_3_Lecture_3_Linear_Classifiers.html#multiclass-svm-loss', '§3.6.4'),
        'svms': ('Chapter_3_Lecture_3_Linear_Classifiers.html#multiclass-svm-loss', '§3.6.4'),
        'hinge loss': ('Chapter_3_Lecture_3_Linear_Classifiers.html#multiclass-svm-loss', '§3.6.4'),
        'margin-based': ('Chapter_3_Lecture_3_Linear_Classifiers.html#multiclass-svm-loss', '§3.6.4'),
        
        # === Normalization Layers (Chapter 7) ===
        'batch normalization': ('Chapter_7_Lecture_7_Convolutional_Networks.html#batch-normalization', '§7.14'),
        'batchnorm': ('Chapter_7_Lecture_7_Convolutional_Networks.html#batch-normalization', '§7.14'),
        'instance normalization': ('Chapter_7_Lecture_7_Convolutional_Networks.html#alternative-normalization-methods-ln-in-gn-', '§7.14.6'),
        'layer normalization': ('Chapter_7_Lecture_7_Convolutional_Networks.html#alternative-normalization-methods-ln-in-gn-', '§7.14.6'),
        'group normalization': ('Chapter_7_Lecture_7_Convolutional_Networks.html#alternative-normalization-methods-ln-in-gn-', '§7.14.6'),
        
        # === Latent Spaces / Manifold (Chapter 19) ===
        'latent space': ('Chapter_19_Lecture_19_Generative_Models_I.html', '§19'),
        'manifold hypothesis': ('Chapter_19_Lecture_19_Generative_Models_I.html', '§19'),
        'manifold': ('Chapter_19_Lecture_19_Generative_Models_I.html', '§19'),
        'latent variable': ('Chapter_19_Lecture_19_Generative_Models_I.html', '§19'),
        
        # === Transformers / Attention (Chapter 17) ===
        'positional encoding': ('Chapter_17_Lecture_17_Attention.html#positional-encoding', '§17.4'),
        'positional embed': ('Chapter_17_Lecture_17_Attention.html#positional-encoding', '§17.4'),
        'sinusoidal': ('Chapter_17_Lecture_17_Attention.html#positional-encoding', '§17.4'),
        'transformer architecture': ('Chapter_17_Lecture_17_Attention.html', '§17'),
        'self-attention': ('Chapter_17_Lecture_17_Attention.html', '§17'),
        
        # === Vision Transformers (Chapter 18) ===
        'vit': ('Chapter_18_Lecture_18_Vision_Transformers.html', '§18'),
        'vision transformer': ('Chapter_18_Lecture_18_Vision_Transformers.html', '§18'),
        'patch embedding': ('Chapter_18_Lecture_18_Vision_Transformers.html', '§18'),
        'vits tokenize': ('Chapter_18_Lecture_18_Vision_Transformers.html', '§18'),
        
        # === Model Evaluation / FID (Chapter 21) ===
        'fid': ('Chapter_21_Lecture_21_Visualizing_Models__Generating_Images.html', '§21'),
        'fréchet': ('Chapter_21_Lecture_21_Visualizing_Models__Generating_Images.html', '§21'),
        'frechet': ('Chapter_21_Lecture_21_Visualizing_Models__Generating_Images.html', '§21'),
        'inception distance': ('Chapter_21_Lecture_21_Visualizing_Models__Generating_Images.html', '§21'),
        'inception score': ('Chapter_21_Lecture_21_Visualizing_Models__Generating_Images.html', '§21'),
        
        # === GANs / Generative Models ===
        'gan': ('Chapter_20_Lecture_20_Generative_Models_II.html#generative-adversarial-networks-gans', '§20.4'),
        'generator': ('Chapter_20_Lecture_20_Generative_Models_II.html#generative-adversarial-networks-gans', '§20.4'),
        'discriminator': ('Chapter_20_Lecture_20_Generative_Models_II.html#generative-adversarial-networks-gans', '§20.4'),
        
        # === Autoencoders / VAEs (Chapter 19-20) ===
        'autoencoder': ('Chapter_19_Lecture_19_Generative_Models_I.html', '§19'),
        'vae': ('Chapter_19_Lecture_19_Generative_Models_I.html', '§19'),
        'variational': ('Chapter_19_Lecture_19_Generative_Models_I.html', '§19'),
        'elbo': ('Chapter_19_Lecture_19_Generative_Models_I.html', '§19'),
        
        # === ResNets (Chapter 8) ===
        'resnet': ('Chapter_8_Lecture_8_CNN_Architectures_I.html#the-rise-of-residual-networks-resnets', '§8.5'),
        'residual network': ('Chapter_8_Lecture_8_CNN_Architectures_I.html#the-rise-of-residual-networks-resnets', '§8.5'),
        'residual connection': ('Chapter_8_Lecture_8_CNN_Architectures_I.html#the-rise-of-residual-networks-resnets', '§8.5'),
        'skip connection': ('Chapter_8_Lecture_8_CNN_Architectures_I.html#the-rise-of-residual-networks-resnets', '§8.5'),
        
        # === Backpropagation (Chapter 6) ===
        'backpropagation': ('Chapter_6_Lecture_6_Backpropagation.html', '§6'),
        'backprop': ('Chapter_6_Lecture_6_Backpropagation.html', '§6'),
        'computational graph': ('Chapter_6_Lecture_6_Backpropagation.html', '§6'),
        
        # === Object Detection (Chapter 13-14) ===
        'object detection': ('Chapter_13_Lecture_13_Object_Detection.html', '§13'),
        'r-cnn': ('Chapter_14_Lecture_14_Object_Detectors.html', '§14'),
        'faster r-cnn': ('Chapter_14_Lecture_14_Object_Detectors.html', '§14'),
        'yolo': ('Chapter_14_Lecture_14_Object_Detectors.html', '§14'),
    }
    
    def fix_broken_ref_from_context(match):
        """Replace broken ref with a link if context suggests a known target"""
        full_text = match.group(0)
        start_pos = match.start()
        # Look for context clues in surrounding text (wider range)
        context = doc_content[max(0, start_pos-300):start_pos+100].lower()
        
        # Check for known references
        for key, (href, display) in KNOWN_CROSS_REFS.items():
            if key in context:
                return f'<a href="{href}" class="cross-ref">{display}</a>'
        
        # Fallback: style as unavailable reference  
        return '<span class="broken-ref" title="Cross-reference to another chapter">[ref]</span>'
    
    # Handle spanned version: <span>§</span><span>??</span>
    doc_content = re.sub(r'<span[^>]*>§</span>\s*<span[^>]*>\?\?</span>', fix_broken_ref_from_context, doc_content)
    # Handle plain version: §??
    doc_content = re.sub(r'§\s*\?\?', fix_broken_ref_from_context, doc_content)
    # Handle ALREADY CONVERTED versions from previous runs: [§] or <span class="broken-ref"...>[§]</span>
    doc_content = re.sub(r'<span[^>]*class="broken-ref"[^>]*>\[§\]</span>', fix_broken_ref_from_context, doc_content)
    doc_content = re.sub(r'<span[^>]*class="broken-ref"[^>]*>\[ref\]</span>', fix_broken_ref_from_context, doc_content)
    
    # Handle equation references: Eq. (??) or Equation (??) with span-wrapped ??
    # Try to resolve these using the eq_label_map we built earlier
    # Note: Using [\s\xa0] to also match non-breaking spaces (U+00A0) from LaTeX
    NBSP = '\xa0'  # Non-breaking space
    WS = r'[\s' + NBSP + r']'  # Matches whitespace OR non-breaking space

    # Track equation reference resolution stats
    eq_ref_stats = {'total': 0, 'resolved': 0}

    def resolve_eq_ref(match):
        """Try to resolve equation reference using context and eq_label_map"""
        eq_ref_stats['total'] += 1
        prefix = match.group(1)  # "Eq." or "Equation"
        start_pos = match.start()

        # Look for equation label references in surrounding LaTeX source
        # Search backwards in the original content for \eqref{...} patterns
        # that might indicate which equation this refers to
        context_before = doc_content[max(0, start_pos-500):start_pos]
        context_after = doc_content[start_pos:min(len(doc_content), start_pos+200)]

        # Look for context clues - equation labels mentioned nearby
        # Check if there's text like "importance_identity" or "elbo" in context
        for label, eq_num in eq_label_map.items():
            # Extract the short name from the label (e.g., "importance_identity" from "eq:chapter20_importance_identity")
            short_name = label.split('_', 2)[-1] if '_' in label else label
            # Check if this label's name appears in the surrounding context
            combined_context = (context_before + context_after).lower()
            if short_name.lower() in combined_context:
                eq_ref_stats['resolved'] += 1
                return f'{prefix} ({eq_num})'

        # Fallback: style as unresolved
        return f'{prefix} <span class="broken-ref" title="Equation reference not resolved">(??)</span>'

    # Apply resolution to equation references
    doc_content = re.sub(
        r'(Eq\.|Equation)' + WS + r'*\(' + WS + r'*<span[^>]*>\?\?</span>' + WS + r'*\)',
        resolve_eq_ref,
        doc_content, flags=re.IGNORECASE
    )
    # Handle plain version without spans
    doc_content = re.sub(
        r'(Eq\.|Equation)' + WS + r'*\(' + WS + r'*\?\?' + WS + r'*\)',
        resolve_eq_ref,
        doc_content, flags=re.IGNORECASE
    )
    # Handle equation references without parentheses: Eq. <span>??</span>
    doc_content = re.sub(
        r'(Eq\.)' + WS + r'+<span[^>]*class="[^"]*cmbx[^"]*"[^>]*>\?\?</span>',
        resolve_eq_ref,
        doc_content, flags=re.IGNORECASE
    )

    # Also handle already-converted broken-ref patterns from previous runs
    doc_content = re.sub(
        r'(Eq\.|Equation)' + WS + r'*<span[^>]*class="broken-ref"[^>]*>\(\?\?\)</span>',
        resolve_eq_ref,
        doc_content, flags=re.IGNORECASE
    )

    if eq_ref_stats['total'] > 0:
        print(f"  [Eq Refs] Resolved {eq_ref_stats['resolved']}/{eq_ref_stats['total']} equation references")
    # Handle Figure ?? references  
    doc_content = re.sub(
        r'(Figure)' + WS + r'+<span[^>]*class="[^"]*cmbx[^"]*"[^>]*>\?\?</span>',
        r'\1 <span class="broken-ref" title="Figure reference not resolved">[fig]</span>',
        doc_content, flags=re.IGNORECASE
    )
    
    # Handle "Section ??" wrapped in cmbx span: <span class="cmbx-10x-x-109">Section ??</span>
    # This is a cross-chapter section reference that couldn't be resolved
    doc_content = re.sub(
        r'<span[^>]*class="[^"]*cmbx[^"]*"[^>]*>Section' + WS + r'+\?\?</span>',
        lambda m: 'Section ' + fix_broken_ref_from_context(m),
        doc_content, flags=re.IGNORECASE
    )

    # Handle cmbx-wrapped ?? patterns: <span class="cmbx-10x-x-109">??</span>
    # These are cross-chapter references generated by LaTeX when \ref cannot resolve the target
    # This is a fallback - process AFTER specific patterns like Eq. and Figure
    doc_content = re.sub(r'<span[^>]*class="[^"]*cmbx[^"]*"[^>]*>\?\?</span>', fix_broken_ref_from_context, doc_content)


    # B1: Remove "Chapter N" titlemark from h2.chapterHead (display-only fix)
    # The titlemark contains "Chapter N" which we want to hide/remove
    # Pattern: <span class="titlemark">Chapter N</span><br/> inside h2.chapterHead
    def clean_chapter_title(m):
        h2_content = m.group(0)
        # Remove <span class="titlemark">Chapter...</span> and following <br/>
        h2_content = re.sub(r'<span[^>]*class="[^"]*titlemark[^"]*"[^>]*>Chapter\s*\d+</span>\s*<br\s*/?>', '', h2_content, flags=re.IGNORECASE)
        # Also handle non-breaking spaces or other whitespace variations
        h2_content = re.sub(r'<span[^>]*class="[^"]*titlemark[^"]*"[^>]*>Chapter[^<]*</span>\s*<br\s*/?>', '', h2_content, flags=re.IGNORECASE)
        return h2_content
    doc_content = re.sub(r'<h2[^>]*class="[^"]*chapterHead[^"]*"[^>]*>.*?</h2>', clean_chapter_title, doc_content, flags=re.DOTALL)

    # B2: Rewrite section numbering in titlemarks: 1.x → N.x (display-only)
    # Only apply if chapter_num > 1 to avoid unnecessary processing
    chapter_num = chapter_data['num']
    if chapter_num > 1:
        def rewrite_titlemark_number(m):
            full_span = m.group(0)
            # Replace leading "1." with "N." in titlemark content
            # Handle titles like "1.2.3" or "1.1"
            return re.sub(r'>1\.', f'>{chapter_num}.', full_span, count=1)
        # Apply to h3 and h4 titlemarks (sectionHead, subsectionHead)
        doc_content = re.sub(r'<span[^>]*class="[^"]*titlemark[^"]*"[^>]*>1\.[^<]*</span>', rewrite_titlemark_number, doc_content)

    # 9. Fix Citations (Rel Link) -> bibliography.html#bib-KEY
    # B7: Improved key normalization - handle make4ht prefixes (0_, X0-, cite., bib.)
    def normalize_bib_key(key):
        """Normalize bibliography key by stripping known prefixes."""
        key = key.strip()
        # Strip known prefixes in order of specificity
        # Fix: Add stripping of \d+@ (biber) and other prefixes
        import re
        key = re.sub(r'^\d+@', '', key)
        for prefix in ['cite.', 'bib.', 'X0-', '0_', 'cite', 'bib']:
            if key.lower().startswith(prefix.lower()):
                key = key[len(prefix):]
                break
        # Clean up leading punctuation
        key = key.lstrip('.-_')
        return key
    
    def cite_repl(m):
        href = m.group(1)
        # Case 1: Internal citation links like #0_keyname or #cite.keyname
        if href.startswith('#'):
            anchor = href.lstrip('#')
            # Check if it's a citation-like anchor - includes 0_ and X0- prefixes from make4ht
            # Also catch 0@ pattern
            if any(x in anchor.lower() for x in ['cite', 'bib']) or anchor.startswith('0_') or anchor.startswith('X0-') or '@' in anchor:
                key = normalize_bib_key(anchor)
                if key:
                    return f'href="bibliography.html#bib-{key}"'
        # Case 2: Already-rewritten links - normalize for idempotency (fix links from previous runs)
        elif href.startswith('bibliography.html#bib-'):
            existing_key = href.replace('bibliography.html#bib-', '')
            normalized = normalize_bib_key(existing_key)
            if normalized != existing_key:
                return f'href="bibliography.html#bib-{normalized}"'
        return m.group(0)
    doc_content = re.sub(r'href="([^"]+)"', cite_repl, doc_content)

    # D1: Rewrite citation DISPLAY NUMBERS to match bibliography.html global numbers
    # Pattern: <a href="bibliography.html#bib-KEY">N</a> - replace N with global number
    # Also handles: <a ...>N</a>, <a ...>[N]</a>, and variations with whitespace
    cite_repl_stats = {'total': 0, 'replaced': 0, 'not_found': []}
    def cite_number_repl(m):
        key = m.group(1)  # bib key without "bib-" prefix
        bracket_open = m.group(2) or ''  # optional opening bracket
        old_num = m.group(3)  # current display number
        bracket_close = m.group(4) or ''  # optional closing bracket

        cite_repl_stats['total'] += 1

        # Normalize the key - strip 0@ prefix (biber refsection artifact)
        normalized_key = re.sub(r'^\d+@', '', key)

        if normalized_key in BIB_INDEX_MAP:
            new_num = BIB_INDEX_MAP[normalized_key]
            cite_repl_stats['replaced'] += 1
            # Also normalize the href key in the output
            return f'href="bibliography.html#bib-{normalized_key}">{bracket_open}{new_num}{bracket_close}</a>'
        # Key not in map - keep original
        if len(cite_repl_stats['not_found']) < 5:
            cite_repl_stats['not_found'].append(key)
        return m.group(0)

    # Match citation links and their display numbers - flexible pattern
    # Handles: >5</a>, >[5]</a>, > 5 </a>, etc.
    doc_content = re.sub(
        r'href="bibliography\.html#bib-([^"]+)">\s*(\[)?(\d+)(\])?\s*</a>',
        cite_number_repl, doc_content
    )

    # Debug: Print citation replacement stats
    if cite_repl_stats['total'] > 0:
        print(f"  [Citations] {cite_repl_stats['replaced']}/{cite_repl_stats['total']} numbers updated (BIB_INDEX_MAP has {len(BIB_INDEX_MAP)} entries)")
        if cite_repl_stats['not_found']:
            print(f"    Keys not in map (sample): {cite_repl_stats['not_found']}")

    # A1: Fix figure REFERENCES numbering mismatch (display only)
    # In-text references say "figure 1.1" when they should say "figure N.1" for Lecture N
    # Do NOT change href/ids, only display text
    chapter_num = chapter_data['num']
    if chapter_num > 1:
        # Pattern 1: Direct "Figure 1.x" text (not inside href)
        def fig_ref_repl(m):
            prefix = m.group(1)  # "Figure " or "Fig. " or "figure "
            sub_num = m.group(2)  # the ".x" part after "1"
            return f'{prefix}{chapter_num}{sub_num}'
        
        doc_content = re.sub(r'(?<!#)(Figure\s+|figure\s+|Fig\.\s+)1(\.\d+)', fig_ref_repl, doc_content, flags=re.IGNORECASE)
        
        # Pattern 2: Handle "Figure <a...>1.x</a>" format (tex4ht puts number inside anchor)
        # Example: Figure <a href="#...">1.2<!-- tex4ht:ref: ... --></a>
        # We need to change the "1.x" inside the anchor to "N.x"
        def fig_ref_anchor_repl(m):
            prefix = m.group(1)  # "Figure " or similar
            anchor_open = m.group(2)  # <a href="...">
            sub_num = m.group(3)  # the ".x" part after "1"
            rest = m.group(4)  # rest including closing </a>
            return f'{prefix}{anchor_open}{chapter_num}{sub_num}{rest}'
        
        # Match: (Figure/Fig. )<a...>1(.x...)<!--...--></a>
        doc_content = re.sub(
            r'(Figure\s+|figure\s+|Fig\.\s*)(<a[^>]*>)1(\.\d+)((?:<!--[^>]*-->)?</a>)',
            fig_ref_anchor_repl, doc_content, flags=re.IGNORECASE
        )

        # Fix malformed enrichment references like "14.8.0.0.0"
        # These should show the full subsection like "Enrichment 14.8.1"
        # Pattern: <a href="#x1-990014.8.1">14.8.0.0.0<!-- tex4ht:ref: ... --></a>
        def fix_malformed_enrichment_ref(m):
            href = m.group(1)  # The href value like "x1-116000doc" or "x1-990014.8.1"
            bad_num = m.group(2)  # The malformed number like "14.8.0.0.0" or "14.8.1.0.0"
            comment = m.group(3) or ''  # The tex4ht comment (optional)

            # Strip trailing .0 sequences from the bad number
            # 14.8.1.0.0 -> 14.8.1
            # 14.8.0.0.0 -> 14.8
            clean_num = re.sub(r'(\.0)+$', '', bad_num)

            return f'<a href="#{href}">Enrichment {clean_num}{comment}</a>'

        # Match both 14.8.0.0.0 and 14.8.1.0.0 patterns
        doc_content = re.sub(
            r'<a href="#([^"]+)">(\d+\.\d+(?:\.\d+)?\.0\.0)(<!--[^>]*-->)?</a>',
            fix_malformed_enrichment_ref, doc_content
        )

    # A4: Process tables with booktabs styling
    doc_content = process_tables_antigravity(doc_content)

    # E5: Fix Code Blocks (Wrap + Copy + Syntax Highlighting)
    # make4ht outputs code as pre.fancyvrb with span elements inside
    def detect_language(code_content):
        """P6: Improved language detection with regex patterns"""
        # Remove HTML tags for analysis
        plain = re.sub(r'<[^>]+>', '', code_content)
        
        # Python indicators (using regex for more reliable matching)
        python_patterns = [
            r'^\s*(import|from)\s+\w+',  # import statements
            r'\bdef\s+\w+\s*\(',  # function definitions
            r'\bclass\s+\w+\s*[:\(]',  # class definitions
            r'\b(for|while)\s+\w+\s+in\s+',  # Python loops
            r'\b(if|elif|else)\s*:',  # conditionals with colon
            r'\breturn\s+',  # return statements
            r'\b(torch|numpy|np|tf|keras|sklearn)\.',  # ML libraries
            r'\bself\.',  # self reference
            r'__\w+__',  # dunder methods
            r'\bprint\s*\(',  # print function
            r'\blambda\s+',  # lambda expressions
            r'\bwith\s+.*\s+as\s+',  # context managers
            r'\@\w+',  # decorators
        ]
        for pattern in python_patterns:
            if re.search(pattern, plain, re.MULTILINE):
                return "language-python"
        
        # Python keywords (broader check)
        python_keywords = ['import ', 'from ', 'def ', 'class ', 'return ', 'yield ', 
                         'try:', 'except:', 'finally:', 'with ', 'as ', 'raise ',
                         'True', 'False', 'None', 'and ', 'or ', 'not ']
        if any(kw in plain for kw in python_keywords):
            return "language-python"
        
        # JavaScript/TypeScript
        if any(kw in plain for kw in ['const ', 'let ', 'var ', 'function ', 'async ', '=>', 'console.']):
            return "language-javascript"
        
        # Shell/Bash
        if any(kw in plain for kw in ['#!/bin', '$ ', 'pip ', 'conda ', 'sudo ', 'apt ', 'brew ']):
            return "language-bash"
        
        # Default to Python for this CV/ML book
        return "language-python"
    
    # Track code block formatting for debugging
    code_blocks_processed = [0]  # Use list to allow mutation in nested function

    def clean_code_content(code):
        """Remove make4ht span wrappers, preserve content, and auto-format indentation like VSCode"""
        code_blocks_processed[0] += 1
        # Remove <span class="cmtt-*">...</span> wrappers (monospace font spans)
        code = re.sub(r'<span[^>]*class="[^"]*cmtt-[^"]*"[^>]*>(.*?)</span>', r'\1', code, flags=re.DOTALL)
        # Remove anchor tags inside code
        code = re.sub(r'<a[^>]*id="[^"]*"[^>]*></a>', '', code)

        # Decode HTML entities to handle &nbsp; and other special spaces
        import html
        code = html.unescape(code)

        # Replace non-breaking spaces (U+00A0) with regular spaces
        code = code.replace('\xa0', ' ')

        # Normalize base indentation first (remove common leading whitespace)
        lines = code.split('\n')
        non_empty_lines = [line for line in lines if line.strip()]

        if non_empty_lines:
            # Calculate minimum indentation
            min_indent = min(len(line) - len(line.lstrip()) for line in non_empty_lines)
            # Remove common base indentation from all lines
            normalized_lines = []
            for line in lines:
                if line.strip():  # Non-empty line
                    normalized_lines.append(line[min_indent:] if len(line) >= min_indent else line)
                else:  # Empty line
                    normalized_lines.append('')
            code = '\n'.join(normalized_lines)

        # Try to auto-format with autopep8 for proper spacing and indentation
        formatting_used = "manual"
        try:
            import autopep8
            # Format with autopep8 (fixes spacing, indentation, line breaks)
            formatted = autopep8.fix_code(code, options={
                'aggressive': 1,
                'max_line_length': 100,
                'indent_size': 4
            })
            formatting_used = "autopep8"
            print(f"   [Code Format] OK - autopep8 v{autopep8.__version__} applied", flush=True)
            code = formatted.strip()
        except ImportError as e:
            print(f"   [Code Format] SKIP - autopep8 not installed: {e}", flush=True)
            print(f"   [Code Format] → Using manual formatting", flush=True)
            code = code.strip()
        except Exception as e:
            print(f"   [Code Format] FAIL - autopep8 failed: {type(e).__name__}: {e}", flush=True)
            print(f"   [Code Format] → Using manual formatting", flush=True)
            code = code.strip()

        # Re-escape HTML entities for safe output (< > & must be escaped in HTML)
        code = code.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

        return code
    
    def code_repl(m):
        code = m.group(1)
        clean_code = clean_code_content(code)
        lang = detect_language(code)
        return f'<div class="code-wrapper"><pre><code class="{lang}">{clean_code}</code></pre></div>'
    
    # Update existing code-wrapper blocks (clean spans, update language)
    def update_existing_code_block(m):
        """Re-process existing code blocks to clean up and update language"""
        code_content = m.group(1)
        clean_code = clean_code_content(code_content)
        lang = detect_language(code_content)
        return f'<div class="code-wrapper"><pre><code class="{lang}">{clean_code}</code></pre></div>'
    
    # Process existing code-wrapper blocks (update language + clean spans)
    doc_content = re.sub(
        r'<div class="code-wrapper"><pre><code[^>]*>(.*?)</code></pre></div>',
        update_existing_code_block, doc_content, flags=re.DOTALL
    )
    
    # Process new verbatim/fancyvrb blocks (first run from make4ht output)
    # Flexible class matching: class="..." contains verbatim/fancyvrb
    doc_content = re.sub(r'<div[^>]*class=["\'][^"\']*verbatim[^"\']*["\'][^>]*>(.*?)</div>', code_repl, doc_content, flags=re.DOTALL)
    doc_content = re.sub(r'<pre class=["\'][^"\']*verbatim[^"\']*["\'][^>]*>(.*?)</pre>', code_repl, doc_content, flags=re.DOTALL)
    # E5: Add pattern for pre.fancyvrb (make4ht default code block format)
    doc_content = re.sub(r'<pre class=["\'][^"\']*fancyvrb[^"\']*["\'][^>]*>(.*?)</pre>', code_repl, doc_content, flags=re.DOTALL)
    # E5: Also match pre with listing class
    doc_content = re.sub(r'<pre class=["\'][^"\']*lstlisting[^"\']*["\'][^>]*>(.*?)</pre>', code_repl, doc_content, flags=re.DOTALL)
    
    # E5: Catch any remaining standalone <pre> not already in code-wrapper
    # This ensures all code blocks have the pre>code structure for highlight.js
    def wrap_standalone_pre(m):
        """Wrap standalone pre elements that aren't in code-wrapper"""
        pre_attrs = m.group(1) or ''
        content = m.group(2)
        # Skip if it looks like already processed (empty, very short, or contains code tag)
        if '<code' in content or len(content.strip()) < 5:
            return m.group(0)
        clean_code = clean_code_content(content)
        lang = detect_language(content)
        return f'<div class="code-wrapper"><pre{pre_attrs}><code class="{lang}">{clean_code}</code></pre></div>'
    
    # Match pre NOT already inside code-wrapper (negative lookbehind)
    doc_content = re.sub(
        r'(?<!code-wrapper">)<pre([^>]*)>(.*?)</pre>(?!</div>)',
        wrap_standalone_pre, doc_content, flags=re.DOTALL
    )

    # R1/R2: Fix escape characters in text (\_ -> _, \( -> (, etc.)
    # At this point, math is already protected via MATH_TOKEN placeholders
    # Safe to replace backslash escapes in remaining content (excludes math)
    # Use negative lookbehind to avoid double-backslash cases
    doc_content = re.sub(r'(?<!\\)\\(?=_)', '', doc_content)  # Remove single backslash before underscore
    doc_content = re.sub(r'(?<!\\)\\(?=\()', '', doc_content)  # Remove \( in text (stray math delimiter)
    doc_content = re.sub(r'(?<!\\)\\(?=\))', '', doc_content)  # Remove \) in text (stray math delimiter)
    doc_content = re.sub(r'(?<!\\)\\(?=\[)', '', doc_content)  # Remove \[ in text (stray math delimiter)
    doc_content = re.sub(r'(?<!\\)\\(?=\])', '', doc_content)  # Remove \] in text (stray math delimiter)

    # Remove TeX4ht vrule artifacts that create unwanted vertical black lines
    # These can appear as spans/divs with specific width styles or vrule classes
    doc_content = re.sub(r'<span[^>]*class="[^"]*vrule[^"]*"[^>]*>.*?</span>', '', doc_content, flags=re.DOTALL)
    doc_content = re.sub(r'<div[^>]*class="[^"]*vrule[^"]*"[^>]*>.*?</div>', '', doc_content, flags=re.DOTALL)
    # Remove thin vertical line elements (style with small width and height)
    doc_content = re.sub(r'<span[^>]*style="[^"]*width:\s*[0-1]\.?\d*\s*(?:px|pt|em)[^"]*height:\s*\d+[^"]*"[^>]*>.*?</span>', '', doc_content, flags=re.DOTALL)
    doc_content = re.sub(r'<hr[^>]*class="[^"]*vrule[^"]*"[^>]*/?\s*>', '', doc_content)

    # P1: Replace ugly enrichment dashed/underscore lines with clean dividers
    # Multi-pass approach for robustness
    
    # Pass 1: Replace paragraphs that contain ONLY underscores/dashes
    doc_content = re.sub(
        r'<p[^>]*>\s*(?:_{6,}\s*)+</p>',
        '<hr class="enrichment-divider">', doc_content, flags=re.DOTALL
    )
    doc_content = re.sub(
        r'<p[^>]*>\s*(?:-{6,}\s*)+</p>',
        '<hr class="enrichment-divider">', doc_content, flags=re.DOTALL
    )
    
    # Pass 2: Replace underscore lines that appear at END of paragraphs (before </p>)
    # Pattern: text... underscore_lines </p>
    def clean_trailing_underscores(m):
        before = m.group(1)  # Content before underscores
        # Return the content with HR appended, then close the paragraph
        return f'{before}</p>\n<hr class="enrichment-divider">'
    
    # Match: ...text...\n___...___\n</p>
    doc_content = re.sub(
        r'([^_\n])\s*\n\s*((?:_{10,}\s*\n?\s*)+)</p>',
        clean_trailing_underscores, doc_content, flags=re.MULTILINE
    )
    doc_content = re.sub(
        r'([^-\n])\s*\n\s*((?:-{10,}\s*\n?\s*)+)</p>',
        clean_trailing_underscores, doc_content, flags=re.MULTILINE
    )
    
    # Pass 3: Handle standalone underscore lines between tags
    doc_content = re.sub(r'(?<=>)\s*_{6,}\s*(?=<)', '<hr class="enrichment-divider">', doc_content)
    doc_content = re.sub(r'(?<=>)\s*-{6,}\s*(?=<)', '<hr class="enrichment-divider">', doc_content)
    
    # Pass 4: Clean up any remaining underscore-only lines (multi-line)
    doc_content = re.sub(
        r'\n\s*_{20,}\s*\n\s*_{20,}\s*\n',
        '\n<hr class="enrichment-divider">\n', doc_content
    )
    
    # Idempotency: remove duplicate consecutive HRs
    doc_content = re.sub(
        r'(<hr class="enrichment-divider"\s*/?>)\s*(<hr class="enrichment-divider"\s*/?>)+',
        r'\1', doc_content
    )
    
    # A3: Convert enrichment titles to proper heading elements with IDs
    # Pattern: <p...><span...><span class="cmbx-10x-x-109">Enrichment: Title</span></span></p>
    # NOTE: LaTeX already numbers enrichments correctly via \refstepcounter in structure.tex
    # So we keep the original title text from make4ht which already has correct numbering
    enrichment_counter = [0]  # Use list to allow modification in nested function
    
    def enrichment_title_repl(m):
        title_text = m.group(1)
        # Already converted? Skip
        if 'enrichment-title' in title_text:
            return m.group(0)
        
        # Generate slug for ID
        enrichment_counter[0] += 1
        # Extract title after "Enrichment:" or numbered prefix like "Enrichment 15.2:"
        clean_title = re.sub(r'^Enrichment(?:\s+[\d.]+)?:\s*', '', title_text, flags=re.IGNORECASE).strip()
        # Create slug: lowercase, replace non-alphanum with hyphens
        slug = re.sub(r'[^a-z0-9]+', '-', clean_title.lower()).strip('-')
        slug = slug[:50] if len(slug) > 50 else slug  # Limit length
        eid = f'enrichment-{slug}-{enrichment_counter[0]}'
        
        # Keep original title text from LaTeX (already has correct section numbering)
        # Use h3 for section-level enrichments (matches section font size)
        # Add data-emoji attribute for idempotent emoji handling via CSS ::after
        return f'<h3 class="enrichment-title" id="{eid}" data-emoji="true">{title_text}</h3>'
    
    # Match paragraphs containing enrichment titles
    doc_content = re.sub(
        r'<p[^>]*>\s*<span[^>]*>\s*<span[^>]*class="[^"]*cmbx[^"]*"[^>]*>(Enrichment:\s*[^<]+)</span>\s*</span>\s*</p>',
        enrichment_title_repl, doc_content, flags=re.DOTALL
    )
    # Also handle direct span pattern without nested spans
    doc_content = re.sub(
        r'<p[^>]*>\s*<span[^>]*class="[^"]*cmbx[^"]*"[^>]*>(Enrichment:\s*[^<]+)</span>\s*</p>',
        enrichment_title_repl, doc_content, flags=re.DOTALL
    )
    
    # Add IDs to existing enrichment titles that lack them (for idempotency)
    # IMPORTANT: Do NOT change heading levels - make4ht outputs correct h3/h4/h5 based on LaTeX structure
    def add_enrichment_id(m):
        """Add IDs to enrichment headings without changing their level."""
        full_match = m.group(0)
        heading_tag = m.group(1)  # h3 or h4
        existing_attrs = m.group(2)
        title_text = m.group(3)
        
        # Already has ID? Skip entirely to preserve idempotency
        if 'id="' in existing_attrs:
            return full_match
        
        # Generate ID from title
        enrichment_counter[0] += 1
        clean_title = re.sub(r'^Enrichment(?:\s+[\d.]+)?:\s*', '', title_text, flags=re.IGNORECASE).strip()
        slug = re.sub(r'[^a-z0-9]+', '-', clean_title.lower()).strip('-')
        slug = slug[:50] if len(slug) > 50 else slug
        eid = f'enrichment-{slug}-{enrichment_counter[0]}'
        
        # Return with same heading level, just add ID and data-emoji
        return f'<{heading_tag} class="enrichment-title" id="{eid}" data-emoji="true">{title_text}</{heading_tag}>'
    
    # Match h3 or h4 enrichment titles to add IDs (preserving their original level)
    doc_content = re.sub(
        r'<(h[345])([^>]*class="enrichment-title"[^>]*)>(Enrichment[^<]+)</h[345]>',
        add_enrichment_id, doc_content
    )
    
    # A4: UNIFIED SECTION RENUMBERING PASS
    # Process ALL h3/h4/h5 headings in document order and renumber consistently
    # This treats enrichments as their declared level (h3 = section, h4 = subsection)
    # The HTML structure from make4ht already reflects the correct hierarchy
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(doc_content, 'html.parser')
        
        # Counters for section hierarchy
        section_counter = 0
        subsection_counter = 0
        subsubsection_counter = 0
        
        # Find all relevant headings in document order
        headings = soup.find_all(['h3', 'h4', 'h5'])
        
        for heading in headings:
            heading_classes = heading.get('class', [])
            if isinstance(heading_classes, str):
                heading_classes = [heading_classes]
            
            # Skip chapterHead (h2 styled as h3 sometimes)
            if 'chapterHead' in heading_classes:
                continue
            
            # Determine heading type
            is_h3_section = heading.name == 'h3' and 'sectionHead' in heading_classes
            is_h3_enrichment = heading.name == 'h3' and 'enrichment-title' in heading_classes
            is_h4_subsection = heading.name == 'h4' and 'subsectionHead' in heading_classes
            is_h4_enrichment = heading.name == 'h4' and 'enrichment-title' in heading_classes
            is_h5_subsubsection = heading.name == 'h5' and ('subsubsectionHead' in heading_classes or 'enrichment-title' in heading_classes)
            
            if is_h3_section:
                # Regular section
                section_counter += 1
                subsection_counter = 0
                subsubsection_counter = 0
                new_number = f"{chapter_num}.{section_counter}"
                
                titlemark = heading.find('span', class_='titlemark')
                if titlemark:
                    titlemark.string = f"{new_number}   "
                    
            elif is_h3_enrichment:
                # Enrichment at h3 level = section level (e.g., 15.2, 15.6, 15.7)
                # The HTML structure from make4ht already determines this is section-level
                section_counter += 1
                subsection_counter = 0
                subsubsection_counter = 0
                new_number = f"{chapter_num}.{section_counter}"
                
                text = heading.get_text()
                clean_title = re.sub(r'^Enrichment(?:\s+[\d.]+)?:\s*', '', text, flags=re.IGNORECASE).strip()
                heading.string = f"Enrichment {new_number}: {clean_title}"
                
            elif is_h4_subsection:
                # Regular subsection - doesn't reset enrichment context
                subsection_counter += 1
                subsubsection_counter = 0
                new_number = f"{chapter_num}.{section_counter}.{subsection_counter}"
                
                titlemark = heading.find('span', class_='titlemark')
                if titlemark:
                    titlemark.string = f"{new_number}   "
                    
            elif is_h4_enrichment:
                # Enrichment at h4 level - subsection
                subsection_counter += 1
                subsubsection_counter = 0
                new_number = f"{chapter_num}.{section_counter}.{subsection_counter}"
                
                text = heading.get_text()
                clean_title = re.sub(r'^Enrichment(?:\s+[\d.]+)?:\s*', '', text, flags=re.IGNORECASE).strip()
                heading.string = f"Enrichment {new_number}: {clean_title}"
                        
            elif is_h5_subsubsection:
                subsubsection_counter += 1
                new_number = f"{chapter_num}.{section_counter}.{subsection_counter}.{subsubsection_counter}" if subsection_counter > 0 else f"{chapter_num}.{section_counter}.{subsubsection_counter}"
                
                if 'enrichment-title' in heading_classes:
                    text = heading.get_text()
                    clean_title = re.sub(r'^Enrichment(?:\s+[\d.]+)?:\s*', '', text, flags=re.IGNORECASE).strip()
                    heading.string = f"Enrichment {new_number}: {clean_title}"
                # Regular subsubsection titlemarks are already handled by make4ht
        
        doc_content = str(soup)
    except ImportError:
        # BeautifulSoup not available, skip unified renumbering
        pass

    # A5: Fix section numbering mismatches (enrichment sections cause gaps)
    # This must run AFTER BeautifulSoup processing to avoid being overwritten
    def fix_section_numbering(html_content):
        """
        Fix section numbering where titlemark doesn't match anchor ID.
        This happens when enrichment sections are numbered in LaTeX, causing gaps
        in the main section sequence (e.g., 14.6 appears twice, 14.7 is skipped).
        """
        # Pattern: <span class="titlemark">14.6   </span> <a id="x1-9900014.7"></a>
        pattern = r'<span class="titlemark">(\d{1,2}\.\d+)\s+</span>\s*<a id="([^"]+)"></a>'

        def replace_mismatched_number(match):
            titlemark_num = match.group(1)
            anchor_id = match.group(2)

            # Extract correct number from anchor ID
            # Skip leading zeros, then capture chapter (1-2 digits) and section
            anchor_match = re.search(r'0*(\d{1,2}\.\d+)$', anchor_id)
            if anchor_match:
                correct_num = anchor_match.group(1)

                if titlemark_num != correct_num:
                    print(f"  Fixing section number: '{titlemark_num}' -> '{correct_num}' in {anchor_id}")
                    return f'<span class="titlemark">{correct_num}   </span> <a id="{anchor_id}"></a>'

            # No change needed
            return match.group(0)

        return re.sub(pattern, replace_mismatched_number, html_content)

    doc_content = fix_section_numbering(doc_content)

    # E1/R2: Fix LaTeX \texttt{...} underscore escaping for INLINE code only
    # Match inline <code> that are NOT inside <pre>
    def texttt_underscore_fix(m):
        full_match = m.group(0)
        attrs = m.group(1)  # Capture existing attributes (class, id, etc.)
        content = m.group(2)
        # Check if this is inside a <pre> (skip if so)
        # We do this by checking if there's a class indicating it's a code block
        if 'language-' in attrs:
            return full_match  # Don't modify code block content
        # Remove backslash before underscore in inline code
        fixed = content.replace('\\_', '_')
        return f'<code{attrs}>{fixed}</code>'
    
    # Match inline code/tt tags
    doc_content = re.sub(r'<code([^>]*)>(.*?)</code>', texttt_underscore_fix, doc_content, flags=re.DOTALL)
    doc_content = re.sub(r'<tt([^>]*)>(.*?)</tt>', lambda m: f'<code{m.group(1)}>{m.group(2).replace(chr(92)+"_", "_")}</code>', doc_content, flags=re.DOTALL)

    # B8: Process figure captions - bold FULL prefix and fix lecture numbering
    chapter_num = chapter_data['num']  # Get lecture/chapter number
    
    def process_caption(m):
        full_caption = m.group(0)
        
        # First strip any existing fig-label spans (fix incorrectly wrapped content)
        full_caption = re.sub(r'<span class="fig-label">([^<]*)</span>', r'\1', full_caption)
        
        # Match full prefix pattern: "FigureN.M:", "Figure N.Y:", "Figure N:" etc
        # Handle both "Figure 1.1:" (with space) and "Figure1.1:" (no space, from make4ht)
        # Pattern captures: (prefix)(main_num)(sub_num including dots)(suffix colon/period)
        pattern = r'((?:Figure|Fig\.|Table|Algorithm|Definition|Listing)\s*)(\d+)((?:\.\d+)*)([\s:]+)'
        
        def rewrite_label(match):
            prefix = match.group(1)  # "Figure " or "Figure" (may have space or not)
            main_num = match.group(2)  # First number
            sub_num = match.group(3)  # ".Y" or ".Y.Z" or empty
            suffix = match.group(4)  # ":" or ": " or " "
            
            # B8: Fix lecture numbering - if main_num is "1", rewrite to chapter_num
            # This fixes the issue where all figures show "Figure 1.Y" instead of "Figure N.Y"
            if main_num == "1" and chapter_num > 1:
                main_num = str(chapter_num)
            
            full_label = f'{prefix}{main_num}{sub_num}{suffix}'
            return f'<span class="fig-label">{full_label}</span>'
        
        new_caption = re.sub(pattern, rewrite_label, full_caption, count=1)
        return new_caption
    
    # Apply to various caption formats including figcaption elements
    doc_content = re.sub(r'<figcaption[^>]*>.*?</figcaption>', process_caption, doc_content, flags=re.DOTALL)
    doc_content = re.sub(r'<p[^>]*class="[^"]*caption[^"]*"[^>]*>.*?</p>', process_caption, doc_content, flags=re.DOTALL)
    doc_content = re.sub(r'<div[^>]*class="[^"]*caption[^"]*"[^>]*>.*?</div>', process_caption, doc_content, flags=re.DOTALL)
    doc_content = re.sub(r'<span[^>]*class="[^"]*id[^"]*"[^>]*>.*?</span>', process_caption, doc_content, flags=re.DOTALL)

    # P9: Fix equation numbering - "Equation 1.x" -> "Equation N.x" for Chapter N
    # This applies to in-text equation references, not the equation labels themselves (MathJax handles those)
    if chapter_num > 1:
        # Pattern: "Equation <a href="...">1.x<!-- comment --></a>" - TeX4ht puts comments inside anchors
        def eq_ref_repl(m):
            prefix = m.group(1)  # "Equation ", "Eq. ", etc.
            anchor_open = m.group(2)  # "<a href="...">"
            old_num = m.group(3)  # "1.x" or just "1"
            rest = m.group(4)  # Everything after the number (comments, </a>)
            # Replace leading "1." with "N." or just "1" with "N"
            if old_num.startswith('1.'):
                new_num = f'{chapter_num}.' + old_num[2:]
            elif old_num == '1':
                new_num = str(chapter_num)
            else:
                new_num = old_num
            return f'{prefix}{anchor_open}{new_num}{rest}'
        
        # Match equation references with anchor tags (handles HTML comments inside anchor)
        # Pattern captures: (Equation )(< a href="...">)(1.x)(<!-- ... --></a>)
        doc_content = re.sub(
            r'(Equation\s+|Eq\.\s+|equation\s+|eq\.\s+)(<a[^>]*>)(1(?:\.\d+)?)((?:<!--[^>]*-->)?</a>)',
            eq_ref_repl, doc_content, flags=re.IGNORECASE
        )
        
        # Also fix plain text equation references (not in anchors)
        doc_content = re.sub(
            r'(Equation\s+|Eq\.\s+)(1)(\.\d+)(?![^<]*</a>)',
            lambda m: f'{m.group(1)}{chapter_num}{m.group(3)}',
            doc_content, flags=re.IGNORECASE
        )

    # 4B. Extract TOC with lecture number for section numbering rewrite
    local_toc = extract_toc_from_body(doc_content, lecture_num=chapter_num)
    
    # Restore Math
    doc_content = restore_math(doc_content)
    
    # Post-Restore Cleanup: content now has raw LaTeX math, fix artifacts
    doc_content = clean_latex_artifacts(doc_content)
    
    # Specific \mathchar cleanup
    # \mathchar"458 in this context is a Checkmark (✓)
    # Be robust to variations: \mathchar "458 (spaced quote), wrapped in \( ... \)
    # Case 1: Wrapped in MathJax delims -> Strip delims + replace
    doc_content = re.sub(
        r'\\(?:\(|\[)\s*(?:\\|&#x5C;|&#92;|&#x5c;)mathchar\s*"?\s*458\s*\\(?:\)|\])', 
        '<span style="color:var(--primary); font-weight:bold;">\u2713</span>', 
        doc_content, flags=re.IGNORECASE
    )
    # Case 2: Bare occurrence
    doc_content = re.sub(
        r'(?:\\|&#x5C;|&#92;|&#x5c;)mathchar\s*"?\s*458', 
        '<span style="color:var(--primary); font-weight:bold;">\u2713</span>', 
        doc_content, flags=re.IGNORECASE
    )
    # Remove any other stray mathchars (literal or encoded)
    doc_content = re.sub(r'(?:\\|&#x5C;|&#92;|&#x5c;)mathchar\s*"?\s*[0-9A-Fa-f]+', '', doc_content, flags=re.IGNORECASE)
    
    # F7: Fix Image Paths (Case Sensitivity) & Base URL
    doc_content = fix_image_paths(doc_content)

    
    # Navigation
    num = chapter_data['num']
    prev_ch = next((c for c in CHAPTERS if c['num'] == num - 1), None)
    next_ch = next((c for c in CHAPTERS if c['num'] == num + 1), None)
    
    # Nav links with padded numbering for PDFs (e.g. Chapter_15.pdf)
    pdf_book = get_asset_url("downloads/main.pdf", is_aux=False)
    pdf_chapter = get_asset_url(f"downloads/Chapter_{num:02d}.pdf", is_aux=False)

    top_bar_html = f"""
    <div class="nav-btns">
        <div class="dropdown">
            <button class="nav-btn" style="background: var(--gray-200); color: var(--text);"><i class="fas fa-file-pdf"></i></button>
            <div class="dropdown-content">
                <a href="{pdf_book}" target="_blank">Full Book</a>
                <a href="{pdf_chapter}" target="_blank">This Chapter</a>
            </div>
        </div>
        <button id="btn_top" class="nav-btn">Top <i class="fas fa-arrow-up"></i></button>
    </div>
    """

    # Bottom Nav (Fix 3: Gray/Blue Cards)
    # Old logic: Prev = Gray, Next = Blue.
    bottom_nav = '<div style="margin-top: 4rem; padding-top: 2rem; border-top: 1px solid #eee; display: flex; justify-content: space-between; gap: 1rem; flex-wrap: wrap;">'
    
    if prev_ch:
        bottom_nav += f'''
        <a href="{prev_ch['file']}" class="nav-btn" style="flex:1; padding: 1.5rem; display:block; text-align:left; max-width: 45%;">
            <div style="font-size:0.8rem; text-transform:uppercase; color:#666;">Previous Lecture</div>
            <div style="font-size:1.1rem; font-weight:700;">← Lecture {prev_ch['num']}</div>
            <div style="font-size:0.95rem; font-weight:400; color:#444;">{prev_ch['title']}</div>
        </a>'''
    else:
        bottom_nav += '<div></div>'
        
    if next_ch:
        bottom_nav += f'''
        <a href="{next_ch['file']}" class="nav-btn primary" style="flex:1; padding: 1.5rem; display:block; text-align:right; max-width: 45%;">
             <div style="font-size:0.8rem; text-transform:uppercase; color:rgba(255,255,255,0.8);">Next Lecture</div>
             <div style="font-size:1.1rem; font-weight:700;">Lecture {next_ch['num']} →</div>
             <div style="font-size:0.95rem; font-weight:400; opacity:0.9;">{next_ch['title']}</div>
        </a>'''
    
    bottom_nav += '</div>'

    # Build Wrapper
    page_title = f'Lecture {num}: {chapter_data["title"]}'
    sidebar_html = build_sidebar(num, is_aux=False, local_toc_content=local_toc)
    
    html = render_page_html(
        title=page_title,
        body_content=doc_content,
        sidebar_html=sidebar_html,
        nav_buttons_html=top_bar_html,
        bottom_nav_html=bottom_nav,
        is_aux=False
    )
    
    # CRITICAL SAFETY CHECK: Validate before writing to prevent content wiping
    is_safe, error_msg = validate_output_safety(html, html_file.name)
    if not is_safe:
        print(f"  [X] SAFETY CHECK FAILED for {html_file.name}: {error_msg}")
        print(f"  [!] Keeping original file unchanged to prevent data loss!")
        return  # Do NOT overwrite the file

    # Report code block processing stats
    if code_blocks_processed[0] > 0:
        print(f"  [Code Blocks] Processed {code_blocks_processed[0]} code blocks", flush=True)

    # Safe to write
    html_file.write_text(html, encoding='utf-8')
    print(f"  [OK] Validated and saved {html_file.name}")

# 5. AUX PAGES (Homepage, Bib, Preface...)
# -----------------------------------------------------------------------------
def build_bib():
    """Build bibliography.html from .bbl file, with fallback to .bib parsing."""
    # Try multiple paths for .bbl file
    bbl_paths = [
        Path("html_output/main_html.bbl"),
        Path("./html_output/main_html.bbl"),
        HTML_OUTPUT_DIR / "main_html.bbl",
    ]
    bbl = None
    for p in bbl_paths:
        if p.exists():
            bbl = p
            print(f"[Bibliography] Found .bbl file at: {p}")
            break

    bib = Path("bibliography.bib")  # Fallback source

    html_entries = []

    # Primary: Parse .bbl file (from LaTeX build)
    if bbl and bbl.exists():
        content = bbl.read_text(encoding='utf-8', errors='replace')
        entries = re.split(r'\\entry\{', content)[1:]
        
        for i, entry in enumerate(entries):
            key_m = re.match(r'^([^}]+)\}', entry)
            if not key_m: continue
            key = key_m.group(1)
            key = key.replace('#cite.', '').replace('#bib.', '') 
            # Fix: Strip '0@' prefix (biber refsection artifact)
            key = re.sub(r'^\d+@', '', key)
            norm_key = key
            
            def get_field(name):
                m = re.search(r'\\field\{' + name + r'\}\{([^}]+)\}', entry)
                return m.group(1) if m else ""
                
            title = get_field('title') or "Untitled"
            year = get_field('year') or ""
            
            entry_flat = entry.replace('\n', ' ')
            fams = re.findall(r'family=\{([^}]+)\}', entry_flat)
            givs = re.findall(r'given=\{([^}]+)\}', entry_flat)
            
            authors = []
            if len(fams) == len(givs):
                for f, g in zip(fams, givs):
                    authors.append(f"{g} {f}")
            else:
                authors = fams
            
            author_str = ", ".join(authors) if authors else "Unknown Author"

            url = ""
            m_url = re.search(r'\\verb\{url\}\s*\\verb (.*?)\s*\\endverb', entry, re.DOTALL)
            if m_url:
                url = m_url.group(1).strip()
            
            link_html = ""
            if url:
                 link_html = f'<a href="{url}" target="_blank" class="bib-ref-link" style="margin-left:auto;">Paper <i class="fas fa-external-link-alt"></i></a>'

            html_entries.append(f'''
            <div class="bib-entry" id="bib-{norm_key}">
               <div class="bib-label">[{i+1}]</div>
               <div class="bib-content">
                   <div style="display:flex; align-items:flex-start; justify-content:space-between;">
                       <span class="bib-author">{author_str}</span>
                       {link_html}
                   </div>
                   <span class="bib-title">{title}</span>
                   <div class="bib-meta">
                       <span class="bib-year">{year}</span>
                   </div>
               </div>
            </div>
            ''')

        print(f"[Bibliography] Parsed {len(html_entries)} entries from .bbl file")
    
    # Fallback: Parse .bib file directly (simpler format)
    elif bib.exists():
        print("[Bibliography] WARNING: No .bbl file found! Tried paths:")
        for p in bbl_paths:
            print(f"    - {p} (exists: {p.exists()})")
        print("[Bibliography] Falling back to .bib parsing (citation numbers may not match)...")
        content = bib.read_text(encoding='utf-8', errors='replace')
        
        # Simple BibTeX parser - find @type{key, ... } blocks
        pattern = r'@(\w+)\s*\{\s*([^,]+)\s*,([^@]*)'
        matches = re.findall(pattern, content, re.DOTALL)
        
        for i, (entry_type, key, fields) in enumerate(matches[:500]):  # Limit to 500 for performance
            key = key.strip()
            
            def get_bib_field(name):
                m = re.search(rf'{name}\s*=\s*[\{{"](.*?)[\}}"]', fields, re.DOTALL | re.IGNORECASE)
                if m:
                    val = m.group(1).strip()
                    # Clean LaTeX artifacts
                    val = re.sub(r'[{}]', '', val)
                    return val
                return ""
            
            title = get_bib_field('title') or "Untitled"
            year = get_bib_field('year') or ""
            author = get_bib_field('author') or "Unknown Author"
            url = get_bib_field('url') or get_bib_field('doi')
            if url and url.startswith('10.'):
                url = f"https://doi.org/{url}"
            
            link_html = ""
            if url:
                link_html = f'<a href="{url}" target="_blank" class="bib-ref-link" style="margin-left:auto;">Paper <i class="fas fa-external-link-alt"></i></a>'
            
            html_entries.append(f'''
            <div class="bib-entry" id="bib-{key}">
               <div class="bib-label">[{i+1}]</div>
               <div class="bib-content">
                   <div style="display:flex; align-items:flex-start; justify-content:space-between;">
                       <span class="bib-author">{author}</span>
                       {link_html}
                   </div>
                   <span class="bib-title">{title}</span>
                   <div class="bib-meta">
                       <span class="bib-year">{year}</span>
                   </div>
               </div>
            </div>
            ''')
        
        print(f"[Bibliography] Parsed {len(html_entries)} entries from .bib fallback")
    
    else:
        print("[Bibliography] ERROR: No .bbl or .bib file found!")
        print("    Tried .bbl paths:")
        for p in bbl_paths:
            print(f"      - {p} (exists: {p.exists()})")
        print(f"    Tried .bib path: {bib} (exists: {bib.exists()})")
        print("[Bibliography] Skipping bibliography generation - citation numbers will be broken!")
        return
    
    if html_entries:
        generate_aux_page("Bibliography", "".join(html_entries), "bibliography.html")

def build_index():
    # Fix 1: Homepage Centered Card Layout (v2) with UI Fixes
    cards = ""
    for ch in CHAPTERS:
        cards += f"""
        <a href="{ch['file']}" class="chapter-card">
            <div style="color:var(--primary); font-weight:900; font-size:0.8rem; margin-bottom:0.5rem; text-transform:uppercase;">Lecture {ch['num']}</div>
            <div style="font-size:1.3rem; font-weight:800;">{ch['title']}</div>
        </a>"""
        
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    {get_common_head("Deep Learning for Computer Vision")}
    <style>
        /* Override common head strictness for Homepage */
        html, body {{ height: auto !important; overflow-y: auto !important; display: block !important; }}

        .hero {{ text-align: center; padding: 4rem 1rem; background: var(--gray-50); border-bottom: 1px solid var(--gray-300); }}

        .grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 2rem; max-width: 1400px; margin: 3rem auto; padding: 0 2rem; }}

        .chapter-card {{ background: var(--gray-50); padding: 2.5rem; border-radius: 20px; text-decoration: none !important; color: inherit; border: 1px solid var(--gray-300); transition: 0.3s; display: block; }}
        .chapter-card:hover {{ transform: translateY(-8px); border-color: var(--primary); box-shadow: 0 20px 40px rgba(0,0,0,0.1); }}

        /* Fix 2: Wider, shorter info boxes */
        .info-row {{ display: flex; gap: 2rem; justify-content: center; margin: 2rem auto; max-width: 1200px; flex-wrap: wrap; }}
        .info-box {{ background: var(--bg); padding: 0.75rem 1.0rem; border-radius: 12px; border: 1px solid var(--gray-300); flex: 1; min-width: 300px; text-align: left; box-shadow: 0 4px 6px rgba(0,0,0,0.02); }}
        .info-box p {{ color: var(--text) !important; opacity: 0.8; }}
        .subtitle {{ color: var(--text); opacity: 0.7; }}
        .footer-text {{ color: var(--text); opacity: 0.6; }}

        /* Dark mode for homepage */
        body.dark-mode {{ background: var(--bg) !important; }}
        body.dark-mode .hero {{ background: var(--gray-100) !important; border-color: var(--gray-300) !important; }}
        body.dark-mode .info-box {{ background: var(--gray-100) !important; border-color: var(--gray-300) !important; }}
        body.dark-mode .chapter-card {{ background: var(--gray-100) !important; border-color: var(--gray-300) !important; color: var(--text) !important; }}
        body.dark-mode .chapter-card div {{ color: var(--text) !important; }}
        body.dark-mode .chapter-card div:first-child {{ color: var(--primary) !important; }}
        body.dark-mode .nav-btn {{ background: var(--gray-200) !important; color: var(--text) !important; }}
        body.dark-mode .nav-btn.primary {{ background: var(--primary) !important; color: #fff !important; }}
        body.dark-mode .nav-btn.danger {{ background: #333 !important; color: #fff !important; }}

        /* High contrast for homepage */
        body.high-contrast {{ background: #000 !important; }}
        body.high-contrast .hero {{ background: #000 !important; border-color: #fff !important; }}
        body.high-contrast .info-box {{ background: #000 !important; border-color: #fff !important; }}
        body.high-contrast .info-box h4, body.high-contrast .info-box p {{ color: #fff !important; }}
        body.high-contrast .chapter-card {{ background: #000 !important; border-color: #fff !important; }}
        body.high-contrast .chapter-card div {{ color: #fff !important; }}
        body.high-contrast .chapter-card div:first-child {{ color: #ffff00 !important; }}
        body.high-contrast .nav-btn {{ background: #ffff00 !important; color: #000 !important; border: 2px solid #fff !important; }}
        body.high-contrast .nav-btn.primary {{ background: #ffff00 !important; color: #000 !important; }}
        body.high-contrast .nav-btn.danger {{ background: #ffff00 !important; color: #000 !important; }}
        body.high-contrast h1, body.high-contrast p {{ color: #fff !important; }}
        body.high-contrast .subtitle, body.high-contrast .footer-text {{ color: #fff !important; opacity: 1 !important; }}

        /* Mobile fixes */
        @media (max-width: 768px) {{
            .hero h1, .hero p {{ text-align: center !important; }}
        }}
    </style>
</head>
<body>
    <header class="hero">
        <h1 style="border:none; margin:0; font-size:3rem; color:var(--text);">Deep Learning for Computer Vision</h1>
        <p class="subtitle" style="font-size:1.2rem; font-weight:300; text-align:center;">EECS 498-007 / 598-005 | University of Michigan</p>

        <div class="info-row">
            <div class="info-box" style="border-left: 4px solid #7FD1B9;">
                <h4 style="margin:0 0 0.25rem 0; color:#7FD1B9;"><i class="fas fa-code-branch"></i> Open Source</h4>
                <p style="margin:0; font-size:0.95rem;">Built from source. Content matches lectures.</p>
            </div>
            <div class="info-box" style="border-left: 4px solid #7A6563;">
                <h4 style="margin:0 0 0.25rem 0; color:#7A6563;"><i class="fas fa-circle-info"></i> Disclaimer</h4>
                <p style="margin:0; font-size:0.95rem;">Unofficial learning platform. Not affiliated with course staff.</p>
            </div>
        </div>

        <!-- Hero Search Bar -->
        <div class="hero-search-wrapper">
            <div class="search-input-wrapper">
                <i class="fas fa-search" style="color:#aaa;"></i>
                <input type="text" class="search-input pagefind-trigger" placeholder="Loading..." data-active-placeholder="Search for lectures, topics, or equations..." disabled>
            </div>
            <div class="search-results"></div>
        </div>

        <!-- Fix 3: Blue buttons -->
        <div style="display:flex; justify-content:center; gap:1rem; flex-wrap:wrap;">
            <a href="{get_asset_url('Auxiliary/Preface.html')}" class="nav-btn primary">Read Preface</a>
            <a href="{get_asset_url('dependency_graph.html')}" class="nav-btn primary">Dependency Graph</a>
            <a href="{get_asset_url('bibliography.html')}" class="nav-btn primary">Bibliography</a>
            <a href="{get_asset_url('downloads/main.pdf')}" class="nav-btn danger">Download PDF</a>
        </div>
    </header>
    
    <div class="grid">{cards}</div>
    
    <footer class="footer-text" style="text-align:center; padding:2rem; font-size:0.9rem;">
        Feedback? <a href="https://github.com/RonsGit/DL4CV/issues" style="color:var(--primary); font-weight:700;">Open Issue</a> or <a href="mailto:eecs498summary@gmail.com" style="color:var(--primary); font-weight:700;">Email Us</a>
    </footer>
    
    {get_js_footer()}
</body>
</html>"""
    Path("html_output/index.html").write_text(html, encoding='utf-8')

def generate_aux_page(title, body, filename):
    # Determine active_mk for sidebar highlighting
    active_mk = "aux"
    if "bib" in filename.lower(): active_mk = "bib"
    elif "dependency" in filename.lower(): active_mk = "dep"
    elif "preface" in filename.lower(): active_mk = "preface"

    # Issue 2: Generate IDs for headings in auxiliary pages (for floating nav)
    def ensure_heading_ids(html_content):
        """Add IDs to headings that don't have them"""
        def add_id(m):
            tag = m.group(1)
            attrs = m.group(2)
            content = m.group(3)
            # Check if already has id
            if 'id=' in attrs:
                return m.group(0)
            # Generate ID from content
            text = re.sub(r'<[^>]+>', '', content).strip()
            id_val = re.sub(r'[^a-zA-Z0-9]+', '-', text).strip('-').lower()[:50]
            if not id_val:
                # B2: Use deterministic hash instead of Python's non-stable hash()
                id_val = f"heading-{hashlib.sha1(content.encode()).hexdigest()[:8]}"
            return f'<{tag} id="{id_val}"{attrs}>{content}</{tag}>'
        
        html_content = re.sub(r'<(h[2-6])([^>]*)>(.*?)</\1>', add_id, html_content, flags=re.DOTALL)
        return html_content
    
    body = ensure_heading_ids(body)

    # Issue 2: Clean up stray text/artifacts from Preface
    # Remove common LaTeX artifacts and extra whitespace
    body = re.sub(r'\\(medskip|bigskip|noindent|newpage|clearpage|vspace\{[^}]*\}|hspace\{[^}]*\})', '', body)
    body = re.sub(r'<p>\s*</p>', '', body)  # Remove empty paragraphs
    body = re.sub(r'^\s*<br\s*/?>\s*', '', body, flags=re.MULTILINE)  # Remove leading breaks
    
    sidebar = build_sidebar(active_mk, is_aux="Auxiliary" in filename)
    rel = "../" if "Auxiliary" in filename else ""
    
    # Nav Logic (Preface/DepGraph/Bib) - Clean Top Bar as requested
    # Only PDF and Top buttons.
    prev_link, next_link = "#", "#"
    prev_txt, next_txt = "", ""

    # Determine page-specific PDF if available
    # Use is_aux based on whether file is in Auxiliary folder (matches rel prefix logic)
    is_aux_page = "Auxiliary" in filename
    page_pdf = None
    page_pdf_label = None
    if "preface" in filename.lower():
        page_pdf = get_asset_url('downloads/Preface.pdf', is_aux=is_aux_page)
        page_pdf_label = "This Page"
    elif "bib" in filename.lower():
        page_pdf = get_asset_url('downloads/Bibliography.pdf', is_aux=is_aux_page)
        page_pdf_label = "This Page"

    # Top Bar HTML (Aux - Match Chapter Style Exactly)
    dropdown_content = f'<a href="{get_asset_url("downloads/main.pdf", is_aux=is_aux_page)}" target="_blank">Full Book</a>'
    if page_pdf:
        dropdown_content += f'\n                <a href="{page_pdf}" target="_blank">{page_pdf_label}</a>'

    nav_btns = f"""
    <div class="nav-btns">
        <div class="dropdown">
            <button class="nav-btn" style="background: var(--gray-200); color: var(--text);"><i class="fas fa-file-pdf"></i></button>
            <div class="dropdown-content">
                {dropdown_content}
            </div>
        </div>
        <button id="btn_top" class="nav-btn">Top <i class="fas fa-arrow-up"></i></button>
    </div>
    """

    # Issue 1: Determine body class for dependency graph
    body_class = ""
    if "Dependency" in title:
        body_class = "page-depgraph"
    
    extra_styles = ""
    if "Bibliography" in title:
        extra_styles += '.container { max-width: 100% !important; padding: 0 !important; }'
    
    # Handle optional Bibliography-specific wrapper removal if needed by keeping it simple
    # But since render_page_html enforces a .card, we use it for consistency.
    # The prompt asked for "The exact CSS/JS blocks... Sidebar Container... Floating Buttons"
    # calling render_page_html achieves this.
    
    html = render_page_html(
        title=title,
        body_content=f'<h1>{title}</h1>{body}',
        sidebar_html=sidebar,
        nav_buttons_html=nav_btns,
        extra_styles=extra_styles,
        is_aux=True,
        body_class=body_class
    )
    
    out = Path("html_output") / filename
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding='utf-8')

def discover_chapters():
    global CHAPTERS
    CHAPTERS = []
    files = sorted(Path("html_output").glob("Chapter_*_Lecture_*.html"))
    for f in files:
        m = re.match(r'Chapter_(\d+)_Lecture_\d+_(.*)\.html', f.name)
        if m:
            num = int(m.group(1))
            
            # Read content to find REAL title (preserves hyphens/punctuation)
            content = f.read_text(encoding='utf-8', errors='replace')
            # Look for <h2 class="chapterHead">...</h2>
            title_match = re.search(r'<h[12][^>]*class="[^"]*chapterHead[^"]*"[^>]*>(.*?)</h[12]>', content, re.IGNORECASE | re.DOTALL)
            
            if title_match:
                raw_title_html = title_match.group(1)
                # Remove anchors, spans, etc.
                clean_title = re.sub(r'<[^>]+>', '', raw_title_html)
                clean_title = clean_title.replace('\n', ' ').strip()
                # Remove "Lecture N" or "Lecture N:" prefix
                clean_title = re.sub(r'^Lecture\s+\d+:?\s*', '', clean_title, flags=re.IGNORECASE).strip()
                # Issue 4: Remove number prefix "24.1 " if mistakenly captured (Must have a dot to avoid stripping "3D")
                clean_title = re.sub(r'^\d+\.\d+\s+', '', clean_title).strip()
                print(f"DEBUG: Found content title for Ch {num}: '{clean_title}' (Raw: '{raw_title_html}')")
            else:
                # Fallback to filename if parsing fails
                # Preserve hyphens: replace underscores but keep dashes intact
                clean_title = m.group(2).replace('_', ' ')
                # Fix common patterns: "SelfSupervised" -> "Self-Supervised"
                clean_title = re.sub(r'([a-z])([A-Z])', r'\1-\2', clean_title)
                print(f"DEBUG: Fallback title for Ch {num}: '{clean_title}' (No Match)")
                
            CHAPTERS.append({'num': num, 'title': clean_title, 'file': f.name, 'path': f})
    CHAPTERS.sort(key=lambda x: x['num'])

def fix_image_paths(content: str) -> str:
    """
    Scans content for <img> tags and fixes src attributes for Linux case sensitivity.
    Example: src="Figures/Chapter_1/Img.png" -> src="Figures/Chapter_1/img.png" (if that's the real file)
    Also normalizes chapter directory names: chapter_17 -> Chapter_17
    Also validates external links.
    """
    def repl(m):
        raw_src = m.group(1)
        # Skip external links
        if raw_src.startswith(('http:', 'https:', 'data:', '//')):
            return m.group(0)

        # Normalize chapter directory naming: chapter_N -> Chapter_N
        # This prevents duplication of figure directories in CI/CD
        normalized_src = re.sub(r'/chapter_(\d+)/', r'/Chapter_\1/', raw_src)
        was_normalized = normalized_src != raw_src
        if was_normalized:
            print(f"    [ImgFix] Normalized chapter dir: {raw_src} -> {normalized_src}")
            raw_src = normalized_src

        # Check explicit existence first
        full_path = HTML_OUTPUT_DIR / raw_src
        if full_path.exists():
            # If we normalized the path, return the normalized version
            if was_normalized:
                return f'src="{normalized_src}"'
            return m.group(0)
            
        # Path parts processing
        try:
            parts = Path(raw_src).parts
            current_dir = HTML_OUTPUT_DIR
            resolved_parts = []
            
            # Walk down the path verifying each component
            for part in parts:
                if not current_dir.exists():
                    return m.group(0) # Give up
                    
                # List dir entries case-insensitively
                found = False
                for entry in os.listdir(current_dir):
                    if entry.lower() == part.lower():
                        current_dir = current_dir / entry
                        resolved_parts.append(entry)
                        found = True
                        break
                
                if not found:
                    return m.group(0) # Give up logic
            
            # Reconstruct path
            new_src = "/".join(resolved_parts)
            if new_src != raw_src:
                print(f"    [ImgFix] {raw_src} -> {new_src}")
                return f'src="{new_src}"'
                
        except Exception as e:
            print(f"    [ImgWarn] Error fixing {raw_src}: {e}")
            
        return m.group(0)

    return re.sub(r'src="([^"]+)"', repl, content)




def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="", help="Base URL for GitHub Pages")
    args = parser.parse_args()
    
    global BASE_URL
    BASE_URL = args.base_url
    if BASE_URL:
        print(f"--> Using Base URL: {BASE_URL}")

    print(">>> Post-Processing (Surgical Merge v4)...")
    print("CREATE_NAVIGATION_VERSION=2026-01-16-ZERO-REGRESSION")
    discover_chapters()
    if not CHAPTERS: return
    
    target = None
    if 'ONLY_CHAPTER_NUM' in os.environ:
        t_num = int(os.environ['ONLY_CHAPTER_NUM'])
        target = [c for c in CHAPTERS if c['num'] == t_num]
    
    to_process = target if target else CHAPTERS

    # 1. Build Bibliography FIRST (Generates bibliography.html)
    if not target:
        build_bib()
    
    # 2. Load Index Map (Now bibliography.html exists)
    bib_path = Path("html_output/bibliography.html")
    load_bib_index_map(bib_path)

    # 3. Process Chapters
    for ch in to_process:
        process_chapter(ch['path'], ch)
        
    # Helper to extract inner content if wrapped
    def extract_inner_body(raw_html):
        candidate = raw_html
        
        # Priority 1: Content Markers
        m = re.search(r'<!-- content-start -->(.*?)<!-- content-end -->', raw_html, re.DOTALL)
        if m:
            candidate = m.group(1)
        
        # Priority 2: doc_content ID (if markers failed or we want to drill deeper)
        # Scan for the *last* occurrence of id="doc_content" to find the deepest nesting? 
        # Actually, let's just check if candidate is still wrapped.
        
        if 'id="sidebar"' in candidate or 'class="sidebar"' in candidate:
             # It's still wrapped (recursive case).
             m_nested = re.search(r'<!-- content-start -->(.*?)<!-- content-end -->', candidate, re.DOTALL)
             if m_nested:
                 return extract_inner_body(m_nested.group(1)) # Recurse
        
        # Reverted unsafe card-body strip. Trusted markers are sufficient.
            
        return candidate

        # If markers didn't clean it (e.g. sidebar is inside markers as seen in the bug),
        # validation check:
        if 'id="sidebar"' in candidate:
            # Recursive unwrap didn't work via markers (maybe markers are wrapping the sidebar?)
            # Force strip by regex targeting the structure
            # <aside ... </aside> ... <div class="main-wrapper"> ... <div id="doc_content"> ...
            m_deep = re.search(r'id="doc_content"[^>]*>(.*)', candidate, re.DOTALL)
            if m_deep:
                # We need to find the closing </div> for doc_content.
                # Since we can't count divs with regex, let's rely on content markers or </body> if present.
                pass
            
            # ULTIMATE FALLBACK: Dependency Graph Logic
            if "Dependency Graph" in candidate:
                 # Extract the image and title
                 m_img = re.search(r'(<img[^>]+>)', candidate)
                 if m_img:
                     return f"<div style='text-align:center; margin:2rem;'>{m_img.group(1)}</div>"
        
        # General Title Strip (Fix Double Title)
        # Strip the first H1 found, as generate_aux_page adds the main title.
        candidate = re.sub(r'<h1[^>]*>.*?</h1>', '', candidate, count=1, flags=re.DOTALL | re.IGNORECASE)

        return candidate

    if not target:
        # build_bib called above
        build_index()
        
        # Preface (Check root Preface.html FIRST to avoid reading stripped version)
        preface_src = Path("html_output/Preface.html")
        if not preface_src.exists():
             preface_src = Path("html_output/Auxiliary/Preface.html")
        
        # Fallback: Check if we can just define it if built by build_manager
        if preface_src.exists():
             raw = preface_src.read_text(encoding='utf-8', errors='replace')
             body = extract_inner_body(raw)
             
             # Cleanup for wrapping
             body = re.sub(r'<div class="crosslinks">.*?</div>', '', body, flags=re.DOTALL)
             # Preface might also have a double title issue
             body = re.sub(r'<h1.*?>.*?</h1>', '', body, count=1, flags=re.DOTALL | re.IGNORECASE)
             
             # SURGICAL PREFACE FIX: Strip everything before the first H2 to remove nested wrappers
             # The real content (including Contributors) starts with an H2
             m_pref = re.search(r'(<h2>.*)', body, re.DOTALL)
             if m_pref:
                 body = m_pref.group(1)
             
             # E3: Strip any leftover script tags from previous runs (generic chrome stripping)
             body = re.sub(r'<script[^>]*>.*?</script>', '', body, flags=re.DOTALL)
             
             body = protect_math(body)
             # R1: Fix escaped underscores (\_ -> _) in text, math is protected
             body = re.sub(r'(?<!\\)\\(?=_)', '', body)
             body = restore_math(body)
             # Fix image paths for Preface (nested in Auxiliary folder)
             # Handle both single and double quotes around src attribute
             body = re.sub(r'src="Pictures/', 'src="../Pictures/', body)
             body = re.sub(r"src='Pictures/", "src='../Pictures/", body)
             generate_aux_page("Preface", body, "Auxiliary/Preface.html")

        # Dependency Graph
        dep_src = Path("html_output/dependency_graph.html")
        dep_img = HTML_OUTPUT_DIR / "Pictures/book_dependencies.png"

        if dep_src.exists() or dep_img.exists():
             if dep_src.exists():
                 raw = dep_src.read_text(encoding='utf-8', errors='replace')
                 body = extract_inner_body(raw)
                 # Robust H1 Strip (Fix Double Title) for Dep Graph
                 body = re.sub(r'<h1.*?>.*?</h1>', '', body, count=1, flags=re.DOTALL | re.IGNORECASE)
                 body = protect_math(body)
                 body = restore_math(body)
                 # Fix image paths - dependency_graph.html is in root, not subdirectory
                 # So Pictures/ is direct child, not ../Pictures/
                 body = re.sub(r'src="\.\./Pictures/', 'src="Pictures/', body)
                 body = re.sub(r"src='\.\./Pictures/", "src='Pictures/", body)
             else:
                 # Generate from image if HTML missing
                 # Note: dependency_graph.html is in html_output/ root, so Pictures is a sibling
                 body = f'<img src="Pictures/book_dependencies.png" alt="Dependency Tree" class="depgraph-img" style="max-width:100%; height:auto;">'

             generate_aux_page("Dependency Graph", body, "dependency_graph.html")
    
    print(">>> Done.")

if __name__ == '__main__':
    main()