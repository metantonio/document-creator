import os
import shutil
import tempfile
import subprocess
import re
import urllib.request
import json
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

def fetch_github_metadata(repo_url: str) -> Dict[str, Any]:
    """Fetch GitHub repository stats (Stars, Forks, Open Issues, License, Branch) via public API."""
    metadata = {
        "stars": 0,
        "forks": 0,
        "open_issues": 0,
        "open_prs": 0,
        "license": "N/A",
        "language": "N/A",
        "default_branch": "main",
        "description": ""
    }
    
    match = re.search(r'github\.com/([^/]+)/([^/\.]+)', repo_url)
    if not match:
        return metadata

    owner, repo = match.group(1), match.group(2)
    headers = {
        'User-Agent': 'DocCraft-AI-Assistant/1.0',
        'Accept': 'application/vnd.github.v3+json'
    }

    try:
        api_url = f"https://api.github.com/repos/{owner}/{repo}"
        req = urllib.request.Request(api_url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            metadata["stars"] = data.get("stargazers_count", 0)
            metadata["forks"] = data.get("forks_count", 0)
            metadata["open_issues"] = data.get("open_issues_count", 0)
            metadata["language"] = data.get("language") or "N/A"
            metadata["default_branch"] = data.get("default_branch") or "main"
            metadata["description"] = data.get("description") or ""
            lic = data.get("license") or {}
            metadata["license"] = lic.get("name") if isinstance(lic, dict) else "N/A"
    except Exception as e:
        print(f"Note: Could not fetch GitHub API metadata: {e}")

    try:
        pr_url = f"https://api.github.com/repos/{owner}/{repo}/pulls?state=open&per_page=1"
        req = urllib.request.Request(pr_url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            prs = json.loads(resp.read().decode('utf-8'))
            metadata["open_prs"] = len(prs)
    except Exception:
        pass

    return metadata

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
    return "\n".join(tree_lines[:150])

def scan_github_actions(root_path: str) -> Dict[str, str]:
    """Scan .github/workflows directory for CI/CD workflow YAML files."""
    workflows = {}
    workflows_dir = os.path.join(root_path, ".github", "workflows")
    if os.path.exists(workflows_dir) and os.path.isdir(workflows_dir):
        for f in os.listdir(workflows_dir):
            if f.endswith('.yml') or f.endswith('.yaml'):
                full_path = os.path.join(workflows_dir, f)
                try:
                    with open(full_path, 'r', encoding='utf-8', errors='replace') as file_obj:
                        workflows[f] = file_obj.read(3000)
                except Exception:
                    pass
    return workflows

def scan_env_and_configs(root_path: str) -> Dict[str, str]:
    """Scan for environment variables and config files (.env, config.py, settings, etc.)."""
    env_configs = {}
    target_names = ['.env.example', '.env', 'docker-compose.yml', 'Dockerfile', 'config.py', 'settings.py', 'application.properties', 'appsettings.json']
    
    for root, dirs, files in os.walk(root_path):
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
        for f in files:
            rel_path = os.path.relpath(os.path.join(root, f), root_path)
            if f in target_names or any(rel_path.endswith(t) for t in target_names):
                full_path = os.path.join(root, f)
                try:
                    with open(full_path, 'r', encoding='utf-8', errors='replace') as file_obj:
                        env_configs[rel_path] = file_obj.read(2500)
                except Exception:
                    pass
    return env_configs

def scan_file_imports_graph(root_path: str) -> Dict[str, List[str]]:
    """Scan source files and build import/dependency mapping between files."""
    import_map = {}
    
    for root, dirs, files in os.walk(root_path):
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
        for f in files:
            ext = os.path.splitext(f)[1].lower()
            if ext in ['.py', '.js', '.ts', '.tsx', '.jsx', '.go', '.java', '.cs', '.rs', '.html']:
                rel_path = os.path.relpath(os.path.join(root, f), root_path)
                full_path = os.path.join(root, f)
                try:
                    with open(full_path, 'r', encoding='utf-8', errors='replace') as file_obj:
                        lines = file_obj.readlines()[:150]
                        imported_modules = []
                        for line in lines:
                            line_s = line.strip()
                            if line_s.startswith('import ') or line_s.startswith('from ') or 'require(' in line_s or 'src=' in line_s:
                                imported_modules.append(line_s)
                            elif any(kw in line_s for kw in ['.json', '.csv', '.sql', '.backup', 'fetch(', 'fs.read']):
                                match = re.search(r'[\'\"]([^\'\"]+\.(?:json|csv|sql|js|py|html))[\'\"]', line_s)
                                if match:
                                    imported_modules.append(f"references {match.group(1)}")
                        if imported_modules:
                            import_map[rel_path] = imported_modules[:10]
                except Exception:
                    pass
    return import_map

def extract_repo_context(root_path: str, repo_url: Optional[str] = None) -> Dict[str, Any]:
    """Scan local repo folder and extract key files, structure, dependencies, GitHub stats, workflows, and AST imports."""
    if not os.path.exists(root_path):
        raise FileNotFoundError(f"Repository path does not exist: {root_path}")

    dir_tree = build_directory_tree(root_path)
    
    extracted_key_files = {}
    sampled_code_files = {}

    for root, dirs, files in os.walk(root_path):
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
        
        for f in files:
            ext = os.path.splitext(f)[1].lower()
            if ext in IGNORE_EXTS:
                continue

            rel_path = os.path.relpath(os.path.join(root, f), root_path)
            full_filepath = os.path.join(root, f)

            if f in KEY_FILES or rel_path in KEY_FILES:
                try:
                    with open(full_filepath, "r", encoding="utf-8", errors="replace") as file_obj:
                        extracted_key_files[rel_path] = file_obj.read(5000)
                except Exception as e:
                    print(f"Error reading key file {rel_path}: {e}")

            elif ext in ['.py', '.js', '.ts', '.tsx', '.jsx', '.go', '.rs', '.java', '.c', '.cpp', '.cs']:
                if len(sampled_code_files) < 15:
                    try:
                        with open(full_filepath, "r", encoding="utf-8", errors="replace") as file_obj:
                            sampled_code_files[rel_path] = file_obj.read(2500)
                    except Exception:
                        pass

    github_meta = fetch_github_metadata(repo_url) if repo_url else {}
    workflows = scan_github_actions(root_path)
    env_configs = scan_env_and_configs(root_path)
    import_graph = scan_file_imports_graph(root_path)

    return {
        "repo_name": os.path.basename(root_path),
        "directory_tree": dir_tree,
        "key_files": extracted_key_files,
        "sampled_code_files": sampled_code_files,
        "github_metadata": github_meta,
        "github_actions": workflows,
        "env_configs": env_configs,
        "import_graph": import_graph
    }

def analyze_repo_source(repo_input: str) -> Tuple[Dict[str, Any], Optional[str]]:
    """
    Given a local folder path or GitHub URL:
    Returns (repo_context_dict, temp_dir_to_clean_up_or_None).
    """
    repo_input = repo_input.strip()
    if is_github_url(repo_input):
        temp_dir = fetch_github_repo(repo_input)
        context = extract_repo_context(temp_dir, repo_url=repo_input)
        context["repo_name"] = repo_input.split("/")[-1].replace(".git", "")
        return context, temp_dir
    else:
        abs_path = os.path.abspath(repo_input)
        context = extract_repo_context(abs_path)
        return context, None
