#!/usr/bin/env python3
"""
scripts/build_bib_pdf.py (Refactored)

Goal: Robustly build Bibliography.pdf from source (using a wrapper) with Heartbeat monitoring.
Prevent deadlocks during pdflatex/biber execution.

Logic:
1. Create a minimal wrapper .tex file (citations only).
2. Run pdflatex -> biber -> pdflatex -> pdflatex.
3. Monitor process with Heartbeat (kill if 60s no IO).
4. Verify final page count (Expect ~58).

Usage:
  python3 scripts/build_bib_pdf.py --out html_output/downloads/Bibliography.pdf
"""

import sys
import os
import time
import shutil
import re
import subprocess
import argparse
from pathlib import Path
from typing import List, Optional

# ----------------------------
# Constants
# ----------------------------
HEARTBEAT_TIMEOUT = 60    # Kill if no file changes for 60s
HARD_TIMEOUT = 300        # 5 Minutes Max for the whole build (or per step)
EXPECTED_PAGES = 58

# ----------------------------
# Heartbeat Monitor
# ----------------------------
class HeartbeatMonitor:
    def __init__(self, watch_dir: Path, timeout: float = HEARTBEAT_TIMEOUT):
        self.watch_dir = watch_dir
        self.timeout = timeout
        self.last_activity = time.time()
        self.initial_files = self._scan_files()

    def _scan_files(self) -> dict:
        """Return map of file -> mtime for all files in watch dir + subdirs."""
        state = {}
        try:
            for p in self.watch_dir.rglob("*"):
                if p.is_file():
                    try:
                        state[p] = p.stat().st_mtime
                    except OSError:
                        pass
        except OSError:
            pass
        return state

    def check(self) -> bool:
        """Returns True if alive (activity detected or within timeout), False if stalled."""
        current_state = self._scan_files()
        activity_detected = False

        if set(current_state.keys()) != set(self.initial_files.keys()):
            activity_detected = True
        else:
            for p, mtime in current_state.items():
                if p in self.initial_files and mtime > self.initial_files[p]:
                    activity_detected = True
                    break
        
        if activity_detected:
            self.last_activity = time.time()
            self.initial_files = current_state
            return True
        
        # No activity
        elapsed = time.time() - self.last_activity
        return elapsed < self.timeout
    
    def touch(self):
        self.last_activity = time.time()
    
    def time_since_activity(self) -> float:
        return time.time() - self.last_activity

# ----------------------------
# Process Execution
# ----------------------------
def _run_cmd_robust(cmd: List[str], cwd: Path, log_path: Path, strict: bool = True) -> None:
    """Run command with Heartbeat monitoring."""
    print(f"   [EXEC] {' '.join(cmd)}")
    
    # Open log file
    with open(log_path, "w", encoding="utf-8") as f_log:
        proc = subprocess.Popen(
            cmd,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1 # Line buffered
        )

        monitor = HeartbeatMonitor(cwd, HEARTBEAT_TIMEOUT)
        start_time = time.time()
        last_check = time.time()

        try:
            while True:
                ret = proc.poll()
                line = proc.stdout.readline()

                if line:
                    monitor.touch()
                    f_log.write(line)
                    # Optional: Active Error Scanning could be added here
                    if "! LaTeX Error" in line or "! Emergency stop" in line:
                         proc.kill()
                         raise RuntimeError(f"LaTeX Error detected: {line.strip()}")
                else:
                    if ret is not None:
                        break
                    time.sleep(0.05)

                # Timeouts
                now = time.time()
                if (now - start_time) > HARD_TIMEOUT:
                    proc.kill()
                    raise TimeoutError(f"HARD TIMEOUT ({HARD_TIMEOUT}s) exceeded.")

                if (now - last_check) > 2.0: # Check activity every 2s
                    monitor.check()
                    last_check = now
                    since = monitor.time_since_activity()
                    if since > HEARTBEAT_TIMEOUT:
                        proc.kill()
                        raise TimeoutError(f"STALLED (No disk activity for {since:.1f}s).")
        
        except Exception as e:
            if proc.poll() is None:
                proc.kill()
            raise e

    if proc.returncode != 0:
        msg = f"Command failed with code {proc.returncode}. See {log_path.name}"
        if strict:
            raise RuntimeError(msg)
        else:
            print(f"   [WARN] {msg} (strict=False, proceeding)")


# ----------------------------
# Citation Scanning
# ----------------------------


# ----------------------------
# Citation Scanning
# ----------------------------
def _scan_citations(repo_root: Path) -> set[str]:
    """Scans .tex files for citation keys to include only used references."""
    cited_keys = set()
    # Regex handles:
    # \cite{key}, \parencite{key}, \textcite[p.1]{key}, \cite{k1, k2}
    # Commands: cite, parencite, textcite, supercite, autocite, citeauthor, citetitle, citeyear, footcite, fullcite
    # Pattern explanation:
    # \\(?:...): match command starting with \
    # (?:\[.*?\]){0,2}: match 0 to 2 optional arguments [opt]
    # \{([^}]+)\}: match content inside {}
    # Generic regex to match ANY command containing 'cite' (e.g., \cite, \citet, \citeyearpar, \footcite)
    # This is more robust than a hardcoded list.
    # Pattern: \ + (letters) + cite + (letters) + [opt] + {key}
    pattern_str = r"(?i)\\([a-zA-Z]*cite[a-zA-Z]*)(?:(?:\s*\[.*?\]){0,2})\s*\{([^\}]+)\}"
    cite_pattern = re.compile(pattern_str)
    
    # Files to scan: RECURSIVELY all .tex files in repo_root
    # Exclude .bib_build_temp and dot folders
    files_to_scan = []
    for p in repo_root.rglob("*.tex"):
        if ".bib_build_temp" in p.parts or ".git" in p.parts or "scripts" in p.parts:
            continue
        # Also exclude the generated wrapper if it exists in root (unlikely but safe)
        if p.name == "bibliography_standalone.tex":
            continue
        files_to_scan.append(p)
    
    print(f"[build_bib_pdf] Scanning {len(files_to_scan)} files for citations...")
    
    for tex_file in files_to_scan:
        if not tex_file.exists():
            continue
            
        try:
            content = tex_file.read_text(encoding="utf-8", errors="replace")
            # Simple comment removal: remove from % to end of line, if not escaped
            lines = content.splitlines()
            cleaned_lines = []
            for line in lines:
                # Remove comments starting with % (ignoring \%)
                # Heuristic: split by % then check if preceding char is \
                # Better heuristic for this context:
                # If % exists, check backslash.
                if "%" in line:
                    # Find first occurrence of % not preceded by \
                    parts = re.split(r"(?<!\\)%", line, maxsplit=1)
                    cleaned_lines.append(parts[0])
                else:
                    cleaned_lines.append(line)
            
            cleaned_content = "\n".join(cleaned_lines)
            
            for match in cite_pattern.finditer(cleaned_content):
                # group(1) is the command name, group(2) is the key string
                keys_str = match.group(2)
                # Split by comma
                for k in keys_str.split(","):
                    k = k.strip()
                    if k and k != "*":
                        cited_keys.add(k)
                        
        except Exception as e:
            print(f"[WARN] Failed to scan {tex_file.name}: {e}")

    print(f"[build_bib_pdf] Found {len(cited_keys)} unique cited keys.")
    return cited_keys


# ----------------------------
# Wrapper Generation
# ----------------------------
def _create_bib_wrapper(cwd: Path, cited_keys: set[str]) -> Path:
    wrapper = cwd / "bibliography_standalone.tex"
    
    if not cited_keys:
        print("[WARN] No citations found! Fallback to \\nocite{*}")
        nocite_line = r"\nocite{*} % Fallback: Include ALL references"
    else:
        # Join keys with commas to create specific nocite
        keys_str = ",".join(sorted(cited_keys))
        nocite_line = f"\\nocite{{{keys_str}}}"

    content = r"""
\DocumentMetadata{}
\documentclass[11pt,fleqn,openany]{book}
\raggedbottom
\usepackage[top=3cm,bottom=3cm,left=3.2cm,right=3.2cm,headsep=10pt,letterpaper]{geometry}
\usepackage[dvipsnames]{xcolor}
\definecolor{ocre}{RGB}{52,177,201}
\usepackage{avant}
\usepackage{mathptmx}
\usepackage{microtype}
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage{amsthm}
\usepackage{bm}
\usepackage{enumitem}
\usepackage[backend=biber,style=numeric,sortcites,sorting=nty,backref,natbib,hyperref]{biblatex}
\usepackage{csquotes}
\addbibresource{bibliography.bib}
\defbibheading{bibempty}{}
\input{structure}
\chapterimage{head1.png} % Required to prevent empty filename error in structure.tex

% Basic defs from main.tex to avoid errors
\def\R{\mathbb{R}}
\newcommand{\ind}{\mathbf{1}}
\newcommand{\cvx}{convex}
\usepackage{pifont}
\newcommand{\cmark}{\ding{51}}
\newcommand{\xmark}{\ding{55}}

\begin{document}
""" + nocite_line + r"""
\printbibliography[heading=bibintoc,title={Bibliography}]
\end{document}
"""
    wrapper.write_text(content, encoding="utf-8")
    return wrapper

# ----------------------------
# Parse Page Count
# ----------------------------
def _get_page_count(log_file: Path) -> int:
    if not log_file.exists():
        return 0
    text = log_file.read_text(encoding="utf-8", errors="replace")
    # Pattern: Output written on xxx.pdf (58 pages, ...
    m = re.search(r"Output written on .*? \((\d+) pages", text)
    if m:
        return int(m.group(1))
    return 0

# ----------------------------
# Main
# ----------------------------
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="html_output/downloads/Bibliography.pdf", help="Output PDF path")
    # Legacy args to prevent breaking callers
    parser.add_argument("--main-pdf", help="Ignored (Legacy)")
    parser.add_argument("--toc", help="Ignored (Legacy)")
    parser.add_argument("--log", help="Ignored (Legacy)")
    
    args = parser.parse_args()
    
    out_path = Path(args.out).resolve()
    repo_root = Path(__file__).resolve().parent.parent
    
    # Setup working dir
    work_dir = repo_root / ".bib_build_temp"
    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"[build_bib_pdf] Starting Robust Build in {work_dir}")
    
    try:
        # 1. Copy dependencies
        # Need: structure.tex, bibliography.bib, StyleInd.ist
        for f in ["structure.tex", "bibliography.bib"]:
            src = repo_root / f
            if src.exists():
                shutil.copy2(src, work_dir / f)
            else:
                raise FileNotFoundError(f"Missing dependency: {f}")
        
        # Copy Pictures folder (required for structure.tex/chapterimage)
        pics_src = repo_root / "Pictures"
        pics_dst = work_dir / "Pictures"
        if pics_src.exists():
            if pics_dst.exists():
                shutil.rmtree(pics_dst)
            shutil.copytree(pics_src, pics_dst)
        
        # 2. Scan Citations
        cited_keys = _scan_citations(repo_root)

        # 3. Create Wrapper
        wrapper_tex = _create_bib_wrapper(work_dir, cited_keys)
        jobname = wrapper_tex.stem # bibliography_standalone
        
        # 3. Build Sequence
        # pdflatex -> biber -> pdflatex -> pdflatex
        # pdflatex -> biber -> pdflatex -> pdflatex
        common_flags = ["-interaction=nonstopmode"]
        
        # Inject Memory Settings Globaly
        os.environ["TEXMFCNF"] = str(repo_root) + ":"
        
        # Pass 1: PDFLaTeX
        print(">>> Pass 1: PDFLaTeX")
        _run_cmd_robust(
            ["pdflatex"] + common_flags + [wrapper_tex.name],
            work_dir,
            work_dir / "pass1.log",
            strict=False
        )
        
        # Pass 2: Biber
        print(">>> Pass 2: Biber")
        _run_cmd_robust(
            ["biber", jobname],
            work_dir,
            work_dir / "biber.log"
        )
        
        # Pass 3: PDFLaTeX
        print(">>> Pass 3: PDFLaTeX")
        _run_cmd_robust(
            ["pdflatex"] + common_flags + [wrapper_tex.name],
            work_dir,
            work_dir / "pass3.log",
            strict=False
        )
        
        # Pass 4: PDFLaTeX (Final)
        print(">>> Pass 4: PDFLaTeX (Final)")
        final_log = work_dir / "pass4.log"
        _run_cmd_robust(
            ["pdflatex"] + common_flags + [wrapper_tex.name],
            work_dir,
            final_log,
            strict=False
        )
        
        # 4. Verify
        generated_pdf = work_dir / f"{jobname}.pdf"
        if not generated_pdf.exists():
             raise RuntimeError("Final PDF not found.")
        
        count = _get_page_count(final_log)
        print(f"[SUCCESS] Bibliography built. Total Pages: {count}")
        
        if count == 0:
            print("[WARNING] Page count detected as 0. Check logs.")
        elif abs(count - EXPECTED_PAGES) > 10:
             print(f"[WARNING] Expected ~{EXPECTED_PAGES} pages, got {count}.")
             
        # 5. Move Output
        out_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(generated_pdf, out_path)
        print(f"[DONE] Saved to {out_path}")
        
    except Exception as e:
        print(f"[ERROR] Build Failed: {e}")
        # Identify stalling log
        sys.exit(1)
    finally:
        # Cleanup? 
        # shutil.rmtree(work_dir) 
        # Leave for debugging if failed?
        pass

if __name__ == "__main__":
    main()
