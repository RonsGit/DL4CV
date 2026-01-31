#!/usr/bin/env bash
set -euo pipefail

# Robust root detection (works whether this script lives in repo root or scripts/)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$SCRIPT_DIR"
if [[ -d "$ROOT/scripts" && -f "$ROOT/main.tex" ]]; then
  :
elif [[ -f "$SCRIPT_DIR/../main.tex" ]]; then
  ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
fi

cd "$ROOT"

PY="python3"
if ! command -v "$PY" >/dev/null 2>&1; then
  PY="python"
fi

echo "=== Build Site (root=$ROOT) ==="

# 1) Build (PDF + chapter HTML + auxiliary raw pages)
$PY scripts/build_manager.py --out-dir html_output

# 2) Split chapter PDFs (stop before bibliography; also Preface.pdf if possible)
$PY scripts/split_pdf.py --main-pdf html_output/downloads/main.pdf --toc html_output/main.toc --out-dir html_output/downloads

# 3) Deterministic Bibliography.pdf extraction
$PY scripts/build_bib_pdf.py --main-pdf html_output/downloads/main.pdf --toc html_output/main.toc --out html_output/downloads/Bibliography.pdf

# 4) Wrap pages + navigation + strip bib from chapters + generate bibliography.html + index.html
$PY scripts/create_navigation.py --out-dir html_output

# 5) Pagefind index (optional)
if command -v pagefind >/dev/null 2>&1; then
  echo "=== Pagefind indexing ==="
  pagefind --site html_output --output-path html_output/pagefind
else
  echo "=== Pagefind not installed; skipping index ==="
fi

# 6) Verify strictly (no PDF page count assertions)
$PY scripts/verify_strict.py --out-dir html_output

echo "=== DONE ==="
