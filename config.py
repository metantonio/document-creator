import json
import os
from typing import List, Dict, Any

CONFIG_FILE_PATH = os.path.join(os.path.dirname(__file__), "config.json")
DEFAULT_DOCS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "docs_storage"))

DEFAULT_CONFIG: Dict[str, Any] = {
    "active_provider": "local",  # 'local' or 'cloud'
    "document_paths": [
        DEFAULT_DOCS_DIR
    ],
    "local_config": {
        "name": "Local LLM (Ollama / LM Studio / llama.cpp)",
        "base_url": "http://localhost:11434/v1",
        "model": "llama3",
        "api_key": "ollama",
        "temperature": 0.3,
        "max_tokens": 0
    },
    "cloud_config": {
        "name": "Cloud LLM (OpenAI / OpenRouter / Groq)",
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o",
        "api_key": "",
        "temperature": 0.3,
        "max_tokens": 32768
    },
    "teams_config": {
        "tenant_id": "",
        "client_id": "",
        "client_secret": "",
        "default_team_id": "",
        "default_channel_id": ""
    }
}

def deep_merge(target: Dict[str, Any], source: Dict[str, Any]) -> Dict[str, Any]:
    """Recursively merge source dict into target dict."""
    for key, value in source.items():
        if isinstance(value, dict) and key in target and isinstance(target[key], dict):
            deep_merge(target[key], value)
        else:
            target[key] = value
    return target

def load_config() -> Dict[str, Any]:
    """Load configuration from config.json or fallback to DEFAULT_CONFIG."""
    config = json.loads(json.dumps(DEFAULT_CONFIG))
    if os.path.exists(CONFIG_FILE_PATH):
        try:
            with open(CONFIG_FILE_PATH, "r", encoding="utf-8") as f:
                saved = json.load(f)
                deep_merge(config, saved)
        except Exception as e:
            print(f"Error loading config.json: {e}")
    
    # Ensure document_paths exist on disk
    for path in config.get("document_paths", []):
        try:
            os.makedirs(path, exist_ok=True)
        except Exception as e:
            print(f"Could not create doc directory {path}: {e}")
            
    return config

def save_config(new_config: Dict[str, Any]) -> Dict[str, Any]:
    """Save configuration to config.json."""
    current = load_config()
    deep_merge(current, new_config)
    
    # Ensure document paths exist
    for path in current.get("document_paths", []):
        try:
            os.makedirs(path, exist_ok=True)
        except Exception as e:
            print(f"Could not create doc directory {path}: {e}")

    with open(CONFIG_FILE_PATH, "w", encoding="utf-8") as f:
        json.dump(current, f, indent=2)
        
    return current

# Initialize on import
APP_CONFIG = load_config()
