import os
import shutil
from typing import List, Dict, Any, Optional
from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.staticfiles import StaticFiles
import json
import asyncio
from fastapi.responses import HTMLResponse, FileResponse, StreamingResponse
from pydantic import BaseModel

import config
from config import load_config, save_config
import doc_service
import chat_manager
import teams_service
import teams_desktop_service
from ai_doc_assistant import process_document_update, process_document_update_chunked, generate_repo_documentation, ONBOARDING_GREETING

app = FastAPI(title="Technical Documentation Creator")

# Models for request validation
class ConfigUpdateRequest(BaseModel):
    active_provider: Optional[str] = None
    document_paths: Optional[List[str]] = None
    local_config: Optional[Dict[str, Any]] = None
    cloud_config: Optional[Dict[str, Any]] = None
    teams_config: Optional[Dict[str, Any]] = None

class TeamsConfigRequest(BaseModel):
    tenant_id: Optional[str] = ""
    client_id: Optional[str] = ""
    client_secret: Optional[str] = ""
    default_team_id: Optional[str] = ""
    default_channel_id: Optional[str] = ""

class TeamsImportRequest(BaseModel):
    chat_id: str
    target_type: str = "channel"  # 'channel' or 'chat'
    team_id: Optional[str] = ""
    channel_id: Optional[str] = ""
    teams_chat_id: Optional[str] = ""
    limit: int = 20
    provider: Optional[str] = None

class TeamsDesktopCaptureRequest(BaseModel):
    chat_id: str
    window_title: Optional[str] = None
    delay_seconds: int = 5
    auto_scroll_up: bool = True
    scroll_depth: str = "standard"
    provider: Optional[str] = None

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
        initial_content = (req.content or "").strip()
        # If initial content contains an instruction prompt or unstructured logs, structure it!
        if len(initial_content) > 50:
            doc_info = doc_service.create_document(filepath, req.format, req.title, "")
            doc_info, _ = process_document_update(filepath, initial_content)
        else:
            doc_info = doc_service.create_document(filepath, req.format, req.title, initial_content)

        # If linked to a chat, update chat active document
        if req.chat_id:
            chat_manager.update_chat_active_document(req.chat_id, filepath)
            chat_manager.add_chat_message(
                req.chat_id, 
                "assistant", 
                f"✅ New document **{filename}** created successfully!",
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
@app.post("/api/chats/{chat_id}/messages/stream")
async def send_message_stream(chat_id: str, req: SendMessageRequest):
    """Streaming endpoint that yields stage progress events (SSE) and final response."""
    chat = chat_manager.get_chat(chat_id)
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")

    user_text = req.text.strip()
    if not user_text:
        raise HTTPException(status_code=400, detail="Message text cannot be empty")

    chat_manager.add_chat_message(chat_id, "user", user_text)
    active_doc_path = chat.get("active_doc_path")

    if not active_doc_path or not os.path.exists(active_doc_path):
        ai_reply = (
            "Please select or create a document first before adding technical details.\n\n"
            "You can:\n"
            "• Click **Create New Document** below\n"
            "• Select an **Existing Document** from the Library tab"
        )
        chat_manager.add_chat_message(chat_id, "assistant", ai_reply)
        async def empty_stream():
            yield f"data: {json.dumps({'type': 'done', 'chat': chat_manager.get_chat(chat_id)})}\n\n"
        return StreamingResponse(empty_stream(), media_type="text/event-stream")

    async def event_generator():
        import queue
        import threading
        stage_queue = queue.Queue()

        def on_progress(stage, message):
            stage_queue.put({"type": "stage", "stage": stage, "message": message})

        def run_processing():
            try:
                updated_doc, explanation = process_document_update(
                    filepath=active_doc_path,
                    user_input=user_text,
                    chat_history=chat.get("messages", []),
                    provider=req.provider,
                    progress_callback=on_progress
                )
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
            stage_queue.put({"type": "done"})

        thread = threading.Thread(target=run_processing)
        thread.start()

        while True:
            await asyncio.sleep(0.1)
            while not stage_queue.empty():
                item = stage_queue.get()
                if item["type"] == "done":
                    final_chat = chat_manager.get_chat(chat_id)
                    yield f"data: {json.dumps({'type': 'done', 'chat': final_chat})}\n\n"
                    return
                else:
                    yield f"data: {json.dumps(item)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")

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
        updated_doc, explanation = process_document_update_chunked(
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


# --- MICROSOFT TEAMS ENDPOINTS ---
@app.get("/api/teams/config")
def get_teams_config_endpoint():
    """Retrieve saved Teams configuration."""
    cfg = load_config()
    teams_cfg = cfg.get("teams_config", {})
    masked_secret = "********" if teams_cfg.get("client_secret") else ""
    return {
        "tenant_id": teams_cfg.get("tenant_id", ""),
        "client_id": teams_cfg.get("client_id", ""),
        "client_secret": masked_secret,
        "default_team_id": teams_cfg.get("default_team_id", ""),
        "default_channel_id": teams_cfg.get("default_channel_id", "")
    }

@app.post("/api/teams/config")
def save_teams_config_endpoint(req: TeamsConfigRequest):
    """Save Azure AD Teams API configuration."""
    cfg = load_config()
    existing_teams = cfg.get("teams_config", {})
    
    secret_to_save = req.client_secret
    if secret_to_save == "********":
        secret_to_save = existing_teams.get("client_secret", "")

    new_teams_cfg = {
        "tenant_id": req.tenant_id.strip(),
        "client_id": req.client_id.strip(),
        "client_secret": secret_to_save.strip(),
        "default_team_id": req.default_team_id.strip(),
        "default_channel_id": req.default_channel_id.strip()
    }
    
    save_config({"teams_config": new_teams_cfg})
    return {"status": "success", "message": "Microsoft Teams configuration saved."}

@app.post("/api/teams/test-connection")
def test_teams_connection_endpoint(req: TeamsConfigRequest):
    """Test Azure AD authentication credentials connection."""
    cfg = load_config()
    existing_teams = cfg.get("teams_config", {})
    
    secret = req.client_secret
    if secret == "********":
        secret = existing_teams.get("client_secret", "")

    res = teams_service.test_teams_connection(
        tenant_id=req.tenant_id or existing_teams.get("tenant_id", ""),
        client_id=req.client_id or existing_teams.get("client_id", ""),
        client_secret=secret
    )
    return res

@app.post("/api/teams/import")
def import_teams_messages_endpoint(req: TeamsImportRequest):
    """Fetches Teams messages from channel or chat, formats them, and updates the active document."""
    chat = chat_manager.get_chat(req.chat_id)
    if not chat:
        raise HTTPException(status_code=404, detail="Chat not found")

    active_doc_path = chat.get("active_doc_path")
    if not active_doc_path or not os.path.exists(active_doc_path):
        raise HTTPException(status_code=400, detail="Please create or select an active document first.")

    cfg = load_config()
    teams_cfg = cfg.get("teams_config", {})

    tenant_id = teams_cfg.get("tenant_id")
    client_id = teams_cfg.get("client_id")
    client_secret = teams_cfg.get("client_secret")

    if not tenant_id or not client_id or not client_secret:
        raise HTTPException(status_code=400, detail="Microsoft Teams Azure AD credentials are not configured. Please configure them in Settings -> Microsoft Teams.")

    messages = []
    err = None

    if req.target_type == "channel":
        team_id = req.team_id or teams_cfg.get("default_team_id")
        channel_id = req.channel_id or teams_cfg.get("default_channel_id")
        if not team_id or not channel_id:
            raise HTTPException(status_code=400, detail="Team ID and Channel ID are required for channel imports.")
        messages, err = teams_service.fetch_channel_messages(tenant_id, client_id, client_secret, team_id, channel_id, req.limit)
    else: # chat
        teams_chat_id = req.teams_chat_id
        if not teams_chat_id:
            raise HTTPException(status_code=400, detail="Teams Chat ID is required for chat imports.")
        messages, err = teams_service.fetch_chat_messages(tenant_id, client_id, client_secret, teams_chat_id, req.limit)

    if err:
        raise HTTPException(status_code=400, detail=f"Failed to fetch Teams messages: {err}")

    if not messages:
        return {"status": "warning", "message": "No messages found in the specified Teams channel/chat."}

    # Format messages to prompt text transcript
    formatted_prompt = teams_service.format_teams_messages_to_prompt(messages)

    # Process document update with AI
    try:
        updated_doc, explanation = process_document_update(
            filepath=active_doc_path,
            user_input=formatted_prompt,
            chat_history=chat.get("messages", []),
            provider=req.provider
        )

        chat_manager.add_chat_message(
            req.chat_id,
            "user",
            f"💬 Imported {len(messages)} messages from Microsoft Teams"
        )
        chat_manager.add_chat_message(
            req.chat_id,
            "assistant",
            f"📝 **Document Updated with Teams Conversation!**\n\n{explanation}",
            doc_update_info=updated_doc
        )

        return {"status": "success", "imported_count": len(messages), "document": updated_doc, "explanation": explanation}
    except Exception as e:
        chat_manager.add_chat_message(
            req.chat_id,
            "assistant",
            f"❌ Error updating document from Teams import: {str(e)}"
        )
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/teams/desktop/windows")
def list_teams_desktop_windows_endpoint():
    """List open Microsoft Teams windows on Windows desktop."""
    windows = teams_desktop_service.list_teams_desktop_windows()
    return {"windows": windows}

@app.post("/api/teams/desktop/capture")
def capture_teams_desktop_endpoint(req: TeamsDesktopCaptureRequest):
    """Capture chat text from open Microsoft Teams desktop window and process into active document."""
    chat = chat_manager.get_chat(req.chat_id)
    if not chat:
        raise HTTPException(status_code=404, detail=f"Chat '{req.chat_id}' not found.")

    active_doc_path = chat.get("active_doc_path")
    if not active_doc_path or not os.path.exists(active_doc_path):
        raise HTTPException(status_code=400, detail="No active document set for this chat session.")

    success, transcript, lines = teams_desktop_service.capture_teams_chat_from_window(
        req.window_title, req.delay_seconds, req.auto_scroll_up, req.scroll_depth
    )
    if not success or not transcript.strip():
        raise HTTPException(status_code=400, detail=transcript)

    try:
        updated_doc, explanation = process_document_update_chunked(
            filepath=active_doc_path,
            user_input=f"Microsoft Teams Desktop Capture:\n\n{transcript}",
            chat_history=chat.get("messages", []),
            provider=req.provider
        )

        chat_manager.add_chat_message(
            req.chat_id,
            "user",
            "🖥️ Captured Teams Desktop Conversation"
        )
        chat_manager.add_chat_message(
            req.chat_id,
            "assistant",
            f"📝 **Document Updated with Teams Desktop Capture!**\n\n{explanation}",
            doc_update_info=updated_doc
        )

        return {"status": "success", "lines_count": len(lines), "document": updated_doc, "explanation": explanation}
    except Exception as e:
        chat_manager.add_chat_message(
            req.chat_id,
            "assistant",
            f"❌ Error updating document from Teams Desktop Capture: {str(e)}"
        )
        raise HTTPException(status_code=500, detail=str(e))


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
