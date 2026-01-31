#!/usr/bin/env python3
"""
Post-Processor Package for CVBook HTML Generation
==================================================

This package transforms raw TeX4ht-generated HTML into polished, 
responsive web pages with navigation, styling, and SEO features.

Modules:
    - config: Configuration constants and global state
    - math_protection: LaTeX math tokenization and restoration
    - sidebar: Navigation sidebar generation
    - utils: Utility functions (text normalization, image paths, etc.)
    - toc_extractor: Table of contents extraction from chapters
    - page_renderer: Unified HTML page generation
    
Usage:
    from post_processor import run
    run()  # With default arguments
    
    # Or with custom base URL:
    run(base_url="/CVBook")
"""

__version__ = "2.0.0"
__author__ = "CVBook Team"

import sys
import os

# Add parent directory to path to allow importing original script
_parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _parent_dir not in sys.path:
    sys.path.insert(0, _parent_dir)


def run(base_url: str = "") -> None:
    """
    Run the full post-processing pipeline.
    
    This is the main entry point that processes all HTML files,
    generates navigation, bibliography, and auxiliary pages.
    
    Args:
        base_url: Base URL for GitHub Pages deployment (e.g., "/CVBook").
                  Leave empty for local filesystem browsing.
    """
    # Import the core module (formerly create_navigation.py)
    from . import core
    
    # Override BASE_URL if provided
    if base_url:
        core.BASE_URL = base_url
        print(f"--> Using Base URL: {base_url}")
    
    # Run the main processing function
    core.main()


def run_with_args() -> None:
    """
    Run post-processing with command-line arguments.
    This is the CLI entry point.
    """
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Post-process CVBook HTML files with navigation, styling, and SEO.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python -m post_processor                    # Local development
    python -m post_processor --base-url /CVBook # GitHub Pages deployment
        """
    )
    parser.add_argument(
        "--base-url", 
        default="", 
        help="Base URL for GitHub Pages (e.g., '/CVBook')"
    )
    
    args = parser.parse_args()
    run(base_url=args.base_url)


# Export key functions and classes for direct imports
from .config import (
    HTML_OUTPUT_DIR,
    CHAPTERS,
    BIB_INDEX_MAP,
    set_base_url,
    get_base_url,
)

from .math_protection import (
    protect_math,
    restore_math,
    clean_latex_artifacts,
)

from .utils import (
    normalize_text,
    load_bib_index_map,
    discover_chapters,
    fix_image_paths,
    validate_output_safety,
)

from .sidebar import (
    build_sidebar,
    get_asset_url,
)

from .toc_extractor import (
    extract_toc_from_body,
)

from .page_renderer import (
    render_page_html,
)


__all__ = [
    # Main entry points
    'run',
    'run_with_args',
    # Config
    'HTML_OUTPUT_DIR',
    'CHAPTERS', 
    'BIB_INDEX_MAP',
    'set_base_url',
    'get_base_url',
    # Math protection
    'protect_math',
    'restore_math',
    'clean_latex_artifacts',
    # Utils
    'normalize_text',
    'load_bib_index_map',
    'discover_chapters',
    'fix_image_paths',
    'validate_output_safety',
    # Sidebar
    'build_sidebar',
    'get_asset_url',
    # TOC
    'extract_toc_from_body',
    # Renderer
    'render_page_html',
]
