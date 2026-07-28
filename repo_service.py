import os
import shutil
import tempfile
import subprocess
import re
from typing import Dict, Any, List, Optional, Tuple

IGNORE_DIRS = {
    '.git', '.svn', '.hg', 'node_modules', 'venv', 'env', '.venv',
    '__pycache__', '.idea', '.vscode', 'dist', 'build', 'target',
    'bin', 'obj', '.next', '.nuxt', 'coverage'
}

IGNORE_EXTS = {
    '.png', '.jpg', '.jpeg', '.gif', '.ico', '.svg', '.webp',
    '.pdf', '.zip', '.tar', '.gz', '.7z', '.exe', '.dll', '.so',
    '.dylib', '.pyc', '.pyo', '.db', '.sqlite', '.woff', '.woff2', '.ttf'
}

KEY_FILES = [
    'README.md', 'readme.md', 'README.txt',
    'package.json', 'requirements.txt', 'Cargo.toml', 'go.mod',
    'pom.xml', 'build.gradle', 'pyproject.toml', 'Dockerfile',
    'docker-compose.yml', 'main.py', 'app.py', 'index.js', 'index.ts',
    'App.tsx', 'main.go', 'main.rs', 'config.py'
]

def is_github_url(url_or_path: str) -> bool:
    """Check if input string is a GitHub or Git repository URL."""
    url_or_path = url_or_path.strip()
    return url_or_path.startswith("http://") or url_or_path.startswith("https://") or url_or_path.endswith(".git")

def fetch_github_repo(repo_url: str) -> str:
    """Clone a remote GitHub repository to a temporary directory."""
    temp_dir = tempfile.mkdtemp(prefix="repo_wiki_")
    try:
        cmd = ["git", "clone", "--depth", "1", repo_url, temp_dir]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if res.returncode != 0:
            raise Exception(f"Git clone failed: {res.stderr or res.stdout}")
        return temp_dir
    except Exception as e:
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)
        raise Exception(f"Could not clone repository '{repo_url}': {str(e)}")

def build_directory_tree(root_path: str, max_depth: int = 3) -> str:
    """Generate a clean ASCII directory tree representation."""
    tree_lines = []
    
    def _scan_dir(current_path: str, depth: int, prefix: str):
        if depth > max_depth:
            return
        try:
            entries = sorted(os.listdir(current_path))
        except PermissionError:
            return
            
        entries = [e for e in entries if e not in IGNORE_DIRS]
        
        for i, entry in enumerate(entries):
            full_path = os.path.join(current_path, entry)
            is_last = (i == len(entries) - 1)
            connector = "└── " if is_last else "├── "
            
            if os.path.isdir(full_path):
                tree_lines.append(f"{prefix}{connector}{entry}/")
                new_prefix = prefix + ("    " if is_last else "│   ")
                _scan_dir(full_path, depth + 1, new_prefix)
            else:
                ext = os.path.splitext(entry)[1].lower()
                if ext not in IGNORE_EXTS:
                    tree_lines.append(f"{prefix}{connector}{entry}")

    tree_lines.append(os.path.basename(root_path) + "/")
    _scan_dir(root_path, 1, "")
    return "\n".join(tree_lines[:150]) # Limit lines for LLM context window

def extract_repo_context(root_path: str) -> Dict[str, Any]:
    """Scan local repo folder and extract key files, structure, and dependencies."""
    if not os.path.exists(root_path):
        raise FileNotFoundError(f"Repository path does not exist: {root_path}")

    dir_tree = build_directory_tree(root_path)
    
    extracted_key_files = {}
    sampled_code_files = {}

    for root, dirs, files in os.walk(root_path):
        # Filter out ignored directories
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
        
        for f in files:
            ext = os.path.splitext(f)[1].lower()
            if ext in IGNORE_EXTS:
                continue

            rel_path = os.path.relpath(os.path.join(root, f), root_path)
            full_filepath = os.path.join(root, f)

            # 1. Check if key configuration/readme file
            if f in KEY_FILES or rel_path in KEY_FILES:
                try:
                    with open(full_filepath, "r", encoding="utf-8", errors="replace") as file_obj:
                        extracted_key_files[rel_path] = file_obj.read(5000) # first 5kb
                except Exception as e:
                    print(f"Error reading key file {rel_path}: {e}")

            # 2. Sample important source code files (e.g. .py, .js, .ts, .go, .rs, .java)
            elif ext in ['.py', '.js', '.ts', '.tsx', '.jsx', '.go', '.rs', '.java', '.c', '.cpp', '.cs']:
                if len(sampled_code_files) < 10:
                    try:
                        with open(full_filepath, "r", encoding="utf-8", errors="replace") as file_obj:
                            sampled_code_files[rel_path] = file_obj.read(2500)
                    except Exception as e:
                        pass

    return {
        "repo_name": os.path.basename(root_path),
        "directory_tree": dir_tree,
        "key_files": extracted_key_files,
        "sampled_code_files": sampled_code_files
    }


def analyze_repo_source(repo_input: str) -> Tuple[Dict[str, Any], Optional[str]]:
    """
    Given a local folder path or GitHub URL:
    Returns (repo_context_dict, temp_dir_to_clean_up_or_None).
    """
    repo_input = repo_input.strip()
    if is_github_url(repo_input):
        temp_dir = fetch_github_repo(repo_input)
        context = extract_repo_context(temp_dir)
        context["repo_name"] = repo_input.split("/")[-1].replace(".git", "")
        return context, temp_dir
    else:
        abs_path = os.path.abspath(repo_input)
        context = extract_repo_context(abs_path)
        return context, None
