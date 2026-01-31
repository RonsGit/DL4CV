#!/usr/bin/env python3
"""
Page renderer - unified HTML page generation.
The single source of truth for creating HTML page skeletons.
"""
import re
from . import config


def render_page_html(title: str, body_content: str, sidebar_html: str, nav_buttons_html: str,
                     bottom_nav_html: str = "", extra_styles: str = "", is_aux: bool = False, 
                     body_class: str = "", common_head_fn=None, js_footer_fn=None) -> str:
    """
    Unified page renderer - THE ONLY function that creates the HTML skeleton.
    Includes the Shared Layout: Sidebar, Sticky Top Bar, Floating Buttons (via JS), and Content Card.
    
    Args:
        title: Page title
        body_content: Main content HTML
        sidebar_html: Sidebar navigation HTML
        nav_buttons_html: Top navigation buttons HTML
        bottom_nav_html: Bottom navigation HTML (prev/next chapters)
        extra_styles: Additional CSS styles
        is_aux: Whether this is an auxiliary page
        body_class: Additional CSS class for body element
        common_head_fn: Function to generate <head> content (injected to avoid circular imports)
        js_footer_fn: Function to generate JS footer (injected to avoid circular imports)
    """
    # These functions should be passed in from templates module
    head_html = common_head_fn(title, is_aux) if common_head_fn else ""
    js_html = js_footer_fn() if js_footer_fn else ""
    
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    {head_html}
    <style>{extra_styles}</style>
</head>
<body id="page-top-body" class="{body_class}">
    <aside class="sidebar" id="sidebar">
        <div class="resize-handle" id="sidebar_resizer"></div>
        {sidebar_html}
    </aside>
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
                    <div class="card-body" id="doc_content">
                        <!-- content-start -->
                        {body_content}
                        <!-- content-end -->
                    </div>
                    {bottom_nav_html}
                </div>
            </div>
        </main>
    </div>
    {js_html}
</body>
</html>"""


def validate_output_safety(html_content: str, filename: str) -> tuple:
    """
    Validates that output HTML is safe to write (not empty/corrupted).
    Returns: (is_safe: bool, error_message: str)
    """
    # Check 1: Exactly one doc_content
    doc_content_count = html_content.count('id="doc_content"')
    if doc_content_count != 1:
        return False, f"Invalid doc_content count: {doc_content_count} (expected 1)"
    
    # Check 2: Extract content and verify length using content markers
    match = re.search(r'<!-- content-start -->(.*?)<!-- content-end -->', html_content, re.DOTALL)
    if not match:
        if len(html_content) < 5000:
            return False, f"Total HTML too short: {len(html_content)} chars"
        content = html_content
    else:
        content = match.group(1)
        content_len = len(content)
        if content_len < config.MIN_CONTENT_LENGTH:
            return False, f"Content too short: {content_len} chars (minimum {config.MIN_CONTENT_LENGTH})"
    
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
    
    return True, ""
