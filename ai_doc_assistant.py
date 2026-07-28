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


SYSTEM_DOCUMENT_ANALYZER_PROMPT = """You are a Lead Software Architect and Senior Technical Author.
Your task is to perform DEEP TECHNICAL ANALYSIS on the user's input (which may contain raw chat transcripts, pull request details, or git diff patches) and author high-quality, production-grade technical documentation.

Current Document Outline & Sections:
{document_structure_json}

User Technical Input:
"{user_input}"

Instructions & Strict Rules:
1. **DEEP ARCHITECTURAL ANALYSIS & EXPLANATIONS**:
   - Do NOT just copy raw code or chat lines verbatim.
   - For any code changes, diffs, or infrastructure updates: Explain WHY the change was made, WHAT problem it solves, and HOW the technical mechanics work (e.g. proxy TLS decryption limits, GCS mirror fallbacks, cross-region latency, IAM grants).
   - Write clear explanatory prose and bullet points before presenting code snippets or tables.

2. **CONVERSATION & TRANSCRIPT SYNTHESIS**:
   - If the input contains raw team chat logs (Teams/Slack), synthesize all requests into a clean, professional Markdown Table: `| Requester | Request / Issue | Impacted Resource | Status | Resolution & Architectural Summary |`.

3. **COLOR-CODED GIT DIFF CODE BLOCKS**:
   - Format all code patches inside ```diff ``` code blocks with explicit + and - line markers.

4. **CRITICAL PROHIBITION (NEVER ECHO PROMPT INSTRUCTIONS)**:
   - NEVER output prompt instructions (such as "I want to create a guide...", "en el pull request que está...", "explícalos...") inside `updated_section_content`.
   - NEVER output conversational intro filler (such as "Here is the guide...", "Sure, here is...").
   - Output ONLY clean, professional technical document content.

5. Provide your decision strictly in JSON format as follows:

```json
{{
  "action": "merge_existing" OR "add_new",
  "target_heading": "Exact Title of Existing Heading" (if merge_existing, or closest preceding heading if add_new),
  "new_heading_title": "Title of New Section" (only if action is add_new, otherwise null),
  "heading_level": 2 (number 1 to 4 for heading level),
  "updated_section_content": "The full updated, deeply analyzed content for this section in Markdown format",
  "explanation": "Clear, concise 1-2 sentence explanation of what was modified or added in the document."
}}
```
Only return valid JSON inside a ```json ``` block.
"""


def clean_meta_instructions_from_content(content: str) -> str:
    """Strips any accidental prompt instructions or LLM intro filler from generated content."""
    if not content:
        return ""
    lines = content.splitlines()
    cleaned = []
    
    meta_patterns = [
        r'^\s*i\s+want\s+to\s+create',
        r'^\s*here\s+is\s+the\s+guide',
        r'^\s*here\s+is\s+the\s+document',
        r'^\s*sure,?\s+here',
        r'^\s*en\s+el\s+pull\s+request\s+que\s+est[aá]',
        r'^\s*estos\s+fueron\s+los\s+cambios',
        r'^\s*expl[ií]calos',
        r'^\s*prompt\s*:'
    ]
    
    for line in lines:
        s = line.strip()
        if any(re.search(pat, s, re.IGNORECASE) for pat in meta_patterns):
            continue
        cleaned.append(line)
        
    return "\n".join(cleaned).strip()


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


def clean_input_text(text: str) -> str:
    """Filter out UI system status badges, metadata cards, and assistant notifications from text."""
    if not text:
        return ""
    lines = text.splitlines()
    cleaned = []
    for line in lines:
        s = line.strip()
        if (
            s.startswith("📝") or 
            s.startswith("📂") or 
            s.startswith("✅") or 
            s.startswith("❌") or 
            "Document Updated!" in s or 
            "Updated file:" in s or 
            "section headings in document" in s or 
            "Structured technical content generated successfully" in s or
            "Loaded existing document" in s
        ):
            continue
        cleaned.append(line)
    return "\n".join(cleaned).strip()


def separate_instruction_and_payload(raw_input: str) -> Tuple[str, str]:
    """
    Separates user meta-instructions (e.g., "I want to create a guide...", "explícalos...")
    from technical data payload (chat transcripts, code diffs, logs).
    Returns (instruction_text, payload_text).
    """
    raw_input = clean_input_text(raw_input)
    lines = raw_input.splitlines()
    
    instruction_patterns = [
        r'^\s*i\s+want\s+to\s+create',
        r'^\s*create\s+a\s+guide',
        r'^\s*create\s+a\s+doc',
        r'^\s*expl[ií]calos',
        r'^\s*estos\s+fueron\s+los\s+cambios',
        r'^\s*en\s+el\s+pull\s+request',
        r'^\s*resumen\s+de',
        r'^\s*documentar',
        r'^\s*actualizar\s+el\s+documento',
        r'^\s*\d+\s*/\s*\d+\s+viewed',
        r'^\s*\d+\s+of\s+\d+\s+files\s+viewed',
        r'^\s*filter\s+files',
        r'^\s*file\s+tree'
    ]
    
    instructions = []
    payloads = []
    
    for line in lines:
        s = line.strip()
        if not s:
            continue
            
        is_meta = any(re.search(pat, s, re.IGNORECASE) for pat in instruction_patterns)
        if is_meta:
            instructions.append(s)
        else:
            payloads.append(line)
            
    instruction_text = "\n".join(instructions) if instructions else "Structure and document the technical information cleanly into markdown sections."
    payload_text = "\n".join(payloads)
    
    return instruction_text, payload_text


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
    Generic failsafe parser that dynamically converts ANY raw prompt input 
    (chat transcripts, logs, code diffs, or instructions) into clean Markdown sections.
    """
    instruction, payload = separate_instruction_and_payload(user_input)
    lines = payload.splitlines()
    sections = []
    
    chat_rows = []
    diff_lines = []
    general_lines = []
    
    in_diff = False
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
            
        # Omit web diff UI noise headers
        if (
            stripped.startswith("Filter files") or 
            stripped.startswith("File tree") or 
            stripped.startswith("Original file line number") or 
            stripped.startswith("Lines changed:") or
            stripped.startswith("=======================")
        ):
            continue
            
        if stripped.startswith('diff --git') or stripped.startswith('--- a/') or stripped.startswith('+++ b/'):
            in_diff = True
            
        if in_diff:
            diff_lines.append(line)
        else:
            # Match participant pattern (e.g. "User Name (Contractor)", "User Name (Admin)")
            chat_match = re.match(r'^([A-Z][A-Za-z0-9\s_\-\.]{2,35}\s+\((?:Contractor|Employee|User|Admin|Dev|QA)\))\s*[:\-\—]?\s*(.*)$', stripped, re.IGNORECASE)
            if chat_match:
                sender = chat_match.group(1).strip()
                message_text = chat_match.group(2).strip()
                if message_text:
                    chat_rows.append((sender, message_text))
                else:
                    chat_rows.append((sender, ""))
            else:
                if chat_rows and chat_rows[-1][1] == "":
                    prev_sender, _ = chat_rows[-1]
                    chat_rows[-1] = (prev_sender, stripped)
                else:
                    general_lines.append(stripped)

    section_counter = 1

    # 1. Chat Summary Table
    if chat_rows:
        table_rows = ["| Participant / Sender | Message / Request Details |", "| :--- | :--- |"]
        for sender, msg in chat_rows:
            if msg:
                clean_msg = msg.replace('|', '\\|')
                table_rows.append(f"| **{sender}** | {clean_msg} |")
                
        if len(table_rows) > 2:
            sections.append({
                "title": f"{section_counter}. Communication & Team Request Log",
                "level": 2,
                "content": "\n".join(table_rows)
            })
            section_counter += 1

    # 2. Code Diff Patch Section
    if diff_lines:
        diff_code_block = "```diff\n" + "\n".join(diff_lines[:250]) + "\n```"
        sections.append({
            "title": f"{section_counter}. Infrastructure Modifications & Diff Patch",
            "level": 2,
            "content": diff_code_block
        })
        section_counter += 1

    # 3. Technical Notes & Details
    if general_lines:
        sections.append({
            "title": f"{section_counter}. Technical Notes & Overview",
            "level": 2,
            "content": "\n\n".join(general_lines)
        })
        section_counter += 1

    if not sections:
        sections.append({
            "title": "Technical Documentation Overview",
            "level": 1,
            "content": payload if payload else user_input
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
    instruction, payload = separate_instruction_and_payload(user_input)
    doc_info = read_document(filepath)
    sections = doc_info["sections"]
    
    # Format payload for LLM prompt safely bounded
    payload_for_prompt = payload if len(payload) <= 3000 else (payload[:1800] + "\n\n...[payload truncated]...\n\n" + payload[-1200:])
    
    llm_input_json = {
        "user_goal_instruction": instruction,
        "technical_data_payload": payload_for_prompt
    }

    structure_summary = []
    for s in sections:
        structure_summary.append({
            "title": s["title"],
            "level": s["level"],
            "content": s["content"][:1000]
        })
        
    prompt = SYSTEM_DOCUMENT_ANALYZER_PROMPT.format(
        document_structure_json=json.dumps(structure_summary, indent=2),
        user_input=json.dumps(llm_input_json, indent=2)
    )
    
    messages = [
        {"role": "system", "content": "You are a professional documentation AI assistant."}
    ]

    # Include recent conversation history turns for context memory (up to 8 messages)
    if chat_history:
        for m in chat_history[-8:]:
            role = "user" if m.get("sender") == "user" else "assistant"
            txt = clean_input_text(m.get("text", ""))
            if txt and not m.get("is_onboarding"):
                messages.append({"role": role, "content": txt[:1000]})

    messages.append({"role": "user", "content": prompt})

    llm_output = generate_chat_response(
        messages=messages,
        provider=provider
    )
    
    analysis = extract_json_from_response(llm_output)
    
    if not analysis or not isinstance(analysis, dict) or "action" not in analysis:
        explanation = "Structured technical content generated successfully."
        fallback_sec_list = fallback_parse_prompt_to_sections(user_input)
        
        # If existing document contains raw unparsed dumps (>10 raw headings or raw diff), reset to clean structured sections
        if len(sections) > 10 or (len(sections) >= 1 and any("diff --git" in s["content"] or "--- a/" in s["content"] for s in sections)):
            sections = fallback_sec_list
        else:
            for f_sec in fallback_sec_list:
                sections.append(f_sec)
            
        updated_doc = save_updated_sections(filepath, doc_info["format"], sections)
        return updated_doc, explanation

    action = analysis.get("action", "add_new")
    target_heading = analysis.get("target_heading", "")
    new_heading_title = analysis.get("new_heading_title")
    heading_level = int(analysis.get("heading_level", 2))
    raw_updated_content = analysis.get("updated_section_content", user_input)
    updated_content = clean_meta_instructions_from_content(raw_updated_content)
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
