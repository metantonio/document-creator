import os
import re
from typing import List, Dict, Any, Optional
import docx
from docx import Document

def normalize_path(path: str) -> str:
    return os.path.abspath(path)

def list_all_documents(document_paths: List[str]) -> List[Dict[str, Any]]:
    """Scan configured document paths for .md, .txt, and .docx files."""
    documents = []
    seen_paths = set()

    for dir_path in document_paths:
        abs_dir = normalize_path(dir_path)
        if not os.path.exists(abs_dir):
            continue
        
        for root, _, files in os.walk(abs_dir):
            for file in files:
                ext = os.path.splitext(file)[1].lower()
                if ext in ['.md', '.docx', '.txt']:
                    full_path = os.path.join(root, file)
                    if full_path in seen_paths:
                        continue
                    seen_paths.add(full_path)
                    
                    try:
                        stat = os.stat(full_path)
                        documents.append({
                            "filename": file,
                            "filepath": full_path,
                            "folder": root,
                            "format": ext[1:], # 'md', 'docx', 'txt'
                            "size_bytes": stat.st_size,
                            "modified_time": stat.st_mtime
                        })
                    except Exception as e:
                        print(f"Error reading file stat for {full_path}: {e}")

    # Sort by modification time descending
    documents.sort(key=lambda x: x["modified_time"], reverse=True)
    return documents


def parse_markdown_or_txt(content: str) -> List[Dict[str, Any]]:
    """Parse headings and sections from Markdown or Text content."""
    lines = content.splitlines()
    sections = []
    current_title = "Document Overview"
    current_level = 1
    current_lines = []

    for line in lines:
        # Check for Markdown heading e.g. # Title, ## Subtitle
        match = re.match(r'^(#{1,6})\s+(.+)$', line.strip())
        if match:
            # Save previous section if it has content
            if current_lines or sections:
                sections.append({
                    "title": current_title,
                    "level": current_level,
                    "content": "\n".join(current_lines).strip()
                })
            current_level = len(match.group(1))
            current_title = match.group(2).strip()
            current_lines = []
        else:
            # Check for standard text uppercase title heuristic e.g. "INTRODUCTION:"
            txt_heading_match = re.match(r'^([A-Z0-9\s_\-]{3,50}):$', line.strip())
            if txt_heading_match and not line.startswith('#'):
                if current_lines or sections:
                    sections.append({
                        "title": current_title,
                        "level": current_level,
                        "content": "\n".join(current_lines).strip()
                    })
                current_level = 2
                current_title = txt_heading_match.group(1).strip()
                current_lines = []
            else:
                current_lines.append(line)

    if current_lines or not sections:
        sections.append({
            "title": current_title,
            "level": current_level,
            "content": "\n".join(current_lines).strip()
        })

    return sections


def parse_docx(filepath: str) -> List[Dict[str, Any]]:
    """Parse headings and section text from a .docx file."""
    doc = Document(filepath)
    sections = []
    current_title = "Document Overview"
    current_level = 1
    current_lines = []

    for p in doc.paragraphs:
        style_name = p.style.name if p.style else ""
        text = p.text.strip()
        
        # Check if paragraph is a Heading
        if style_name.startswith('Heading') or style_name == 'Title':
            if current_lines or sections:
                sections.append({
                    "title": current_title,
                    "level": current_level,
                    "content": "\n".join(current_lines).strip()
                })
            
            if style_name == 'Title':
                current_level = 1
            else:
                try:
                    current_level = int(style_name.replace('Heading', '').strip())
                except ValueError:
                    current_level = 2
            current_title = text if text else "Untitled Section"
            current_lines = []
        else:
            if p.text:
                current_lines.append(p.text)

    if current_lines or not sections:
        sections.append({
            "title": current_title,
            "level": current_level,
            "content": "\n".join(current_lines).strip()
        })

    return sections


def read_document(filepath: str) -> Dict[str, Any]:
    """Read document content and extract structural headings/sections."""
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"File not found: {filepath}")

    ext = os.path.splitext(filepath)[1].lower()
    
    if ext == '.docx':
        doc = Document(filepath)
        full_text = "\n\n".join([p.text for p in doc.paragraphs if p.text])
        sections = parse_docx(filepath)
    else:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            full_text = f.read()
        sections = parse_markdown_or_txt(full_text)

    headings = [{"title": s["title"], "level": s["level"]} for s in sections]

    return {
        "filepath": filepath,
        "filename": os.path.basename(filepath),
        "format": ext[1:],
        "full_text": full_text,
        "headings": headings,
        "sections": sections
    }


def create_document(filepath: str, format_type: str, title: str, content: str) -> Dict[str, Any]:
    """Create a new document file (.md, .txt, or .docx)."""
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    format_type = format_type.lower()

    if format_type == "docx":
        doc = Document()
        doc.add_heading(title, level=1)
        for line in content.splitlines():
            if line.strip():
                if line.startswith('#'):
                    # Heading in content
                    level = len(line) - len(line.lstrip('#'))
                    heading_text = line.lstrip('#').strip()
                    doc.add_heading(heading_text, level=min(level, 4))
                else:
                    doc.add_paragraph(line)
        doc.save(filepath)
    elif format_type == "md":
        formatted_content = f"# {title}\n\n{content}"
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(formatted_content)
    else: # txt
        formatted_content = f"{title.upper()}\n{'='*len(title)}\n\n{content}"
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(formatted_content)

    return read_document(filepath)


def save_updated_sections(filepath: str, format_type: str, sections: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Save an updated list of sections back to disk in specified format."""
    format_type = format_type.lower()
    
    if format_type == "docx":
        doc = Document()
        for idx, sec in enumerate(sections):
            level = max(1, min(sec.get("level", 2), 4))
            doc.add_heading(sec["title"], level=level)
            body = sec.get("content", "")
            if body:
                for paragraph in body.split("\n\n"):
                    if paragraph.strip():
                        doc.add_paragraph(paragraph.strip())
        doc.save(filepath)
    elif format_type == "md":
        md_text = ""
        for sec in sections:
            prefix = "#" * max(1, min(sec.get("level", 2), 6))
            md_text += f"{prefix} {sec['title']}\n\n{sec.get('content', '')}\n\n"
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(md_text.strip() + "\n")
    else: # txt
        txt_text = ""
        for sec in sections:
            txt_text += f"{sec['title'].upper()}:\n{'-'*len(sec['title'])}\n{sec.get('content', '')}\n\n"
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(txt_text.strip() + "\n")

    return read_document(filepath)
