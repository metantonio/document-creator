# DocCraft AI - Technical Documentation Creator 📝

[![Repository](https://img.shields.io/badge/GitHub-metantonio%2Fdocument--creator-blue?logo=github)](https://github.com/metantonio/document-creator)

**DocCraft AI** is an intelligent, English-interface Python application for creating and editing technical documentation (`.docx`, `.md`, `.txt`) using either **Local LLMs** (llama.cpp, Ollama, LM Studio) or **Cloud LLMs** (OpenAI, OpenRouter, Groq, etc.).

Repository: [https://github.com/metantonio/document-creator](https://github.com/metantonio/document-creator)

---

> [!IMPORTANT]  
> **Recommended Best Practice:** Always create a virtual environment (`venv`) before installing dependencies. This keeps your Python packages isolated specifically to this project and avoids conflicts with system-wide packages.

---

## 🚀 Quick Start Guide

### 1. Clone or Open the Repository
```bash
git clone https://github.com/metantonio/document-creator.git
cd document-creator
```

### 2. Create and Activate a Virtual Environment

**On Windows (PowerShell / Command Prompt):**
```powershell
# 1. Create virtual environment
python -m venv venv

# 2. Activate virtual environment (PowerShell)
.\venv\Scripts\Activate.ps1

# Note: If PowerShell blocks script execution (ExecutionPolicy error), run this first:
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope Process
```

**On macOS / Linux:**
```bash
# 1. Create virtual environment
python -m venv venv

# 2. Activate virtual environment (bash/zsh)
source venv/bin/activate
```

### 3. Install Dependencies
With your virtual environment activated, install the required packages:
```bash
pip install -r requirements.txt
```

### 4. Launch the Application
Start the application server:
```bash
python main.py
```
Open your web browser and navigate to:
👉 **`http://127.0.0.1:8000`**

---

## ✨ Key Features

- **⚡ Repository Documentation Wiki Generator (OpenWiki / DeepWiki Style)**:
  - Input any local folder path (e.g. `C:\Repositorios\my-project`) or public GitHub repository URL (`https://github.com/owner/repo`).
  - Automatically parses directory trees, configuration files (`README`, `package.json`, `requirements.txt`, etc.), and main source modules.
  - Generates structured technical documentation (Architecture, Component Map, Tech Stack, Dependencies, API Breakdown, Setup Guide).
  - Seamlessly incorporates the generated wiki into a **new document** or merges it into an **existing document** (`.docx`, `.md`, `.txt`) chosen by the user.

- **Dual LLM Connectivity (Local & Cloud)**:
  - **Local Models**: Preconfigured support for **llama.cpp** (`http://localhost:8080/v1`), **Ollama** (`http://localhost:11434/v1`), and **LM Studio** (`http://localhost:1234/v1`).
  - **Cloud Models**: Supports **OpenAI** (`gpt-4o`), **OpenRouter**, **Groq**, etc.
  - **1-Click AI Switch**: Instantly toggle between Local and Cloud models from the sidebar.

- **Smart Title Recognition & Section Merging**:
  - The AI reads existing titles/headings in your `.docx`, `.md`, or `.txt` document.
  - Automatically determines whether new technical information should be merged into an **existing title section** or appended as a **new section title**.

- **Multi-Format Support**:
  - Create and edit **Markdown (`.md`)**, **Microsoft Word (`.docx`)**, and **Plain Text (`.txt`)** files.

- **Interactive Onboarding in Chat**:
  - Each conversation begins with an onboarding prompt asking whether you want to **Start a New Document** or **Edit an Existing Document**.

- **Dynamic `config.py` UI Editor**:
  - Modify parameters (Base URLs, Model Names, API Keys, Temperatures, Max Tokens, and Document Paths) directly inside the UI Settings modal without manually editing code.

- **Integrated Document Viewer**:
  - Live split-screen preview of Markdown rendering and document heading trees.

---

## 🛠️ Project Structure

```
documentation-creator/
├── config.py             # Central configuration (Local & Cloud LLM settings, paths)
├── config.json           # Saved UI configuration state
├── doc_service.py        # Multi-format document parser & section builder (.docx, .md, .txt)
├── llm_service.py        # Unified OpenAI-compatible API client layer
├── ai_doc_assistant.py   # AI prompts for heading recognition & section merging
├── chat_manager.py       # Chat session storage and onboarding state
├── main.py               # FastAPI application backend
├── docs_storage/         # Default directory for generated documents
├── chats_storage/        # Chat session data storage
├── requirements.txt      # Python dependencies
├── LICENSE               # MIT License
└── static/               # Frontend UI assets
    ├── index.html        # Web layout & modal dialogs
    ├── style.css         # Modern dark-themed styling
    └── app.js            # Frontend JavaScript application logic
```

---

## 📄 License

This project is licensed under the **MIT License** - Copyright (c) 2026 **Antonio Martínez**. See the [LICENSE](LICENSE) file for details.

Repository: [https://github.com/metantonio/document-creator](https://github.com/metantonio/document-creator)

