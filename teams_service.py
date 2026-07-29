import os
import json
import urllib.request
import urllib.parse
import urllib.error
from typing import Dict, Any, List, Optional, Tuple

GRAPH_API_BASE = "https://graph.microsoft.com/v1.0"

def get_auth_token(tenant_id: str, client_id: str, client_secret: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Obtains OAuth2 access token from Azure AD / Microsoft Entra ID using Client Credentials Grant.
    Returns (access_token, error_message).
    """
    if not tenant_id or not client_id or not client_secret:
        return None, "Missing Azure AD credentials (Tenant ID, Client ID, or Client Secret)."

    token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
    headers = {'Content-Type': 'application/x-www-form-urlencoded'}
    body = urllib.parse.urlencode({
        'client_id': client_id,
        'client_secret': client_secret,
        'scope': 'https://graph.microsoft.com/.default',
        'grant_type': 'client_credentials'
    }).encode('utf-8')

    try:
        req = urllib.request.Request(token_url, data=body, headers=headers, method='POST')
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            token = data.get('access_token')
            if token:
                return token, None
            return None, "No access_token received from Azure AD."
    except urllib.error.HTTPError as e:
        err_body = e.read().decode('utf-8', errors='replace')
        return None, f"Azure AD Auth Error ({e.code}): {err_body}"
    except Exception as e:
        return None, f"Connection Error: {str(e)}"


def test_teams_connection(tenant_id: str, client_id: str, client_secret: str) -> Dict[str, Any]:
    """Tests Azure AD authentication credentials."""
    token, err = get_auth_token(tenant_id, client_id, client_secret)
    if err:
        return {"status": "error", "connected": False, "detail": err}
    return {"status": "success", "connected": True, "detail": "Successfully authenticated with Microsoft Azure AD & Graph API!"}


def fetch_graph_api(url: str, token: str) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """Helper to issue GET requests to Microsoft Graph API."""
    headers = {
        'Authorization': f'Bearer {token}',
        'Accept': 'application/json'
    }
    try:
        req = urllib.request.Request(url, headers=headers, method='GET')
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            return data, None
    except urllib.error.HTTPError as e:
        err_body = e.read().decode('utf-8', errors='replace')
        return None, f"Graph API Error ({e.code}): {err_body}"
    except Exception as e:
        return None, f"Request failed: {str(e)}"


def fetch_channel_messages(
    tenant_id: str, client_id: str, client_secret: str, team_id: str, channel_id: str, limit: int = 20
) -> Tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
    """Fetches channel messages from a Microsoft Teams team and channel."""
    token, err = get_auth_token(tenant_id, client_id, client_secret)
    if err:
        return None, err

    url = f"{GRAPH_API_BASE}/teams/{team_id}/channels/{channel_id}/messages?$top={min(limit, 50)}"
    data, err = fetch_graph_api(url, token)
    if err:
        return None, err

    messages = data.get('value', [])
    return messages, None


def fetch_chat_messages(
    tenant_id: str, client_id: str, client_secret: str, chat_id: str, limit: int = 20
) -> Tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
    """Fetches messages from a 1:1 or group chat in Microsoft Teams."""
    token, err = get_auth_token(tenant_id, client_id, client_secret)
    if err:
        return None, err

    url = f"{GRAPH_API_BASE}/chats/{chat_id}/messages?$top={min(limit, 50)}"
    data, err = fetch_graph_api(url, token)
    if err:
        return None, err

    messages = data.get('value', [])
    return messages, None


def format_teams_messages_to_prompt(messages: List[Dict[str, Any]]) -> str:
    """
    Transforms raw Graph API message structures into clean, human-readable Teams chat transcripts
    optimized for ai_doc_assistant parsing.
    """
    formatted_lines = []
    
    # Graph API returns newest first, reverse so it's chronological
    ordered_messages = list(reversed(messages))
    
    for msg in ordered_messages:
        # Extract sender name
        from_user = msg.get('from', {}) or {}
        user_info = from_user.get('user', {}) or from_user.get('application', {}) or {}
        sender_name = user_info.get('displayName') or "Team Member"
        
        # Extract timestamp
        created_time = msg.get('createdDateTime', '')
        timestamp_str = ""
        if created_time:
            # Parse ISO timestamp (e.g. 2026-07-28T10:45:00Z -> 10:45 AM)
            try:
                parts = created_time.split('T')
                if len(parts) > 1:
                    time_part = parts[1][:5]
                    timestamp_str = f" [{time_part}]"
            except Exception:
                timestamp_str = ""

        # Extract content text (strip HTML tags if present)
        body = msg.get('body', {}) or {}
        content_html = body.get('content', '')
        
        # Simple HTML tag stripper
        content_text = re_strip_html(content_html) if content_html else msg.get('summary', '')
        
        if content_text and content_text.strip():
            formatted_lines.append(f"{sender_name}{timestamp_str}\n{content_text.strip()}\n")

    return "\n".join(formatted_lines)


def re_strip_html(html_str: str) -> str:
    """Removes basic HTML tags from Teams message content."""
    import re
    # Replace <br> and <p> with newlines
    clean = re.sub(r'<br\s*/?>', '\n', html_str, flags=re.IGNORECASE)
    clean = re.sub(r'</p>', '\n', clean, flags=re.IGNORECASE)
    clean = re.sub(r'<[^>]+>', '', clean)
    # Unescape HTML entities
    clean = clean.replace('&nbsp;', ' ').replace('&lt;', '<').replace('&gt;', '>').replace('&amp;', '&').replace('&quot;', '"')
    return clean.strip()
