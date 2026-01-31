# LaTeX to HTML build environment
# Pre-installed TeX Live, pandoc, and build tools for fast CI builds
FROM ubuntu:24.04

# Prevent interactive prompts during installation
ENV DEBIAN_FRONTEND=noninteractive

# Install all required packages in a single layer
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    ca-certificates \
    make \
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
    dvisvgm \
    latexmk \
    biber \
    tex4ht \
    pandoc \
    python3-pip \
    python3-venv \
    python3-pypdf \
    python3-pygments \
    python3-bs4 \
    python3-autopep8 \
    texlive-latex-extra \
    latexmk \
    ghostscript \
    nodejs \
    npm && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /workspace

# Copy custom TeX configuration for increased memory limits
COPY texmf.cnf /etc/texmf/texmf.cnf
RUN mktexlsr

# Verify installations
RUN pandoc --version && \
    pdflatex --version && \
    biber --version

# Set environment variable for TeX memory
ENV TEXMFCNF=/etc/texmf:

# Default command
CMD ["/bin/bash"]

