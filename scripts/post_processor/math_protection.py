#!/usr/bin/env python3
"""
Math protection utilities.
Protects LaTeX math from text processing and restores it afterward.
"""
import re

# Global store for math tokens
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
    if not MATH_STORE:
        return content
    pattern = re.compile("|".join(re.escape(k) for k in MATH_STORE.keys()))
    def repl(m): 
        return MATH_STORE[m.group(0)]
    return pattern.sub(repl, content)


def clean_latex_artifacts(content: str) -> str:
    """Clean specific LaTeX artifacts that escape math processing."""
    # Fix \bm -> \boldsymbol (MathJax supported)
    content = content.replace(r'\bm', r'\boldsymbol')
    
    # Checkmark replacement
    content = re.sub(r'\\mathchar"?\s*458', '&#10003;', content, flags=re.IGNORECASE)
    content = content.replace(r'\noindent', '')

    # Generic \mathchar removal
    content = re.sub(r'\\mathchar"?\s*[0-9a-fA-F]+', '', content, flags=re.IGNORECASE)
    content = re.sub(r"\\mathchar'?\s*[0-7]+", '', content, flags=re.IGNORECASE)
    content = re.sub(r'\\mathchar\s*\d+', '', content, flags=re.IGNORECASE)
    
    # Remove internal TeX tokens
    content = content.replace(r'\m@th', '')
    content = re.sub(r'\\hskip\s*[\d\.]+[a-z]+', '', content)
    content = re.sub(r'\\vskip\s*-?[\d\.]+\s*[a-z]{2}', '', content)
    content = content.replace(r'\relax', '')
    
    # Remove long runs of underscores
    content = re.sub(r'_{5,}', '', content)
    return content
