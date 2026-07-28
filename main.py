import os
import shutil
from typing import List, Dict, Any, Optional
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse
from pydantic import BaseModel

import config
from config import load_config, save_config
import doc_service
import chat_manager
from ai_doc_assistant import process_document_update, generate_repo_documentation, ONBOARDING_GREETING

app = FastAPI(title="Technical Documentation Creator")

# Models for request validation
class ConfigUpdateRequest(BaseModel):
    active_provider: Optional[str] = None
    document_paths: Optional[List[str]] = None
    local_config: Optional[Dict[str, Any]] = None
    cloud_config: Optional[Dict[str, Any]] = None

class CreateChatRequest(BaseModel):
    title: Optional[str] = "New Conversation"

class SetDocumentRequest(BaseModel):
    filepath: str

class CreateDocumentRequest(BaseModel):
    chat_id: Optional[str] = None
    format: str # 'docx', 'md', 'txt'
    title: str
    content: str
    target_folder: Optional[str] = None

class SendMessageRequest(BaseModel):
    text: str
    provider: Optional[str] = None # Optional override ('local' or 'cloud')

class AnalyzeRepoRequest(BaseModel):
    repo_source: str # Local folder path or GitHub URL
    chat_id: Optional[str] = None
    doc_option: str = "new" # 'current', 'new', 'existing'
    target_filepath: Optional[str] = None
    format: Optional[str] = "md" # 'md', 'docx', 'txt'
    new_title: Optional[str] = None
    provider: Optional[str] = None


# --- CONFIG ENDPOINTS ---

@app.get("/api/config")
def get_app_config():
    """Get current configuration."""
    return load_config()

@app.post("/api/config")
def update_app_config(req: ConfigUpdateRequest):
    """Update application configuration."""
    current = load_config()
    update_data = {}
    if req.active_provider:
        update_data["active_provider"] = req.active_provider
    if req.document_paths is not None:
        update_data["document_paths"] = req.document_paths
    if req.local_config:
        current_local = current.get("local_config", {})
        current_local.update(req.local_config)
        update_data["local_config"] = current_local
    if req.cloud_config:
        current_cloud = current.get("cloud_config", {})
        current_cloud.update(req.cloud_config)
        update_data["cloud_config"] = current_cloud
        
    updated = save_config(update_data)
    return {"status": "success", "config": updated}


# --- DOCUMENTS ENDPOINTS ---

@app.get("/api/documents")
def get_documents():
    """List all available documents in configured document paths."""
    cfg = load_config()
    paths = cfg.get("document_paths", [config.DEFAULT_DOCS_DIR])
    docs = doc_service.list_all_documents(paths)
    return {"documents": docs, "folders": paths}

@app.get("/api/documents/content")
def get_document_content(filepath: str):
    """Read a document content and structural outline."""
    try:
        data = doc_service.read_document(filepath)
        return data
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/documents/create")
def create_new_document(req: CreateDocumentRequest):
    """Create a new document file."""
    cfg = load_config()
    paths = cfg.get("document_paths", [config.DEFAULT_DOCS_DIR])
    primary_folder = req.target_folder or paths[0]
    
    clean_title = "".join(c for c in req.title if c.isalnum() or c in (' ', '_', '-')).strip()
    if not clean_title:
        clean_title = "Untitled_Doc"
        
    filename = f"{clean_title}.{req.format.lower()}"
    filepath = os.path.join(primary_folder, filename)
    
    try:
        doc_info = doc_service.create_document(filepath, req.format, req.title, req.content)
        
        # If linked to a chat, update chat active document
        if req.chat_id:
            chat_manager.update_chat_active_document(req.chat_id, filepath)
            chat_manager.add_chat_message(
                req.chat_id, 
                "assistant", 
                f"✅ New document **{filename}** created successfully! You can now send me technical details or content to add.",
                doc_update_info=doc_info
            )
            
        return {"status": "success", "document": doc_info}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/api/documents/upload")
async def upload_document(
    file: UploadFile = File(...), 
    chat_id: Optional[str] = Form(None)
):
    """Upload an existing .docx, .md, or .txt file."""
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in ['.docx', '.md', '.txt']:
        raise HTTPException(status_code=400, detail="Invalid file type. Only .docx, .md, and .txt are supported.")

    cfg = load_config()
    paths = cfg.get("document_paths", [config.DEFAULT_DOCS_DIR])
    primary_folder = paths[0]
    os.makedirs(primary_folder, exist_ok=True)
    
    target_path = os.path.join(primary_folder, file.filename)
    with open(target_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    try:
        doc_info = doc_service.read_document(target_path)
        if chat_id:
            chat_manager.update_chat_active_document(chat_id, target_path)
            chat_manager.add_chat_message(
                chat_id, 
                "assistant", 
                f"📂 Loaded existing document **{file.filename}**. I have analyzed its titles and sections. What would you like to add or update?",
                doc_update_info=doc_info
            )
        return {"status": "success", "document": doc_info}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# --- CHAT ENDPOINTS ---

@app.get("/api/chats")
def get_chats():
    """List all chat sessions."""
    return {"chats": chat_manager.list_chats()}

@app.post("/api/chats")
def create_chat(req: CreateChatRequest):
    """Create a new chat conversation."""
    chat = chat_manager.create_chat(req.title or "New Conversation")
    return chat

@app.get("/api/chats/{chat_id}")
def get_chat_detail(chat_id: str):
    """Get chat details and message history."""
    chat = chat_manager.get_chat(chat_id)
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")
    return chat

@app.delete("/api/chats/{chat_id}")
def delete_chat_session(chat_id: str):
    """Delete a chat session."""
    success = chat_manager.delete_chat(chat_id)
    return {"status": "success" if success else "failed"}

@app.post("/api/chats/{chat_id}/set-document")
def set_chat_document(chat_id: str, req: SetDocumentRequest):
    """Link an existing document file to a chat session."""
    chat = chat_manager.update_chat_active_document(chat_id, req.filepath)
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")
        
    doc_info = doc_service.read_document(req.filepath)
    chat_manager.add_chat_message(
        chat_id,
        "assistant",
        f"📂 Attached document **{doc_info['filename']}** to this conversation. Send me content to add or edit!",
        doc_update_info=doc_info
    )
    return {"status": "success", "chat": chat_manager.get_chat(chat_id)}

@app.post("/api/chats/{chat_id}/messages")
def send_message(chat_id: str, req: SendMessageRequest):
    """Send user message and receive AI document assistant response."""
    chat = chat_manager.get_chat(chat_id)
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")

    user_text = req.text.strip()
    if not user_text:
        raise HTTPException(status_code=400, detail="Message text cannot be empty")

    # 1. Add user message
    chat_manager.add_chat_message(chat_id, "user", user_text)

    # 2. Check if chat has an active document
    active_doc_path = chat.get("active_doc_path")
    
    if not active_doc_path or not os.path.exists(active_doc_path):
        # Prompt user to create or select a document first
        ai_reply = (
            "Please select or create a document first before adding technical details.\n\n"
            "You can:\n"
            "• Click **Create New Document** below\n"
            "• Select an **Existing Document** from the Library tab"
        )
        chat_manager.add_chat_message(chat_id, "assistant", ai_reply)
        return {"chat": chat_manager.get_chat(chat_id)}

    # 3. Process document update with AI (passing chat history for conversational memory)
    try:
        updated_doc, explanation = process_document_update(
            filepath=active_doc_path,
            user_input=user_text,
            chat_history=chat.get("messages", []),
            provider=req.provider
        )
        
        # Add assistant reply with updated document metadata
        chat_manager.add_chat_message(
            chat_id,
            "assistant",
            f"📝 **Document Updated!**\n\n{explanation}",
            doc_update_info=updated_doc
        )
    except Exception as e:
        chat_manager.add_chat_message(
            chat_id,
            "assistant",
            f"❌ An error occurred while updating the document: {str(e)}"
        )

    return {"chat": chat_manager.get_chat(chat_id)}

@app.post("/api/repository/analyze")
def analyze_repository(req: AnalyzeRepoRequest):
    """Analyze a local codebase or GitHub repository URL and merge technical documentation into chosen document."""
    repo_src = req.repo_source.strip()
    if not repo_src:
        raise HTTPException(status_code=400, detail="Repository source (folder path or GitHub URL) cannot be empty.")

    cfg = load_config()
    paths = cfg.get("document_paths", [config.DEFAULT_DOCS_DIR])
    primary_folder = paths[0]

    target_path = None

    # Determine target document
    if req.doc_option == "current" and req.chat_id:
        chat = chat_manager.get_chat(req.chat_id)
        if chat and chat.get("active_doc_path") and os.path.exists(chat.get("active_doc_path")):
            target_path = chat.get("active_doc_path")

    if not target_path and req.doc_option == "existing" and req.target_filepath:
        if os.path.exists(req.target_filepath):
            target_path = req.target_filepath

    if not target_path: # Default create new document
        doc_format = (req.format or "md").lower()
        repo_name = repo_src.split("/")[-1].replace(".git", "").strip() or "Repo_Documentation"
        clean_title = req.new_title or f"Wiki - {repo_name}"
        filename = f"{clean_title}.{doc_format}"
        target_path = os.path.join(primary_folder, filename)
        doc_service.create_document(target_path, doc_format, clean_title, f"Technical Documentation Wiki for {repo_name}")

    try:
        # Generate repo documentation and merge into target document
        updated_doc, explanation = generate_repo_documentation(
            repo_input=repo_src,
            target_filepath=target_path,
            provider=req.provider
        )

        if req.chat_id:
            chat_manager.update_chat_active_document(req.chat_id, target_path)
            chat_manager.add_chat_message(
                req.chat_id,
                "user",
                f"⚡ Analyze repository: **{repo_src}**"
            )
            chat_manager.add_chat_message(
                req.chat_id,
                "assistant",
                f"✅ **Repository Documentation Generated!**\n\n{explanation}",
                doc_update_info=updated_doc
            )

        return {"status": "success", "document": updated_doc, "explanation": explanation}
    except Exception as e:
        if req.chat_id:
            chat_manager.add_chat_message(
                req.chat_id,
                "assistant",
                f"❌ Error analyzing repository: {str(e)}"
            )
        raise HTTPException(status_code=400, detail=str(e))


# Mount static directory for frontend
static_dir = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")

@app.get("/", response_class=HTMLResponse)
def index_page():
    index_file = os.path.join(static_dir, "index.html")
    if os.path.exists(index_file):
        with open(index_file, "r", encoding="utf-8") as f:
            return f.read()
    return "<h1>Technical Documentation Creator API is Running</h1>"

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
