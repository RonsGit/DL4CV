#!/usr/bin/env python3
"""
CVBook HTML Post-Processor
==========================

Transforms raw TeX4ht-generated HTML into polished, responsive web pages
with navigation, styling, search, and SEO features.

This script is the CLI entry point that replaces the old create_navigation.py.
It provides the same functionality with a cleaner interface.

Usage:
    python run_post_processor.py                    # Local development
    python run_post_processor.py --base-url /CVBook # GitHub Pages deployment

Features:
    - Navigation sidebar with chapter links
    - Responsive table of contents
    - MathJax math rendering
    - Syntax-highlighted code blocks
    - Bibliography with formatted citations
    - Full-text search via Pagefind
    - Mobile-friendly responsive design
"""

import sys
import os

# Ensure the scripts directory is in the path
script_dir = os.path.dirname(os.path.abspath(__file__))
if script_dir not in sys.path:
    sys.path.insert(0, script_dir)


def main():
    """Main entry point for the post-processor."""
    from post_processor import run_with_args
    run_with_args()


if __name__ == "__main__":
    main()
