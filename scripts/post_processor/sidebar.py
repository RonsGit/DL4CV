#!/usr/bin/env python3
"""
Sidebar builder for CVBook navigation.
Creates the HTML for the collapsible sidebar with chapter list.
"""
from . import config


def get_asset_url(rel_path: str, is_aux: bool = False) -> str:
    """
    Returns the web-ready URL for an asset.
    If BASE_URL is set, uses absolute path: /CVBook/path/to/file
    Else, uses relative path: ../path/to/file or path/to/file
    """
    base_url = config.get_base_url()
    if base_url:
        clean_base = base_url.rstrip('/')
        clean_path = rel_path.lstrip('/')
        return f"{clean_base}/{clean_path}"
    else:
        prefix = "../" if is_aux else ""
        return f"{prefix}{rel_path}"


def build_sidebar(active_mk, is_aux=False, local_toc_content=""):
    """Build the sidebar HTML with navigation."""
    home_url = get_asset_url("index.html", is_aux)
    preface_url = get_asset_url("Auxiliary/Preface.html", is_aux)
    dep_url = get_asset_url("dependency_graph.html", is_aux)
    bib_url = get_asset_url("bibliography.html", is_aux)
    repo_url = "https://github.com/RonsGit/DL4CV"
    star_url = "https://github.com/RonsGit/DL4CV/stargazers"
    
    html = f'''
    <div class="sidebar-header">
        <div class="header-title" style="display: flex; align-items: center; gap: 0.75rem;">
            <button id="sidebar_toggle" class="sidebar-toggle"><i class="fas fa-bars"></i></button>
            <a href="{home_url}" style="text-decoration:none; color:inherit; font-size: 1.1rem;"><span>CVBook</span></a>
        </div>
        <div class="repo-links" style="display: flex; align-items: center; gap: 10px; margin-top: 0.75rem; padding-left: 0.5rem;">
             <!-- Repo -->
             <a href="{repo_url}" target="_blank" style="color: #333; font-size: 1.6rem; text-decoration: none;"><i class="fab fa-github"></i></a>
             <!-- Star -->
             <a href="{star_url}" target="_blank" onclick="event.preventDefault(); window.open('https://github.com/login?return_to=%2FRonsGit%2FDL4CV', '_blank');" style="text-decoration: none; color: #24292e; background-color: #eff3f6; border: 1px solid rgba(27,31,35,0.2); border-radius: 4px; padding: 2px 8px; font-size: 12px; font-weight: 600; display: inline-flex; align-items: center; gap: 4px;">
                 <i class="far fa-star"></i> Star
             </a>
        </div>
    </div>
    
    <!-- Fix 4: Ordering (Home -> Preface -> Dep -> Bib -> Chapters) -->
    <ul class="chapter-list">
        <li class="chapter-item {'active' if str(active_mk) == 'index' or str(active_mk) == 'home' else ''}"><a href="{home_url}">Home</a></li>
        <li class="chapter-item {'active' if str(active_mk) == 'preface' or 'preface' in str(active_mk) else ''}"><a href="{preface_url}">Preface</a></li>
        <li class="chapter-item {'active' if str(active_mk) == 'dep' or 'dependency' in str(active_mk) else ''}"><a href="{dep_url}">Dependency Graph</a></li>
        <li class="chapter-item {'active' if str(active_mk) == 'bib' or 'bibliography' in str(active_mk) else ''}"><a href="{bib_url}">Bibliography</a></li>
    </ul>
    
    <hr style="margin: 0.5rem 1.5rem; border:0; border-top:1px solid var(--gray-300);">
    
    <ul class="chapter-list">
    '''
    
    current_num = -1
    if isinstance(active_mk, int): 
        current_num = active_mk
    
    for ch in config.CHAPTERS:
        active = " active" if ch['num'] == current_num else ""
        ch_url = get_asset_url(ch["file"], is_aux)
        html += f'<li class="chapter-item{active}">'
        html += f'<a href="{ch_url}">Lecture {ch["num"]}: {ch["title"]}</a>'
        if ch['num'] == current_num and local_toc_content:
            html += f'<ul class="local-toc" style="display:block;">{local_toc_content}</ul>'
        html += '</li>'
        
    html += '</ul>'
    return html
