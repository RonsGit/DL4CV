#!/usr/bin/env python3
"""
Post-processor configuration and global state.
Shared across all post-processor modules.
"""
from pathlib import Path

# --- CONFIGURATION ---
BASE_URL = ""  # Set via --base-url argument
HTML_OUTPUT_DIR = Path("html_output")

# --- GLOBAL STATE (populated at runtime) ---
BIB_MAPPING = {}
BIB_DATA = {}
BIB_INDEX_MAP = {}  # Maps normalized bib key -> global bibliography number
CHAPTERS = []

# --- CONSTANTS ---
LIGATURES = {
    'ﬀ': 'ff', 'ﬂ': 'fl', 'ﬃ': 'ffi', 'ﬄ': 'ffl', 'ﬁ': 'fi', 'ﬅ': 'st'
}

# Content safety guardrails
MIN_CONTENT_LENGTH = 500  # Minimum characters to prevent content wiping


def set_base_url(url: str):
    """Set the base URL for asset paths."""
    global BASE_URL
    BASE_URL = url


def get_base_url() -> str:
    """Get the current base URL."""
    return BASE_URL
