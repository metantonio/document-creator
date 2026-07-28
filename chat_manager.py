import json
import os
import uuid
import time
from typing import List, Dict, Any, Optional
from ai_doc_assistant import ONBOARDING_GREETING

CHATS_DIR = os.path.join(os.path.dirname(__file__), "chats_storage")
os.makedirs(CHATS_DIR, exist_ok=True)

def _get_chat_filepath(chat_id: str) -> str:
    return os.path.join(CHATS_DIR, f"{chat_id}.json")

def list_chats() -> List[Dict[str, Any]]:
    """List all chat sessions."""
    chats = []
    for file in os.listdir(CHATS_DIR):
        if file.endswith(".json"):
            filepath = os.path.join(CHATS_DIR, file)
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    chats.append({
                        "id": data.get("id"),
                        "title": data.get("title", "Untitled Conversation"),
                        "active_doc_path": data.get("active_doc_path"),
                        "created_at": data.get("created_at"),
                        "updated_at": data.get("updated_at"),
                        "message_count": len(data.get("messages", []))
                    })
            except Exception as e:
                print(f"Error reading chat {file}: {e}")
                
    chats.sort(key=lambda x: x.get("updated_at", 0), reverse=True)
    return chats

def create_chat(title: str = "New Conversation") -> Dict[str, Any]:
    """Create a new chat session with initial onboarding greeting."""
    chat_id = str(uuid.uuid4())
    now = time.time()
    
    initial_message = {
        "id": str(uuid.uuid4()),
        "sender": "assistant",
        "text": ONBOARDING_GREETING,
        "timestamp": now,
        "is_onboarding": True
    }
    
    chat_data = {
        "id": chat_id,
        "title": title,
        "active_doc_path": None,
        "created_at": now,
        "updated_at": now,
        "messages": [initial_message]
    }
    
    with open(_get_chat_filepath(chat_id), "w", encoding="utf-8") as f:
        json.dump(chat_data, f, indent=2)
        
    return chat_data

def get_chat(chat_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve chat object by ID."""
    filepath = _get_chat_filepath(chat_id)
    if not os.path.exists(filepath):
        return None
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"Error reading chat {chat_id}: {e}")
        return None

def save_chat(chat_data: Dict[str, Any]) -> Dict[str, Any]:
    """Persist chat object to disk."""
    chat_data["updated_at"] = time.time()
    filepath = _get_chat_filepath(chat_data["id"])
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(chat_data, f, indent=2)
    return chat_data

def update_chat_active_document(chat_id: str, doc_path: str) -> Optional[Dict[str, Any]]:
    """Link a document to the chat session."""
    chat = get_chat(chat_id)
    if not chat:
        return None
    chat["active_doc_path"] = doc_path
    if chat.get("title") == "New Conversation":
        filename = os.path.basename(doc_path)
        chat["title"] = f"Doc: {filename}"
    return save_chat(chat)

def add_chat_message(
    chat_id: str, 
    sender: str, 
    text: str, 
    doc_update_info: Optional[Dict[str, Any]] = None
) -> Optional[Dict[str, Any]]:
    """Append a message to the chat history."""
    chat = get_chat(chat_id)
    if not chat:
        return None
        
    msg = {
        "id": str(uuid.uuid4()),
        "sender": sender,
        "text": text,
        "timestamp": time.time(),
        "doc_update_info": doc_update_info
    }
    
    chat["messages"].append(msg)
    return save_chat(chat)

def delete_chat(chat_id: str) -> bool:
    """Delete a chat session."""
    filepath = _get_chat_filepath(chat_id)
    if os.path.exists(filepath):
        os.remove(filepath)
        return True
    return False
