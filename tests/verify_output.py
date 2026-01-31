#!/usr/bin/env python3
import argparse
import glob
import os
import re
import sys
from typing import List, Tuple


def find_html_files(publish_dir: str) -> List[str]:
    return sorted(glob.glob(os.path.join(publish_dir, "**", "*.html"), recursive=True))


def read_file_text(path: str) -> str:
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()


def contains_mathjax(html_text: str) -> bool:
    low = html_text.lower()
    return (
        ("mathjax" in low)
        or ("tex-mml-chtml.js" in low)
        or ("tex-chtml-full.js" in low)
    )


def extract_img_srcs(html_text: str) -> List[str]:
    # Simple regex to extract src attributes from <img> tags
    pattern = re.compile(r"<img[^>]+src=[\"\']([^\"\']+)[\"\']", re.IGNORECASE)
    return pattern.findall(html_text)


def is_external_or_data_url(path: str) -> bool:
    p = path.lower()
    return p.startswith("http://") or p.startswith("https://") or p.startswith("data:")


def resolve_candidate_paths(html_file: str, src: str, publish_dir: str) -> List[str]:
    candidates = []
    # Relative to the HTML file directory
    candidates.append(os.path.normpath(os.path.join(os.path.dirname(html_file), src)))
    # Relative to the publish dir root
    candidates.append(os.path.normpath(os.path.join(publish_dir, src)))
    # If src includes directories, also try just the basename at root
    candidates.append(os.path.normpath(os.path.join(publish_dir, os.path.basename(src))))
    return candidates


def check_images_exist(html_files: List[str], publish_dir: str) -> Tuple[bool, List[Tuple[str, str]]]:
    missing: List[Tuple[str, str]] = []
    for html_file in html_files:
        html_text = read_file_text(html_file)
        img_srcs = extract_img_srcs(html_text)
        for src in img_srcs:
            if is_external_or_data_url(src):
                continue
            found = False
            for cand in resolve_candidate_paths(html_file, src, publish_dir):
                if os.path.exists(cand):
                    found = True
                    break
            if not found:
                missing.append((html_file, src))
    return (len(missing) == 0, missing)


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify make4ht HTML output for GitHub Pages")
    parser.add_argument("--publish-dir", default="out", help="Directory with generated site files")
    args = parser.parse_args()

    publish_dir = os.path.abspath(args.publish_dir)
    if not os.path.isdir(publish_dir):
        print(f"ERROR: publish directory not found: {publish_dir}", file=sys.stderr)
        return 2

    html_files = find_html_files(publish_dir)
    if not html_files:
        print(f"ERROR: No HTML files found in {publish_dir}", file=sys.stderr)
        return 2

    # Select primary HTML
    primary_html = next((p for p in html_files if os.path.basename(p) == "index.html"), html_files[0])
    primary_text = read_file_text(primary_html)

    # Check MathJax
    if not contains_mathjax(primary_text):
        print(f"ERROR: MathJax not detected in {primary_html}", file=sys.stderr)
        return 3

    # Check images
    ok_images, missing = check_images_exist(html_files, publish_dir)
    if not ok_images:
        print("ERROR: Missing image assets referenced by HTML:", file=sys.stderr)
        for html_file, src in missing[:50]:  # limit to avoid huge logs
            print(f"  {html_file} -> {src}", file=sys.stderr)
        if len(missing) > 50:
            print(f"  ... and {len(missing) - 50} more", file=sys.stderr)
        return 4

    # All checks passed
    print(f"OK: {len(html_files)} HTML files validated in {publish_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())


