from openai import OpenAI
from typing import List, Dict, Any
from config import load_config

def get_llm_client(provider: str = None):
    """Instantiate OpenAI-compatible client for local or cloud LLMs."""
    cfg = load_config()
    target_provider = provider or cfg.get("active_provider", "local")
    
    if target_provider == "local":
        provider_cfg = cfg.get("local_config", {})
        base_url = provider_cfg.get("base_url", "http://localhost:11434/v1")
        api_key = provider_cfg.get("api_key", "ollama")
        model = provider_cfg.get("model", "llama3")
        temp = float(provider_cfg.get("temperature", 0.3))
        max_tokens = int(provider_cfg.get("max_tokens", 4096))
    else:
        provider_cfg = cfg.get("cloud_config", {})
        base_url = provider_cfg.get("base_url", "https://api.openai.com/v1")
        api_key = provider_cfg.get("api_key", "")
        model = provider_cfg.get("model", "gpt-4o")
        temp = float(provider_cfg.get("temperature", 0.3))
        max_tokens = int(provider_cfg.get("max_tokens", 4096))

    client = OpenAI(
        base_url=base_url,
        api_key=api_key or "empty_key"
    )
    return client, model, temp, max_tokens, target_provider

def generate_chat_response(messages: List[Dict[str, str]], provider: str = None) -> str:
    """Send chat prompt to the selected LLM provider and return response string."""
    try:
        client, model, temperature, max_tokens, provider_name = get_llm_client(provider)
        
        kwargs = {
            "model": model,
            "messages": messages,
            "temperature": temperature
        }
        # Only set max_tokens if positive integer, allowing local LLMs to generate full responses without truncation if max_tokens is <= 0 or None
        if max_tokens and max_tokens > 0:
            kwargs["max_tokens"] = max_tokens

        response = client.chat.completions.create(**kwargs)
        
        if response.choices and len(response.choices) > 0:
            return response.choices[0].message.content or ""
        return ""
    except Exception as e:
        error_msg = str(e)
        if "Connection refused" in error_msg or "Failed to connect" in error_msg:
            return f"❌ Connection Error: Could not connect to the {provider or 'selected'} LLM service. Please make sure your local server (Ollama / llama.cpp / LM Studio) or internet connection is active."
        elif "401" in error_msg or "Incorrect API key" in error_msg:
            return f"❌ Authentication Error: Invalid API Key for {provider or 'selected'} provider. Please check your config.py settings in the UI."
        return f"❌ Error communicating with LLM ({provider or 'selected'}): {error_msg}"
