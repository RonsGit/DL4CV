#!/usr/bin/env python3
"""
Table of Contents extractor.
Extracts hierarchical TOC from chapter body HTML.
"""
import re
from .math_protection import restore_math


def extract_toc_from_body(body_html: str, lecture_num: int = 1) -> str:
    """
    Extract TOC with proper hierarchy using a two-pass algorithm:
    
    Pass 1: Collect all h3/h4 headings and identify enrichments
    Pass 2: Detect consecutive h3 enrichments and renumber them as subsections
    
    Rules:
    - H3 sectionHead = section (X.Y format)
    - H4 subsectionHead = subsection (X.Y.Z format) 
    - H3 enrichments: First in a consecutive group = section, rest = subsections
    - Skip h5 (subsubsections)
    """
    # Match h3, h4, and h5 headings with IDs
    matches = list(re.finditer(
        r'<(h[345])\b[^>]*(?:id=["\']([^"\']+)["\'])[^>]*>(.*?)</\1>', 
        body_html, re.IGNORECASE | re.DOTALL
    ))
    
    # Pass 1: Collect and classify all headings
    headings = []
    for m in matches:
        tag, eid, content = m.groups()
        tag = tag.lower()
        
        if not eid:
            continue
        
        # Extract text content
        text = re.sub(r'<[^>]+>', '', content).strip()
        text = restore_math(text)
        if not text:
            continue
        
        # Skip noise
        if re.search(r'Chapter\s*\d+', text, re.IGNORECASE):
            continue
        if re.match(r'^Lecture\s+\d+:', text, re.IGNORECASE):
            continue
        if tag == 'h5':  # Skip subsubsections
            continue
        
        # Rewrite 1.x -> N.x
        if lecture_num > 1:
            text = re.sub(r'^1\.', f'{lecture_num}.', text)
        
        # Check if enrichment
        enr_match = re.match(r'Enrichment\s+([\d.]+):?\s*(.*)', text, re.IGNORECASE)
        is_enrichment = bool(enr_match)
        enr_num = enr_match.group(1) if enr_match else None
        enr_title = enr_match.group(2).strip() if enr_match else None
        
        # Rewrite enrichment number 1.x -> N.x
        if enr_num and lecture_num > 1:
            enr_num = re.sub(r'^1\.', f'{lecture_num}.', enr_num)
        
        headings.append({
            'tag': tag,
            'eid': eid,
            'text': text,
            'is_enrichment': is_enrichment,
            'enr_num': enr_num,
            'enr_title': enr_title,
        })
    
    # Pass 2: Renumber consecutive h3 enrichments
    i = 0
    while i < len(headings):
        h = headings[i]
        
        if h['is_enrichment'] and h['tag'] == 'h3':
            parent_parts = h['enr_num'].split('.')
            parent_num = '.'.join(parent_parts[:2])
            
            j = i + 1
            subsection_counter = 1
            
            while j < len(headings) and headings[j]['tag'] == 'h3' and headings[j]['is_enrichment']:
                child = headings[j]
                corrected_num = f"{parent_num}.{subsection_counter}"
                child['display_text'] = f"{corrected_num} {child['enr_title']}"
                child['is_subsection'] = True
                subsection_counter += 1
                j += 1
            
            h['display_text'] = f"{parent_num} {h['enr_title']}"
            h['is_subsection'] = False
            i = j
        else:
            if h['is_enrichment']:
                h['display_text'] = f"{h['enr_num']} {h['enr_title']}"
            else:
                h['display_text'] = h['text']
            
            if h['tag'] == 'h4':
                h['is_subsection'] = True
            else:
                num_match = re.match(r'^(\d+(?:\.\d+)*)', h['text'])
                if num_match:
                    parts = num_match.group(1).split('.')
                    h['is_subsection'] = len(parts) >= 3
                else:
                    h['is_subsection'] = False
            i += 1
    
    # Pass 3: Generate HTML with proper hierarchy
    html = ""
    current_parent_id = None
    
    for h in headings:
        text = h.get('display_text', h['text'])
        is_subsection = h.get('is_subsection', False)
        is_enrichment = h['is_enrichment']
        eid = h['eid']
        
        if is_enrichment:
            link_html = f'<a href="#{eid}">{text}<span class="toc-emoji" aria-hidden="true">📘</span></a>'
        else:
            link_html = f'<a href="#{eid}">{text}</a>'
        
        if is_subsection:
            toc_class = 'toc-h4 toc-enrichment' if is_enrichment else 'toc-h4'
            if not current_parent_id:
                continue
            html += f'<li class="{toc_class}">{link_html}</li>'
        else:
            toc_class = 'toc-h3 toc-enrichment' if is_enrichment else 'toc-h3'
            if current_parent_id:
                html += '</ul></li>'
            html += f'<li class="{toc_class}">{link_html}<ul class="toc-sub-list">'
            current_parent_id = eid
    
    if current_parent_id:
        html += '</ul></li>'
    
    return html
