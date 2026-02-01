# LaTeX to HTML build environment
# Pre-installed TeX Live, Python, Node, and all build tools for fast CI builds
# This saves ~15-20 minutes of installation time in GitHub Actions
FROM ubuntu:24.04

# Prevent interactive prompts during installation
ENV DEBIAN_FRONTEND=noninteractive

# Install all required packages in a single layer for optimal caching
# Organized by category for maintainability
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    # Core utilities
    ca-certificates \
    curl \
    git \
    make \
    # TeX Live - Full LaTeX distribution
    texlive \
    texlive-latex-recommended \
    texlive-latex-extra \
    texlive-fonts-recommended \
    texlive-fonts-extra \
    texlive-bibtex-extra \
    texlive-plain-generic \
    texlive-lang-english \
    texlive-xetex \
    texlive-extra-utils \
    texlive-science \
    # LaTeX tools
    dvisvgm \
    latexmk \
    biber \
    tex4ht \
    pandoc \
    # Python 3 and packages
    python3 \
    python3-pip \
    python3-venv \
    python3-pypdf \
    python3-pygments \
    python3-bs4 \
    python3-autopep8 \
    python3-regex \
    # Node.js for pagefind
    nodejs \
    npm \
    # Image optimization tools (saves ~2-3 min in CI)
    ghostscript \
    webp \
    imagemagick \
    # Parallel processing
    parallel \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Install Python packages not available via apt
# pymupdf is critical for PDF processing
RUN pip install --break-system-packages --no-cache-dir \
    pymupdf \
    regex

# Install pagefind globally (search indexing tool)
RUN npm install -g pagefind

# Set working directory
WORKDIR /workspace

# Copy custom TeX configuration for increased memory limits
COPY texmf.cnf /etc/texmf/texmf.cnf
RUN mktexlsr

# Set environment variables
ENV TEXMFCNF=/etc/texmf:
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Verify all critical installations
RUN echo "=== Verifying installations ===" && \
    pdflatex --version | head -1 && \
    biber --version | head -1 && \
    pandoc --version | head -1 && \
    python3 --version && \
    python3 -c "import pymupdf; print(f'PyMuPDF: {pymupdf.__version__}')" && \
    python3 -c "import bs4; print('BeautifulSoup: OK')" && \
    python3 -c "import pygments; print(f'Pygments: {pygments.__version__}')" && \
    node --version && \
    npm --version && \
    pagefind --version && \
    gs --version | head -1 && \
    cwebp -version | head -1 && \
    convert --version | head -1 && \
    echo "=== All tools verified ==="

# Default command
CMD ["/bin/bash"]
