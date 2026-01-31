#!/usr/bin/env python3
r"""
scripts/build_manager.py (Gatekeeper Edition)

Goal: Convert Chapters 1-24 to HTML without Deadlocks.

Strategy:
1.  **Gatekeeper**: Chapter 22 runs FIRST. If it fails -> ABORT ALL.
2.  **Active Error Scanning**: Scan `make4ht` output line-by-line. Kill immediately on:
    - "! LaTeX Error"
    - "! Emergency stop"
    - "Fatal error occurred"
    - "^Error:"
3.  **Heartbeat**: Fallback monitor (kill if no file changes for 60s).
4.  **Clean Room**: Inject shim preamble to bypass PDF structure issues.
5.  **Sanitization**: Recursive `\text{...}` -> `\mbox{...}` in math.
6.  **Deployment**: Immediate sync of artifacts (HTML/CSS/Images) to html_output.
"""

import argparse
import datetime
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Iterable

# Try importing tqdm for progress bars
try:
    from tqdm import tqdm
except ImportError:
    def tqdm(iterable: Iterable, desc: str = "", unit: str = "") -> Iterable:
        print(f"--- {desc} ---")
        return iterable

# ----------------------------
# Constants & Configuration
# ----------------------------

HEARTBEAT_TIMEOUT_SECONDS = 60  # No disk activity for 60s = DEAD
HARD_TIMEOUT_SECONDS = 7200     # 2 hours max per chapter/file
POLL_INTERVAL = 0.1             # Check output frequently

# Strings that trigger IMMEDIATE death
KILL_STRINGS = [
    "! LaTeX Error",
    "! Emergency stop",
    "Fatal error occurred"
]

VERBATIM_ENVS = (
    "minted", "mintedbox", "Verbatim", "verbatim", "lstlisting", "lstlisting*", "BVerbatim"
)

# Shim Preamble to replace structure.tex
CLEAN_STRUCTURE_LATEX = r"""
% AUTO-GENERATED: structure_html.tex
% A clean preable for HTML generation.

\usepackage{amsmath,amssymb,amsfonts,amsthm}
\usepackage{graphicx}
\usepackage{caption}
\usepackage[dvipsnames,svgnames,table]{xcolor}
\usepackage{enumitem,booktabs,array,longtable,float}
\usepackage{xparse,fancyvrb,etoolbox,xstring}
\usepackage[hidelinks]{hyperref}

% Colors
\definecolor{ocre}{RGB}{52,177,201}

% Symbols
\usepackage{pifont}
\providecommand{\cmark}{\ding{51}} 
\providecommand{\xmark}{\ding{55}}

% References
\usepackage[backend=biber,style=numeric,sorting=none,maxbibnames=99,natbib=true]{biblatex}
\addbibresource{bibliography.bib}

% --- Environment Shim Definitions ---

% 1. Code Blocks (Fallbacks)
\NewDocumentEnvironment{minted}{O{} m}{\Verbatim}{\endVerbatim}
\NewDocumentEnvironment{mintedbox}{O{} m}{\Verbatim}{\endVerbatim}
\DeclareRobustCommand{\mintinline}[2]{\texttt{#2}}
\providecommand{\inputminted}[3][]{\VerbatimInput{#3}}

% 2. TColorBox (Strip formatting, keep content)
\NewDocumentEnvironment{tcolorbox}{O{}}{\par\smallskip\noindent}{\par\smallskip}
\providecommand{\tcbset}[1]{}
\providecommand{\tcblower}{\par\medskip}
\providecommand{\newtcolorbox}[4][]{}
\providecommand{\newtcblisting}[4][]{}

% 3. Enrichment (Use proper sectioning based on level parameter)
% The second optional argument O{subsection} determines heading level: section, subsection, or subsubsection
% We step the counter and call the starred version + addcontentsline for proper TOC and HTML h-tag generation
\NewDocumentEnvironment{enrichment}{ O{} O{subsection} }{%
    \IfStrEqCase{#2}{%
        {section}{\stepcounter{section}\section*{\color{ocre}Enrichment \thesection: #1}\addcontentsline{toc}{section}{\protect\numberline{\thesection}Enrichment: #1}}%
        {subsection}{\stepcounter{subsection}\subsection*{\color{ocre}Enrichment \thesubsection: #1}\addcontentsline{toc}{subsection}{\protect\numberline{\thesubsection}Enrichment: #1}}%
        {subsubsection}{\stepcounter{subsubsection}\subsubsection*{\color{ocre}Enrichment \thesubsubsection: #1}\addcontentsline{toc}{subsubsection}{\protect\numberline{\thesubsubsection}Enrichment: #1}}%
    }[\subsection*{\color{ocre}Enrichment: #1}]% Default fallback
    \par\noindent\hrulefill\par
}{%
    \par\hrulefill\par\medskip
}

% 4. Theorems & friends
\newtheoremstyle{simple}{3pt}{3pt}{\normalfont}{}{\bfseries\color{ocre}}{}{0.5em}{}
\theoremstyle{simple}

\newtheorem{theorem}{Theorem}[chapter]
\newtheorem{lemma}[theorem]{Lemma}
\newtheorem{proposition}[theorem]{Proposition}
\newtheorem{corollary}[theorem]{Corollary}
\newtheorem{definition}[theorem]{Definition}
\newtheorem{example}[theorem]{Example}
\newtheorem{exercise}{Exercise}[chapter]
\newtheorem{remark}[theorem]{Remark}
\newtheorem{claim}[theorem]{Claim}
\newtheorem{fact}[theorem]{Fact}
\newtheorem{observation}[theorem]{Observation}
\newtheorem{problem}{Problem}[chapter]
\newtheorem{vocabulary}{Vocabulary}[chapter]

% 5. Misc Utils
\providecommand{\chapterimage}[1]{}
\providecommand{\mathrm}[1]{#1}
\providecommand{\cleardoublepage}{}
\providecommand{\clearpage}{}
\providecommand{\raggedbottom}{}
\providecommand{\DocumentMetadata}[1]{}
""".lstrip()


# ----------------------------
# Build Context
# ----------------------------

@dataclass
class BuildPaths:
    repo_root: Path
    staging: Path
    out_dir: Path
    logs_dir: Path
    html_dir: Path
    shims_dir: Path


def _init_paths(out_dir: Path) -> BuildPaths:
    repo = Path(__file__).resolve().parent.parent
    out_dir = out_dir.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    
    logs_dir = out_dir / "Auxiliary" / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    
    # We use a fixed staging area to allow clearing it easily, 
    # but append a timestamped subdir for this specific run if needed.
    staging = repo / ".staging" / "active_build"
    if staging.exists():
        try:
            shutil.rmtree(staging)
        except OSError:
            pass # Windows file locking might prevent full cleanup immediately
    staging.mkdir(parents=True, exist_ok=True)
    
    shims_dir = staging / ".shims"
    shims_dir.mkdir(parents=True, exist_ok=True)

    return BuildPaths(
        repo_root=repo,
        staging=staging,
        out_dir=out_dir,
        logs_dir=logs_dir,
        html_dir=out_dir,
        shims_dir=shims_dir,
    )


def _setup_staging(paths: BuildPaths) -> None:
    print("--> Setting up Clean Room (Staging)...")
    
    # Copy source folders
    for folder in ["Chapters", "Figures", "Auxiliary", "Pictures"]:
        src = paths.repo_root / folder
        dst = paths.staging / folder
        if src.exists():
             shutil.copytree(src, dst, dirs_exist_ok=True)

    # Copy key files
    for f in ["main.tex", "structure.tex", "bibliography.bib", "tex4ht_mathjax.cfg", "StyleInd.ist"]:
        src = paths.repo_root / f
        if src.exists():
            shutil.copy2(src, paths.staging / f)
            
    # CI Shim: Case-sensitivity fix for Figures/ vs figures/
    # LaTeX code uses 'figures/', but repo has 'Figures/'.
    # On Linux (CI), this fails. We create a symlink or copy to bridge it.
    figures_cap = paths.staging / "Figures"
    figures_lower = paths.staging / "figures"
    
    if figures_cap.exists() and not figures_lower.exists():
        try:
            if os.name == "posix": # Symlinks work best on Linux/Mac
                os.symlink("Figures", figures_lower)
                print("   [Shim] Created symlink figures -> Figures")
            else: # Windows or fallback
                # Symlinks often require admin on Windows, so we copy (safe in staging)
                shutil.copytree(figures_cap, figures_lower)
                print("   [Shim] Created copy figures -> Figures")

            # Recursive Shim: Create lowercase symlinks for LaTeX PDF compilation
            # LaTeX sources use chapter_N paths, so we need symlinks in staging
            # HTML post-processor normalizes all paths to Chapter_N, so no duplication in html_output
            if figures_cap.exists():
                for process_dir in [figures_cap, figures_lower]:
                    if not process_dir.exists(): continue
                    for child in process_dir.iterdir():
                        if child.is_dir():
                            low_name = child.name.lower()
                            if low_name != child.name:
                                low_path = process_dir / low_name
                                if not low_path.exists():
                                    try:
                                        if os.name == "posix":
                                            os.symlink(child.name, low_path)
                                            # print(f"      [Shim] {child.name} -> {low_name}")
                                        else:
                                            # On windows backup (copy)
                                            pass
                                    except Exception:
                                        pass
        except Exception as e:
            print(f"   [Shim Warn] Could not create figures shim: {e}")
        except Exception as e:
            print(f"   [Shim Warn] Could not create figures shim: {e}")

    # Inject Shim Preamble
    (paths.staging / "structure_html.tex").write_text(CLEAN_STRUCTURE_LATEX, encoding="utf-8")

    # Windows Shims (cp/rm/mv)
    if os.name == "nt":
        _write_windows_shims(paths.shims_dir)


def _write_windows_shims(shims_dir: Path) -> None:
    # make4ht internal calls to 'cp', 'mv' fail on vanilla Windows cmd, so we shim them.
    shims = {
        "cp": "@powershell -NoProfile -Command Copy-Item -LiteralPath '%~1' -Destination '%~2' -Force",
        "mv": "@powershell -NoProfile -Command Move-Item -LiteralPath '%~1' -Destination '%~2' -Force",
        "rm": "@if exist \"%~1\" del /f /q \"%~1\"",
        "mkdir": "@if not exist \"%~1\" mkdir \"%~1\""
    }
    for name, cmd in shims.items():
        (shims_dir / f"{name}.cmd").write_text(f"@echo off\n{cmd}\n", encoding="utf-8")
        

def _get_env(paths: BuildPaths) -> Dict[str, str]:
    env = os.environ.copy()
    if os.name == "nt":
        env["PATH"] = str(paths.shims_dir) + os.pathsep + env.get("PATH", "")
    
    # Ensure TeX uses our custom config (memory, etc) from staging
    # TEXMFCNF must point to the directory containing texmf.cnf
    # Note: TeXLive often requires the path to end with ':', or specific format but pointing to dir usually works.
    env["TEXMFCNF"] = str(paths.staging) + os.pathsep
    
    return env


# ----------------------------
# Math Sanitizer
# ----------------------------

def _convert_text_to_mbox(s: str) -> str:
    r"""Safe replacements of \text{..} -> \mbox{..} with balanced braces."""
    if r"\text" not in s: return s
    
    target = r"\text"
    repl = r"\mbox"
    out = []
    i = 0
    n = len(s)
    
    while i < n:
        if s.startswith(target, i):
            # Ensure it's not \textbf etc
            after = i + len(target)
            if after < n and s[after] not in ("{", " ", "\t", "\\"):
                out.append(s[i])
                i += 1
                continue
            
            # Find argument
            j = after
            while j < n and s[j].isspace(): j += 1
            if j < n and s[j] == "{":
                # Balanced scan
                depth = 1
                k = j + 1
                while k < n and depth > 0:
                    if s[k] == "{": depth += 1
                    elif s[k] == "}": depth -= 1
                    elif s[k] == "\\": k += 1
                    k += 1
                
                if depth == 0:
                    content = s[j:k] # "{...}"
                    # Recursively fix content inside
                    out.append(repl + _convert_text_to_mbox(content))
                    i = k
                    continue

        out.append(s[i])
        i += 1
    return "".join(out)


def _sanitize_math_content(s: str) -> str:
    """Detect math delimiters and sanitize content inside them."""
    # Pattern: $$...$$ | $...$ | \[...\] | \(...\) | \begin{equation}...\end{equation}
    # Naive scan is safer than regex for balanced braces, but for speed logic we use simple parsing.
    
    out = []
    i = 0
    n = len(s)
    
    def is_esc(pos):
        c = 0
        p = pos - 1
        while p >= 0 and s[p] == "\\":
            c += 1
            p -= 1
        return (c % 2) == 1

    while i < n:
        match_delim = None
        content = ""
        jump = 0
        
        # 1. $$ ... $$
        if s.startswith("$$", i) and not is_esc(i):
            end = s.find("$$", i+2)
            if end != -1:
                match_delim = ("$$", "$$")
                content = s[i+2:end]
                jump = end + 2
        
        # 2. \[ ... \] (Takes priority over \[ if we check strict)
        elif s.startswith(r"\[", i):
            end = s.find(r"\]", i+2)
            if end != -1:
                match_delim = (r"\[", r"\]")
                content = s[i+2:end]
                jump = end + 2

        # 3. \( ... \)
        elif s.startswith(r"\(", i):
            end = s.find(r"\)", i+2)
            if end != -1:
                match_delim = (r"\(", r"\)")
                content = s[i+2:end]
                jump = end + 2
                
        # 4. $ ... $
        elif s.startswith("$", i) and not is_esc(i):
            # Scan for closing $
            k = i + 1
            found = False
            while k < n:
                if s[k] == "$" and not is_esc(k):
                    found = True
                    break
                k += 1
            if found:
                match_delim = ("$", "$")
                content = s[i+1:k]
                jump = k + 1

        # 5. \begin{equation}
        elif s.startswith(r"\begin{equation}", i):
            end_tag = r"\end{equation}"
            end = s.find(end_tag, i + 16)
            if end != -1:
                match_delim = (r"\begin{equation}", end_tag)
                content = s[i+16:end]
                jump = end + len(end_tag)

        if match_delim:
            sanitized = _convert_text_to_mbox(content)
            out.append(match_delim[0] + sanitized + match_delim[1])
            i = jump
        else:
            out.append(s[i])
            i += 1
            
    return "".join(out)


def _clean_caption_content(c: str) -> str:
    """Remove fragile commands from caption text."""
    # 1. Replace \\ first (common line break)
    c = c.replace(r"\\", " ").replace(r"\newline", " ")
    
    # 2. Remove comments (handle \% properly)
    # (?<!\\)% -> matches % not preceded by \
    c = re.sub(r'(?<!\\)%.*', '', c) 
    
    # 3. Aggressively flatten
    c = c.replace("\n", " ").replace("\r", " ")
    
    # 4. Remove \vspace{...} 
    c = re.sub(r"\\vspace\*?\{[^}]+\}", "", c)
    # Remove explicit \par
    c = c.replace(r"\par", " ")
    
    # 5. Remove citations entirely (Hammer approach)
    # \cite{...}, \citet{...}, \citep[...] { ... }
    # Simple regex assumption: balanced braces handled by _sanitize_captions context, 
    # but inside the content string we assume no nested braces for \cite arguments.
    
    # 6. Escape special characters causing issues in .aux
    # '#' breaks newlabel in .aux (Illegal parameter number)
    # replacing '\#' or '#' with 'No.' to be safe.
    c = c.replace(r"\#", "No.")
    c = c.replace("#", "No.")

    return c


def _sanitize_captions(s: str) -> str:
    r"""Find \caption{...} and clean its content."""
    if r"\caption" not in s: 
        return s

    target = r"\caption"
    out = []
    i = 0
    n = len(s)
    
    while i < n:
        if s.startswith(target, i):
            # Check for optional arg [ ... ]
            j = i + len(target)
            while j < n and s[j].isspace(): j += 1
            
            # Skip optional arg if present
            if j < n and s[j] == "[":
                # find closing ]
                k = j + 1
                while k < n and s[k] != "]":
                    k += 1
                j = k + 1 # move past ]
                
            # Now find {
            while j < n and s[j].isspace(): j += 1
            
            if j < n and s[j] == "{":
                # Balanced scan
                depth = 1
                k = j + 1
                while k < n and depth > 0:
                    if s[k] == "{": depth += 1
                    elif s[k] == "}": depth -= 1
                    elif s[k] == "\\": k += 1
                    k += 1
                
                if depth == 0:
                    # Found caption content s[j+1:k-1]
                    # Capture everything before caption start
                    # Careful: we want to preserve \caption[opt]{...} structure
                    # prefix is s[i:j+1] -> \caption or \caption[..]{
                    prefix = s[i:j+1]
                    content = s[j+1:k-1]
                    cleaned = _clean_caption_content(content)
                    if cleaned != content:
                        # print(f"   [Sanitize] Fixed caption: {content[:40]}...")
                        pass
                    out.append(prefix + cleaned + "}")
                    i = k
                    continue

        out.append(s[i])
        i += 1
    return "".join(out)


def _preprocess_file(path: Path) -> None:
    # print(f"Preprocessing {path.name}...") 
    raw = path.read_text(encoding="utf-8", errors="replace")
    
    # 1. Mask Verbatim Blocks (Simple non-recursive)
    blocks = []
    def repl_block(m):
        blocks.append(m.group(0))
        return f"__VERBATIM_MASK_{len(blocks)-1}__"
    
    pat = re.compile(rf"\\begin\{{({'|'.join(VERBATIM_ENVS)})\}}.*?\\end\{{\1\}}", re.DOTALL)
    masked = pat.sub(repl_block, raw)
    
    # 2. Sanitize Math
    sanitized = _sanitize_math_content(masked)
    
    # 3. Sanitize Captions
    sanitized = _sanitize_captions(sanitized)
    
    # 4. Restore Verbatim
    for idx, b in enumerate(blocks):
        sanitized = sanitized.replace(f"__VERBATIM_MASK_{idx}__", b)
        
    path.write_text(sanitized, encoding="utf-8")


# ----------------------------
# Heartbeat Monitor
# ----------------------------

class HeartbeatMonitor:
    def __init__(self, watch_dir: Path, timeout: int = HEARTBEAT_TIMEOUT_SECONDS):
        self.watch_dir = watch_dir
        self.timeout = timeout
        self.last_activity = time.time()
        self.initial_files = self._scan_files()
        
    def _scan_files(self) -> Dict[Path, float]:
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
            pass # Directory might be locked/deleted
        return state

    def check(self) -> bool:
        """Returns True if alive, False if stalled."""
        current_state = self._scan_files()
        
        # Check if anything changed
        activity_detected = False
        
        # New files?
        if set(current_state.keys()) != set(self.initial_files.keys()):
            activity_detected = True
        else:
            # Modified files?
            for p, mtime in current_state.items():
                if p in self.initial_files and mtime > self.initial_files[p]:
                    activity_detected = True
                    break
        
        if activity_detected:
            self.last_activity = time.time()
            self.initial_files = current_state
            return True
        
        # No activity: check timeout
        elapsed = time.time() - self.last_activity
        return elapsed < self.timeout
        
    def time_since_activity(self) -> float:
        return time.time() - self.last_activity

    def touch(self) -> None:
        """Manually signal activity (e.g. from stdout)."""
        self.last_activity = time.time()


# ----------------------------
# Build Execution
# ----------------------------

def _make4ht_exe() -> str:
    # Look for system make4ht, or common Windows paths
    candidates = [
        r"C:\texlive\2024\bin\windows\make4ht.EXE",
        "make4ht"
    ]
    for c in candidates:
        if shutil.which(c): return c
    return "make4ht"


def _check_kill_string(line: str) -> Optional[str]:
    """Check if the line contains a string that should trigger an immediate kill."""
    for k in KILL_STRINGS:
        if k in line:
            return k
    if line.strip().startswith("Error:"):
        return "Error: (start of line)"
    return None

def _run_with_heartbeat(cmd: List[str], cwd: Path, env: Dict[str, str], log_path: Path, strict: bool = False) -> None:
    """Run a process with heartbeat monitoring and active error scanning."""
    
    with open(log_path, "w", encoding="utf-8") as f_log:
        proc = subprocess.Popen(
            cmd,
            cwd=cwd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, 
            text=True, 
            encoding="utf-8",
            errors="replace",
            bufsize=1  
        )
        
        monitor = HeartbeatMonitor(cwd)
        start_time = time.time()
        last_check_time = time.time()
        
        try:
            while True:
                ret = proc.poll()
                line = proc.stdout.readline()
                
                if line:
                    monitor.touch() # STDOUT counts as activity!
                    f_log.write(line)
                    kill_reason = _check_kill_string(line)
                    if kill_reason:
                        proc.kill()
                        raise RuntimeError(f"Active Scan found fatal error: '{kill_reason}' in line:\n{line.strip()}")
                else:
                    if ret is not None:
                        break
                    time.sleep(0.05)

                # Timeouts
                now = time.time()
                if (now - start_time) > HARD_TIMEOUT_SECONDS:
                    proc.kill()
                    raise TimeoutError(f"HARD TIMEOUT ({HARD_TIMEOUT_SECONDS}s) exceeded.")
                
                # Check monitor periodically (not on every line!)
                if (now - last_check_time) > 5.0:
                    monitor.check()
                    last_check_time = now
                    
                    since_act = monitor.time_since_activity()
                    if since_act > HEARTBEAT_TIMEOUT_SECONDS:
                        proc.kill()
                        raise TimeoutError(f"STALLED (No disk activity for {since_act:.0f}s).")

        except Exception as e:
            if proc.poll() is None:
                proc.kill()
            raise e

    if proc.returncode != 0:
        msg = f"Process failed with code {proc.returncode}"
        if strict:
            raise RuntimeError(msg)
        else:
             print(f"   [WARN] {msg} (strict=False, proceeding)")
             # Check for log file and print tail/errors for debugging
             if log_path.exists():
                 print(f"   [debug] Log snippet from {log_path.name}:")
                 try:
                     txt = log_path.read_text(encoding="utf-8", errors="replace")
                     lines = txt.splitlines()
                     # 1. Print explicit errors
                     for line in lines:
                         if line.startswith("!") or "Error:" in line:
                             print(f"      {line}")
                     # 2. Print tail
                     print("      ... (last 20 lines) ...")
                     for line in lines[-20:]:
                         print(f"      {line}")
                 except Exception:
                     print("      (Could not read log file)")


def _deploy_artifacts(paths: BuildPaths, stem: str) -> None:
    """Safely copy generated artifacts from Staging -> Output, strictly."""
    # 1. Copy Main HTML
    src_html = paths.staging / f"{stem}_wrapper.html"
    if src_html.exists():
        shutil.copy2(src_html, paths.html_dir / f"{stem}.html")
    
    # 2. Copy CSS (Any *.css)
    for css in paths.staging.glob("*.css"):
        shutil.copy2(css, paths.out_dir / css.name)
        
    # 3. Copy Images (Generated by make4ht: png, jpg, svg)
    # We copy them regardless of whether they were there before or new
    for ext in ["png", "jpg", "jpeg", "svg"]:
        for f in paths.staging.glob(f"*.{ext}"):
            # Avoid copying source folders that might be in staging root if copytree was loose
            # (But our copytree put them in /Figures etc, so root files are likely generated)
            if f.is_file():
                shutil.copy2(f, paths.out_dir / f.name)

def _run_build_process(paths: BuildPaths, chapter_name: str) -> None:
    stem = Path(chapter_name).stem
    
    # Extract chapter number from filename (e.g., "Chapter_15_..." -> 15)
    chapter_match = re.search(r'Chapter_(\d+)', chapter_name)
    chapter_num = int(chapter_match.group(1)) if chapter_match else 1
    
    # 1. Create Wrapper (Inject Shim Preamble)
    # Set chapter counter so sections are numbered N.x (e.g., 15.1, 15.2 for Chapter 15)
    wrapper_path = paths.staging / f"{stem}_wrapper.tex"
    wrapper_path.write_text(
        f"\\documentclass[11pt,openany]{{book}}\n"
        f"\\input{{structure_html}}\n"
        f"\\begin{{document}}\n"
        f"\\setcounter{{chapter}}{{{chapter_num - 1}}}\n"  # Set so first section is N.1
        f"\\setcounter{{section}}{{0}}\n"
        f"\\input{{Chapters/{chapter_name}}}\n"
        f"\\end{{document}}\n",
        encoding="utf-8"
    )
    
    # 2. MK4 File
    mk4_path = paths.staging / f"{stem}_wrapper.mk4"
    mk4_path.write_text(
        r"Make:add('biber','biber ${input}',{correct_exit=0}) " + "\n" +
        r"Make:htlatex {} " + "\n" +
        r"Make:biber {} " + "\n" +
        r"Make:htlatex {} " + "\n",
        encoding="utf-8"
    )
    
    # 3. Prepare Command
    exe = _make4ht_exe()
    cmd = [
        exe,
        "-s", # Silent
        "-u", # UTF8
        "-f", "html5",
        "-e", mk4_path.name,
        wrapper_path.name,
        "xhtml,mathjax,charset=utf-8,fn-in",
        "",
        "-interaction=nonstopmode"
    ]
    
    log_file_path = paths.staging / f"{stem}_build.log"
    print(f"   [Processing] {chapter_name} (Active Scan enabled) ...")

    try:
        _run_with_heartbeat(cmd, paths.staging, _get_env(paths), log_file_path)
    except Exception as e:
        print(f"   [ERROR] {e}")
        shutil.copy2(log_file_path, paths.logs_dir / f"{stem}_FAILED.log")
        raise e

    # 5. Success Validation
    out_html = paths.staging / f"{stem}_wrapper.html"
    if not out_html.exists():
        raise FileNotFoundError("Build finished but HTML file missing.")
    
    # Copy artifacts
    _deploy_artifacts(paths, stem)
    shutil.copy2(log_file_path, paths.logs_dir / f"{stem}_SUCCESS.log")


def _extract_and_build_preface(paths: BuildPaths) -> None:
    """Extracts Preface from main.tex and builds it as a standalone HTML page."""
    print(f"\n>>> Processing Preface (Extraction from main.tex)...")
    
    main_tex = paths.staging / "main.tex"
    if not main_tex.exists():
        raise FileNotFoundError("main.tex not found in staging")
    
    content = main_tex.read_text(encoding="utf-8", errors="replace")
    
    # Extract between \chapter*{Preface} and the first \input{Chapters
    # Regex for robustness
    m = re.search(r'(\\chapter\*\{Preface\}.*?)(\\input\{Chapters)', content, re.DOTALL)
    if not m:
        print("   [Preface] Could not find Preface content in main.tex. Skipping.")
        return
        
    preface_content = m.group(1)
    
    p_out = paths.staging / "Chapters" / "Preface.tex"
    p_out.parent.mkdir(parents=True, exist_ok=True)
    p_out.write_text(preface_content, encoding="utf-8")
    
    # Build it using the standard process
    # We reuse _run_build_process but need to adapt it since it expects "Chapter_X" naming for layout
    # We'll just pass "Preface.tex" and handle the "Chapter_X" parsing gracefully in _run_build_process?
    # No, _run_build_process does: chapter_match = re.search(r'Chapter_(\d+)', chapter_name) -> defaults to 1
    # This works fine, it will just treat it as Chapter 1 for counter purposes, which is acceptable for Preface.
    # The output will be Preface.html
    
    _run_build_process(paths, "Preface.tex")
    print(f"   [DONE] Preface -> HTML: OK\n")

# ----------------------------
# ----------------------------
# PDF Build
# ----------------------------


def _build_main_pdf(paths: BuildPaths) -> None:
    """Builds the entire book (main.pdf) -> html_output/downloads/main.pdf."""
    print(f"\n   [Main PDF] Building main.pdf (Full Book)...")
    
    # 1. Prepare Target Directory
    downloads_dir = paths.out_dir / "downloads"
    downloads_dir.mkdir(parents=True, exist_ok=True)
    
    main_tex = paths.staging / "main.tex"
    if not main_tex.exists():
        print("   [Main PDF] main.tex not found in staging. Skipping.")
        return

    # 3. Validation: Run PDFLaTeX -> Biber -> PDFLaTeX -> PDFLaTeX
    jobname = "main"
    def run_cmd(tool: str, args: List[str]):
        full_cmd = [tool] + args
        log_path = paths.staging / f"main_{tool}.log"
        # We use strict=False because main.tex might have some acceptable warnings
        # But we still want the heartbeat.
        _run_with_heartbeat(full_cmd, paths.staging, _get_env(paths), log_path)

    try:
        # Relaxed flags for CI robustness
        # Removed -halt-on-error to allow recovery from non-critical errors
        flags = ["-interaction=nonstopmode", "-shell-escape", "-jobname", jobname, "main.tex"]
        
        # Pass 1
        run_cmd("pdflatex", flags)
        
        # Biber
        if (paths.staging / f"{jobname}.bcf").exists():
             run_cmd("biber", [jobname])
             
        # Pass 2 & 3
        run_cmd("pdflatex", flags)
        run_cmd("pdflatex", flags)
        
        # 4. Copy to Downloads and Verify Page Count
        pdf_out = paths.staging / "main.pdf"
        if pdf_out.exists():
            dest = downloads_dir / "main.pdf"

            # --- STEP 1: Copy UNCOMPRESSED version first (for chapter splitting) ---
            pdf_size_mb = pdf_out.stat().st_size / (1024 * 1024)
            print(f"   [Main PDF] Size: {pdf_size_mb:.2f} MB")

            # Always copy uncompressed version first
            shutil.copy2(pdf_out, dest)
            print(f"   [Main PDF] Copied uncompressed main.pdf to downloads/")

            # --- STEP 2: Compression decision (will be done AFTER chapter splitting) ---
            # Note: Chapter splitting should happen AFTER this function completes
            # The compression of main.pdf will be handled by the post-processing pipeline
            # if main.pdf exceeds 95MB after chapters have been extracted from the uncompressed version
            
            # Copy TOC and BBL for Navigation Script
            toc_src = paths.staging / "main.toc"
            if toc_src.exists():
                shutil.copy2(toc_src, paths.out_dir / "main.toc")
                print(f"   [Main PDF] Copied main.toc to output.")
            
            bbl_src = paths.staging / "main.bbl"
            if bbl_src.exists():
                shutil.copy2(bbl_src, paths.out_dir / "main_html.bbl") # Renaming for nav script
                print(f"   [Main PDF] Copied main.bbl to main_html.bbl.")
            
            # Verify Page Count from Log
            log_content = (paths.staging / "main_pdflatex.log").read_text(encoding="utf-8", errors="replace")
            # Look for: Output written on main.pdf (2217 pages, 12345 bytes).
            m = re.search(r"Output written on .*? \((\d+) pages", log_content)
            if m:
                count = int(m.group(1))
                print(f"   [Main PDF] Detected Page Count: {count}")
            else:
                print("   [Main PDF] Could not determine page count from log.")

        else:
             print("   [Main PDF] Failed to generate main.pdf (file missing).")

    except Exception as e:
        print(f"   [Main PDF FAIL] {e}")




# ----------------------------
# Main Orchestrator
# ----------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", default="html_output", type=Path)
    parser.add_argument("--skip-pdf", action="store_true", help="Skip main PDF generation (HTML build only)")
    parser.add_argument("--skip-nav", action="store_true", help="Skip running create_navigation.py (for CI orchestration)")
    parser.add_argument("--pdf-only", action="store_true", help="Build ONLY the main PDF (main.pdf) and exit.")
    args = parser.parse_args()
    
    # Force unbuffered stdout for python
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(line_buffering=True)
    
    paths = _init_paths(args.out_dir)
    print(f"Build Roots:\n  Repo: {paths.repo_root}\n  Out:  {paths.out_dir}")
    
    _setup_staging(paths)
    

    
    # Get Chapters
    all_chapters = sorted(paths.staging.glob("Chapters/Chapter_*.tex"))
    if not all_chapters:
        print("No chapters found to build.")
        return 0
    

        
    # Sort by number
    sorted_chapters = []
    for c in all_chapters:
        m = re.search(r'Chapter_(\d+)', c.name)
        if m:
            sorted_chapters.append((int(m.group(1)), c))
    sorted_chapters.sort(key=lambda x: x[0])

    
    # ----------------------------
    # Build Context
    # ----------------------------
    build_summary = []

    # Remove Chapter 24 (Templates) from HTML build list usually? 
    # The user instruction was "build the chapters one after another, starting with the fist one until completion".
    # So we keep all chapters.
    
    print("\n========================================")
    print(f" STARTING SEQUENTIAL BUILD ({len(sorted_chapters)} Chapters)")
    print("========================================\n")

    # 0. Build Main PDF (If requested)
    if args.pdf_only:
        _build_main_pdf(paths)
        return 0

    if not args.skip_pdf:
        # We only build main PDF if explicitly requested or part of full build (optional)
        # But per user request, we are focusing on HTML per chapter. 
        # Let's keep main pdf build here if not skipped? 
        # User said: "just the main pdf (that now fails by the way! make sure you run it indepdently now...)"
        # So in normal run, maybe we skip it? Or keep it?
        # User said "The chapter creation now seems to work (html files). No need for you to make pdf per chapter, just the main pdf"
        # So we KEEP main pdf in default run, but remove per-chapter pdfs.
        _build_main_pdf(paths)
    else:
        print("   [Main PDF] Skipped (--skip-pdf).")

    # 0b. Build Preface (Surgical Extraction from main.tex)
    # We do this before chapters so it's ready for navigation
    try:
        _extract_and_build_preface(paths)
        build_summary.append({"name": "Preface", "pdf": "SKIP", "html": "OK"})
    except Exception as e:
        print(f"   [Preface FAIL] {e}")
        build_summary.append({"name": "Preface", "pdf": "SKIP", "html": "FAIL"})

    for num, ch_path in sorted_chapters:
        ch_name = ch_path.name
        stem = ch_path.stem
        print(f">>> Processing Chapter {num}: {ch_name}")
        
        status = {"pdf": "SKIP", "html": "SKIP"}
        
        # --- Phase 1: PDF ---
        # Per-chapter PDF disabled per user request.
        # status["pdf"] = "DISABLED"
        
        _preprocess_file(ch_path)

        # --- Phase 2: HTML ---
        # Note: HTML build uses _wrapper.tex (Clean Room Shim)
        # PDF build used _pdf.tex (Original Structure)
        
        try:
            _run_build_process(paths, ch_name)
            status["html"] = "OK"
        except Exception as e:
             print(f"   [HTML FAIL] {e}")
             status["html"] = "FAIL"
             
        build_summary.append({"name": ch_name, "pdf": status["pdf"], "html": status["html"]})
        print(f"   [DONE] Ch{num} -> HTML: {status['html']}\n")


    # ----------------------------
    # Final Report
    # ----------------------------
    print("\n" + "="*40)
    print(f" BUILD SUMMARY ({datetime.datetime.now().strftime('%H:%M:%S')})")
    print("="*40)
    print(f"{'Chapter':<30} | {'PDF':<5} | {'HTML':<5}")
    print("-" * 46)
    for res in build_summary:
        print(f"{res['name']:<30} | {res['pdf']:<5} | {res['html']:<5}")
    print("-" * 46)
    
    # Check for HTML failures to set exit code
    failures = [x for x in build_summary if x['html'] == "FAIL"]
    
    # ----------------------------
    # Global Artifact Sync
    # ----------------------------
    print("\n[Artifact Sync] Synchronizing global assets...")

    # 1. Figures, Pictures & Images (Recursive)
    # Always copy the real directory content, resolving symlinks if needed.
    # A lowercase symlink (figures -> Figures) may exist for LaTeX case-sensitivity;
    # we must still copy the actual Figures/ content to html_output/.
    # IMPORTANT: Inside Figures/, lowercase symlinks (chapter_20 -> Chapter_20) exist
    # for LaTeX compilation. We must skip those to avoid duplicating content.
    def _copy_tree_skip_symlinks(src_dir, dst_dir):
        """Copy directory tree, skipping symlink children to avoid duplication."""
        dst_dir.mkdir(parents=True, exist_ok=True)
        for item in src_dir.iterdir():
            if item.is_symlink():
                continue  # Skip symlinks (e.g. chapter_20 -> Chapter_20)
            dst_item = dst_dir / item.name
            if item.is_dir():
                _copy_tree_skip_symlinks(item, dst_item)
            elif item.is_file():
                shutil.copy2(item, dst_item)

    copied_real_paths = set()  # Track resolved paths to avoid duplicating
    for folder in ["Figures", "Pictures", "images"]:
        try:
            src = paths.staging / folder
            if src.exists():
                real_src = src.resolve()  # Follow symlinks to get real path
                if real_src in copied_real_paths:
                    print(f"   [Sync] Skipped {folder}/ (already copied as resolved path)")
                    continue
                dst = paths.out_dir / folder
                _copy_tree_skip_symlinks(real_src, dst)
                copied_real_paths.add(real_src)
                file_count = sum(1 for _ in dst.rglob('*') if _.is_file())
                print(f"   [Sync] Copied {folder}/ ({file_count} files)")
        except Exception as e:
            print(f"   [Sync FAIL] Could not copy {folder}: {e}")

    # 2. main.toc (Critical for Sidebar)
    toc_src = paths.staging / "main.toc"
    if toc_src.exists():
        shutil.copy2(toc_src, paths.out_dir / "main.toc")
        print("   [Sync] Copied main.toc")
    else:
        print("   [Sync] Warning: main.toc not found in staging.")

    # ----------------------------
    # Navigation (DEPRECATED - now handled by run_post_processor.py)
    # ----------------------------
    # The --skip-nav flag is kept for backwards compatibility but is now a no-op.
    # Navigation generation has been moved to run_post_processor.py which should
    # be run after this script completes.
    if not args.skip_nav:
        print("\n[Note] Navigation is now handled by run_post_processor.py")
        print("       Run 'python scripts/run_post_processor.py' after this script completes.")
    
    if failures:
        print(f"\n[WARNING] {len(failures)} chapters failed HTML conversion.")
        return 1
    
    print("\n[SUCCESS] All chapters processed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
