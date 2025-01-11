import re
from pandocfilters import toJSONFilter, RawInline, RawBlock

# Define base paths for assets
IMAGE_PATH_PREFIX = "assets/images/"
PDF_PATH_PREFIX = "assets/pdfs/"

def add_yaml_header(key, value):
    """Add YAML header for each chapter."""
    if key == "RawBlock" and value[0] == "latex":
        content = value[1]
        
        # Search for the chapter title in the LaTeX content
        match = re.search(r'\\chapter\{([^}]+)\}', content)
        if match:
            chapter_title = match.group(1)
            # Create YAML header
            yaml_header = f"---\nlayout: post\ntitle: \"{chapter_title}\"\npermalink: /{chapter_title.lower().replace(' ', '-')}/\n---\n"
            return RawBlock("markdown", yaml_header)
    return None

def process_latex_commands(key, value):
    """Process LaTeX commands like \includegraphics and \includepdf."""
    if key == "RawInline" and value[0] == "latex":
        content = value[1]

        # Handle \includegraphics (convert to markdown image)
        if r"\\includegraphics" in content:
            # Extract image path from LaTeX
            match = re.search(r'\\includegraphics\{([^\}]+)\}', content)
            if match:
                img_path = match.group(1)
                return RawInline("markdown", f"![Image]({IMAGE_PATH_PREFIX}{img_path})")

        # Handle \includepdf (convert to markdown link)
        elif r"\\includepdf" in content:
            # Extract PDF path from LaTeX
            match = re.search(r'\\includepdf\{([^\}]+)\}', content)
            if match:
                pdf_path = match.group(1)
                return RawInline("markdown", f"[PDF]({PDF_PATH_PREFIX}{pdf_path})")

        # For citations, keep the original LaTeX
        if r"\\cite" in content:
            return RawInline("latex", content)

    return None

def custom_filter(key, value, format, meta):
    """Main filter function to process LaTeX commands and metadata."""
    
    # Add YAML header for the chapter
    result = add_yaml_header(key, value)
    if result:
        return result

    # Process LaTeX commands for images, PDFs, and citations
    return process_latex_commands(key, value) or value

if __name__ == "__main__":
    toJSONFilter(custom_filter)
