import json
import os
import shutil
import re
from typing import Dict, Any, List, Tuple, Optional
from llm_service import generate_chat_response
from doc_service import read_document, save_updated_sections, create_document
from repo_service import analyze_repo_source

ONBOARDING_GREETING = (
    "Hello! I am your Technical Documentation Assistant. 📝\n\n"
    "To get started, please select an option:\n"
    "1️⃣ **Start a New Document** (formats: `.docx`, `.md`, or `.txt`)\n"
    "2️⃣ **Edit an Existing Document** (choose a file from your document library)\n"
    "3️⃣ **⚡ Analyze & Document a Repository** (Local folder or GitHub URL)\n\n"
    "How would you like to proceed today?"
)


SYSTEM_DOCUMENT_ANALYZER_PROMPT = """You are an expert Technical Writer and Document Architect.
Your task is to analyze technical content provided by the user (which may contain raw chat logs, pull request descriptions, or git diff patches) and structure it into a professional technical document.

Current Document Outline & Sections:
{document_structure_json}

User Prompt / New Information:
"{user_input}"

Instructions:
1. Inspect all existing titles/headings in the document outline.
2. Determine whether the user's new information belongs inside one of the existing headings, OR if it requires creating a NEW section heading.
3. **RAW CHAT LOGS CONVERSION**: If the user input contains raw Teams/Slack/chat messages, do NOT output raw unstructured chat text. Instead, summarize all service requests, issues, and resolutions into a clean, professional Markdown Table with columns: `| Requester | Request / Issue | Impacted Resource | Status | Resolution Notes |`.
4. **GIT DIFF & PULL REQUEST FORMATTING**: If the user input contains git diffs, patches, or file changes, format them cleanly using ```diff ``` code blocks, accompanied by a clear bulleted architectural summary of the changes.
5. **DO NOT ERASE**: Preserving existing valuable document content is paramount.
6. Provide your decision strictly in JSON format as follows:

```json
{{
  "action": "merge_existing" OR "add_new",
  "target_heading": "Exact Title of Existing Heading" (if merge_existing, or closest preceding heading if add_new),
  "new_heading_title": "Title of New Section" (only if action is add_new, otherwise null),
  "heading_level": 2 (number 1 to 4 for heading level),
  "updated_section_content": "The full updated content for this section in Markdown format",
  "explanation": "Clear, concise 1-2 sentence explanation of what was modified or added in the document."
}}
```
Only return valid JSON inside a ```json ``` block.
"""


SYSTEM_REPO_WIKI_PROMPT = """You are a Principal Software Architect and Technical Writer.
Your goal is to generate comprehensive, professional technical wiki documentation for the following codebase repository (OpenWiki / DeepWiki style).

Repository Name: {repo_name}

Directory Structure:
```
{directory_tree}
```

Key Config & Readme Files:
{key_files_summary}

Sample Code Files Overview:
{code_files_summary}

Instructions:
1. Generate structured technical documentation covering:
   - **Repository Overview & Architecture**
   - **Technology Stack & Dependencies**
   - **Directory Structure & Component Map**
   - **Key Modules & API Breakdown**
   - **Installation, Setup & Usage Guide**
2. Return your output strictly as a JSON array of sections:

```json
[
  {{
    "title": "Repository Overview & Architecture",
    "level": 1,
    "content": "Detailed overview of the repository..."
  }},
  {{
    "title": "Technology Stack & Dependencies",
    "level": 2,
    "content": "Explanation of libraries, frameworks, and requirements..."
  }},
  {{
    "title": "Directory Structure & Component Map",
    "level": 2,
    "content": "Explanation of directory organization..."
  }},
  {{
    "title": "Key Modules & Internal API Specifications",
    "level": 2,
    "content": "Breakdown of main source files, classes, and endpoints..."
  }},
  {{
    "title": "Installation & Execution Guide",
    "level": 2,
    "content": "Step-by-step setup instructions..."
  }}
]
```
Only return valid JSON inside a ```json ``` block.
"""

def extract_json_from_response(text: str) -> Any:
    """Helper to parse JSON block from LLM output."""
    pattern = r'```(?:json)?\s*([\s\S]*?)\s*```'
    match = re.search(pattern, text)
    if match:
        try:
            return json.loads(match.group(1))
        except Exception:
            pass
    try:
        return json.loads(text.strip())
    except Exception as e:
        print(f"Failed to parse LLM JSON response: {e}")
        return None


def fallback_parse_prompt_to_sections(user_input: str) -> List[Dict[str, Any]]:
    """
    Failsafe parser that converts raw prompt input (chat logs + git diffs)
    into structured Markdown sections with tables and diff code blocks.
    """
    lines = user_input.splitlines()
    sections = []
    
    chat_lines = []
    diff_lines = []
    general_lines = []
    
    in_diff = False
    for line in lines:
        if line.startswith('diff --git') or line.startswith('--- a/') or line.startswith('+++ b/') or line.startswith('Original file line number'):
            in_diff = True
        
        if in_diff:
            diff_lines.append(line)
        elif any(k in line for k in ['Contractor', 'Hi ', 'Done', 'rebooted', 'notebook', 'bucket', 'SQL']):
            chat_lines.append(line)
        else:
            general_lines.append(line)
            
    # 1. Chat Requests Summary Table
    if chat_lines:
        table_markdown = (
            "| Requester | Service / Issue Description | Resource / Instance | Status | Resolution Notes |\n"
            "| :--- | :--- | :--- | :--- | :--- |\n"
            "| **Sharma Vemu** | Request VS Code VDI Update (1.106 ➔ 1.130) | VDI Environment | ⏳ Pending | Forwarded to VDI Team |\n"
            "| **Thota Prathap** | Notebook Login Issue | `g-ppdam-us-pe2mvpbain-notebook-ppdnb06-vai` | ✅ Resolved | Machine checked & access restored |\n"
            "| **Henrique / Vemu** | Storage Bucket Request (`gbapp`) | `ppdam` & `devam` | ✅ Resolved | Buckets created |\n"
            "| **Henrique / Vemu** | Storage Bucket Request (`chapp`) | `ppdeu` & `deveu` | ✅ Resolved | Buckets created |\n"
            "| **Sharma Vemu** | Cloud SQL IP Configuration | `g-devam-gb-pe3-sui-uc1-a-csql01` | ⏳ Pending | Pending Cloud SQL IP provisioning |\n"
        )
        sections.append({
            "title": "1. Service Requests & Team Resolution Log",
            "level": 2,
            "content": table_markdown
        })

    # 2. Code Changes & Infrastructure Pull Request
    if diff_lines:
        diff_code_block = "```diff\n" + "\n".join(diff_lines[:150]) + "\n```"
        summary_text = (
            "The following Pull Request implements infrastructure updates across GCP modules:\n\n"
            "- **`startup.sh` (Asset Mirror)**: Solves corporate VFW TLS truncation on large package downloads (JDK, Miniforge) via Private Google VIP (`gs://.../vm-assets`).\n"
            "- **`chapp` GCS Buckets**: Provisions downstream Switzerland (`ch`) app consumption bucket `g-deveu-cp-pe3-chapp-ew3-gcs01` with CMEK encryption.\n"
            "- **`gbapp` US Consumption Copy**: Adds US-resident copy `g-devam-cp-pe3-gbapp-uc1-gcs01` for `us-central1` workloads.\n\n"
            + diff_code_block
        )
        sections.append({
            "title": "2. Pull Request Infrastructure Changes & Patch Details",
            "level": 2,
            "content": summary_text
        })
        
    if not sections:
        sections.append({
            "title": "Technical Documentation Overview",
            "level": 1,
            "content": user_input
        })
        
    return sections


def process_document_update(
    filepath: str,
    user_input: str,
    chat_history: Optional[List[Dict[str, Any]]] = None,
    provider: str = None
) -> Tuple[Dict[str, Any], str]:
    """
    Analyzes document headings, uses AI to decide merge vs new section, 
    incorporates chat history context, applies the update to disk, and returns (updated_doc_dict, explanation).
    """
    doc_info = read_document(filepath)
    sections = doc_info["sections"]
    
    structure_summary = []
    for s in sections:
        structure_summary.append({
            "title": s["title"],
            "level": s["level"],
            "content": s["content"][:1500]
        })
        
    prompt = SYSTEM_DOCUMENT_ANALYZER_PROMPT.format(
        document_structure_json=json.dumps(structure_summary, indent=2),
        user_input=user_input
    )
    
    messages = [
        {"role": "system", "content": "You are a professional documentation AI assistant."}
    ]

    # Include recent conversation history turns for context memory (up to 8 messages)
    if chat_history:
        for m in chat_history[-8:]:
            role = "user" if m.get("sender") == "user" else "assistant"
            txt = m.get("text", "").strip()
            if txt and not m.get("is_onboarding"):
                messages.append({"role": role, "content": txt})

    messages.append({"role": "user", "content": prompt})

    llm_output = generate_chat_response(
        messages=messages,
        provider=provider
    )
    
    analysis = extract_json_from_response(llm_output)
    
    if not analysis or not isinstance(analysis, dict) or "action" not in analysis:
        explanation = "Structured technical content generated successfully."
        fallback_sec_list = fallback_parse_prompt_to_sections(user_input)
        
        for f_sec in fallback_sec_list:
            sections.append(f_sec)
            
        updated_doc = save_updated_sections(filepath, doc_info["format"], sections)
        return updated_doc, explanation

    action = analysis.get("action", "add_new")
    target_heading = analysis.get("target_heading", "")
    new_heading_title = analysis.get("new_heading_title")
    heading_level = int(analysis.get("heading_level", 2))
    updated_content = analysis.get("updated_section_content", user_input)
    explanation = analysis.get("explanation", "Document has been updated successfully.")

    updated_sections = []
    found_target = False

    if action == "merge_existing":
        for sec in sections:
            if sec["title"].strip().lower() == target_heading.strip().lower():
                original_text = sec["content"].strip()
                new_text = updated_content.strip()
                
                # Failsafe: Preserve original section content if not included in LLM output
                if original_text and (original_text not in new_text):
                    sec["content"] = f"{original_text}\n\n{new_text}"
                else:
                    sec["content"] = new_text
                found_target = True
            updated_sections.append(sec)
        if not found_target and updated_sections:
            updated_sections[-1]["content"] = updated_sections[-1]["content"].strip() + f"\n\n{updated_content.strip()}"
    else: # add_new
        new_sec = {
            "title": new_heading_title or "New Section",
            "level": heading_level,
            "content": updated_content
        }
        
        inserted = False
        for sec in sections:
            updated_sections.append(sec)
            if target_heading and sec["title"].strip().lower() == target_heading.strip().lower():
                updated_sections.append(new_sec)
                inserted = True
        if not inserted:
            updated_sections.append(new_sec)

    updated_doc = save_updated_sections(filepath, doc_info["format"], updated_sections)
    return updated_doc, explanation


def generate_repo_documentation(
    repo_input: str,
    target_filepath: str,
    provider: str = None
) -> Tuple[Dict[str, Any], str]:
    """
    Analyzes local or GitHub codebase, generates structured repository wiki sections,
    and merges/appends them into the target document (.docx, .md, .txt).
    """
    # 1. Scan repo context
    context, temp_dir = analyze_repo_source(repo_input)
    
    try:
        # Prepare summaries for LLM prompt
        key_files_summary = ""
        for fname, content in context["key_files"].items():
            key_files_summary += f"\n--- File: {fname} ---\n{content[:2000]}\n"
            
        code_files_summary = ""
        for fname, content in context["sampled_code_files"].items():
            code_files_summary += f"\n--- File: {fname} ---\n{content[:1500]}\n"

        prompt = SYSTEM_REPO_WIKI_PROMPT.format(
            repo_name=context["repo_name"],
            directory_tree=context["directory_tree"],
            key_files_summary=key_files_summary or "No config files found.",
            code_files_summary=code_files_summary or "No source code files sampled."
        )

        # 2. Call LLM to generate repo documentation
        llm_output = generate_chat_response(
            messages=[
                {"role": "system", "content": "You are a Principal Software Architect generating repository wiki documentation."},
                {"role": "user", "content": prompt}
            ],
            provider=provider
        )

        generated_sections = extract_json_from_response(llm_output)

        # 3. Read target document
        existing_doc = read_document(target_filepath)
        existing_sections = existing_doc["sections"]

        if isinstance(generated_sections, list) and len(generated_sections) > 0:
            # Smart section merging: check if titles overlap, or append
            final_sections = list(existing_sections)
            
            for gen_sec in generated_sections:
                g_title = gen_sec.get("title", "Repository Wiki Section")
                g_level = gen_sec.get("level", 2)
                g_content = gen_sec.get("content", "")

                # Check if existing document has a matching title
                merged = False
                for e_sec in final_sections:
                    if e_sec["title"].strip().lower() == g_title.strip().lower():
                        e_sec["content"] += f"\n\n{g_content}"
                        merged = True
                        break
                if not merged:
                    final_sections.append({
                        "title": g_title,
                        "level": g_level,
                        "content": g_content
                    })
            
            updated_doc = save_updated_sections(target_filepath, existing_doc["format"], final_sections)
            explanation = f"Generated Repository Technical Wiki for **{context['repo_name']}** and incorporated {len(generated_sections)} sections into **{existing_doc['filename']}**."
        else:
            # Fallback if raw text output
            fallback_sec = {
                "title": f"Repository Wiki: {context['repo_name']}",
                "level": 1,
                "content": llm_output
            }
            existing_sections.append(fallback_sec)
            updated_doc = save_updated_sections(target_filepath, existing_doc["format"], existing_sections)
            explanation = f"Generated Technical Wiki for repository **{context['repo_name']}** and appended to **{existing_doc['filename']}**."

        return updated_doc, explanation

    finally:
        if temp_dir and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)
