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
{user_input}

Instructions & Strict Rules:
1. **DEEP ARCHITECTURAL ANALYSIS & EXPLANATIONS**:
   - Do NOT just copy raw code or chat lines verbatim.
   - For any code changes, diffs, or infrastructure updates: Explain WHY the change was made, WHAT problem it solves, and HOW the technical mechanics work (e.g. proxy TLS decryption limits, GCS mirror fallbacks, cross-region latency, IAM grants).
   - Write clear explanatory prose and bullet points before presenting code snippets or tables.

2. **COMPREHENSIVE CONVERSATION ANALYSIS & COMPLETE DISCUSSION BREAKDOWN**:
   - Preserve 100% of all discussion topics, technical decisions, questions, answers, code references, and participant contributions from the Teams conversation.
   - Do NOT drop, condense, or omit any discussion details or user messages.
   - Structure the output into:
     a) **Full Executive Discussion & Technical Breakdown**: Grouped by topic/theme covering every single question, answer, code snippet, configuration detail, and decision made during the chat.
     b) **Participant Action & Task Status Table**:
        `| Participant / Member | Assigned Task / Topic | Impacted Resource | Status (Completed / In Progress / Pending) | Full Progress & Resolution Details |`
   - Ensure every single participant's contribution, question, and resolution is captured thoroughly without losing any detail!

3. **COLOR-CODED GIT DIFF & SCRIPT CODE BLOCKS**:
   - Format all code patches inside ```diff ``` code blocks with explicit + and - line markers.
   - If the user input contains a standalone script (Batch .bat, Bash .sh, Python .py, SQL, Terraform) or code snippet: You MUST preserve the full script or key code snippets inside fenced code blocks (```bat, ```bash, ```python, etc.), accompanied by a clear step-by-step architectural breakdown of what the script accomplishes.

4. **CRITICAL PROHIBITION (NEVER ECHO PROMPT INSTRUCTIONS)**:
   - NEVER output prompt instructions (such as "I want to create a guide...", "en el pull request que está...", "explícalos...") inside `updated_section_content`.
   - NEVER output conversational intro filler (such as "Here is the guide...", "Sure, here is...").
   - Output ONLY clean, professional technical document content.

5. **URL & EXTERNAL REFERENCE RETENTION**:
   - Whenever a URL (such as a GitHub Pull Request link, Jira ticket, or documentation link) is present in the input along with its content or diffs, ALWAYS preserve the clickable Markdown link `[Link Title](url)` in the section text accompanied by a clear technical explanation of what the URL and its contents represent.

6. Provide your decision strictly in JSON format as follows:

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


SYSTEM_REPO_WIKI_PROMPT = """You are a Principal Software Architect, DevSecOps Lead, and Senior Technical Writer.
Your mission is to perform a DEEP ARCHITECTURAL & CODEBASE ANALYSIS of the target repository (OpenWiki / DeepWiki style) and author comprehensive, production-grade technical wiki documentation in 100% English.

Repository Metadata & GitHub Statistics:
{github_metadata_json}

Directory Structure & File Tree:
```
{directory_tree}
```

Key Config, Manifests & Build Files:
{key_files_summary}

Environment Variables & Configuration Specs:
{env_configs_summary}

CI/CD & GitHub Actions Workflows:
{github_actions_summary}

File Relationship & Import Dependency Graph:
{import_graph_summary}

Sample Codebase Source Files:
{code_files_summary}

STRICT INSTRUCTIONS FOR WIKI GENERATION:
1. **INDEPENDENT OF README**: Do NOT rely solely on README content. Perform an independent architectural, structural, and code-level analysis of the entire codebase.
2. **METRICS & GOVERNANCE**: Include GitHub statistics (Stars, Forks, Open Issues, Open PRs, License, Language, Default Branch) in a clear Markdown summary table.
3. **FILE RELATIONSHIPS & MERMAID DIAGRAMS**: Explain how files interact and depend on each other. Include a visual Mermaid flowchart diagram (```mermaid ... ```) illustrating component architecture and data flow.
4. **ENVIRONMENT VARIABLES & CONFIGURATION**: Document all environment variables, config parameters, Docker setup, and settings files.
5. **CI/CD & GITHUB ACTIONS**: Explain all build pipelines, test runners, GitHub Actions workflows, and automation triggers.
6. **PRODUCE 100% ENGLISH OUTPUT**: All section titles, descriptions, diagrams, tables, and prose must be written strictly in English.

Return your response strictly as a JSON array of sections:

```json
[
  {{
    "title": "Repository Overview & Governance Metrics",
    "level": 1,
    "content": "Comprehensive overview with GitHub statistics table (Stars, Forks, Issues, License)..."
  }},
  {{
    "title": "System Architecture & High-Level Design",
    "level": 2,
    "content": "Architectural breakdown, design patterns, and structural paradigm..."
  }},
  {{
    "title": "Component Dependency Graph & File Relationships",
    "level": 2,
    "content": "Explanation of file imports and relationships accompanied by a Mermaid flowchart diagram..."
  }},
  {{
    "title": "Environment Variables & Configuration Parameters",
    "level": 2,
    "content": "Detailed breakdown of configuration options, env vars, and settings..."
  }},
  {{
    "title": "CI/CD & GitHub Actions Automation Specifications",
    "level": 2,
    "content": "Explanation of GitHub Actions workflows, build pipelines, and automated test triggers..."
  }},
  {{
    "title": "Technology Stack, Frameworks & Core Modules",
    "level": 2,
    "content": "Deep breakdown of main frameworks, libraries, source files, and endpoints..."
  }},
  {{
    "title": "Developer Onboarding, Setup & Deployment Guide",
    "level": 2,
    "content": "Step-by-step instructions for local execution, testing, and deployment..."
  }}
]
```
Only return valid JSON inside a ```json ``` block.
"""


SYSTEM_DOCUMENT_AUDITOR_PROMPT = """You are a Principal Technical Writer and Quality Assurance Editor.
Your job is to perform an AUTOMATED QUALITY AUDIT AND SELF-CORRECTION on a newly generated technical document.

Current Document Outline & Full Content:
{document_full_json}

Audit Checklist:
1. **HEADING HIERARCHY & FLOW**:
   - Ensure headings follow a logical hierarchy (Level 1 main title, Level 2 sections, Level 3/4 subsections).
   - Fix any orphan sub-headings (e.g. Level 3 without a parent Level 2).
   - Remove duplicate or identical section headings.
2. **CONTENT COHERENCE & SYNTAX**:
   - Clean up any unclosed code blocks or broken Markdown tables.
   - If team conversations exist, ensure they are formatted as a **Task Assignment & Progress Table by Person** (`| Participant / Member | Assigned Task / Request | Impacted Resource | Current Status | Progress & Resolution Details |` or Spanish equivalent) classifying tasks as **Completed** / **Completado**, **In Progress** / **En Progreso**, or **Pending** / **Pendiente**.
   - If a conversation section lacks identified participants/senders, verify it is presented as a **Brief Conversation Summary** with bullet points rather than a table with empty or 'Unknown' sender columns.
3. **STRICT CLEANLINESS**:
   - Remove any conversational meta-filler (e.g., "Here is the document...", "Sure, I can help...", "en el pull request que está...").
   - Eliminate redundant prompt instructions left in the content.

Instructions:
- If the document is ALREADY well-structured, coherent, and clean: return `"status": "approved"`.
- If corrections, heading adjustments, or cleanup are needed: return `"status": "refined"`, and provide the COMPLETE list of polished sections.

Return strictly JSON in the following format:

```json
{{
  "status": "approved" OR "refined",
  "audit_summary": "Concise 1-2 sentence description of audit findings or corrections applied.",
  "sections": [
    {{
      "title": "Exact Title of Section",
      "level": 2,
      "content": "Polished section content in Markdown format"
    }}
  ]
}}
```
Only return valid JSON inside a ```json ``` block.
"""


def audit_and_refine_document(filepath: str, provider: str = None, progress_callback = None) -> Tuple[Dict[str, Any], str]:
    """
    Automated Audit & Self-Correction Pass:
    1. Reads the newly generated/updated document.
    2. Runs programmatic quality checks (heading hierarchy normalization, duplicate removal, meta-filler cleaning).
    3. Calls LLM Auditor to review overall logical coherence, formatting, and cleanliness.
    4. Re-saves the document to disk if any refinements were made.
    """
    if progress_callback:
        progress_callback("auditing", "🔍 Pase de Auditoría: Normalizando jerarquía de títulos y limpieza...")

    doc_info = read_document(filepath)
    sections = doc_info.get("sections", [])
    if not sections:
        return doc_info, "Document is empty, audit skipped."

    # Step A: Programmatic Pre-Audit & Normalization
    programmatic_modified = False
    cleaned_sections = []
    seen_titles = set()

    for idx, sec in enumerate(sections):
        title = sec.get("title", "").strip()
        level = sec.get("level", 2)
        content = clean_meta_instructions_from_content(sec.get("content", ""))

        # Strip unneeded repetition in titles
        norm_title = re.sub(r'^\d+[\.\)]\s*', '', title).strip()
        
        # Prevent exact duplicate titles
        if norm_title.lower() in seen_titles and len(sections) > 1:
            title = f"{title} (Part {idx+1})"
            programmatic_modified = True
        else:
            seen_titles.add(norm_title.lower())

        # Normalize orphan heading levels
        if level > 4:
            level = 3
            programmatic_modified = True

        if content != sec.get("content", ""):
            programmatic_modified = True

        cleaned_sections.append({
            "title": title,
            "level": level,
            "content": content
        })

    if programmatic_modified:
        doc_info = save_updated_sections(filepath, doc_info["format"], cleaned_sections)
        sections = doc_info.get("sections", [])

    # Step B: AI LLM Auditor Pass
    try:
        doc_summary_for_audit = []
        for s in sections:
            doc_summary_for_audit.append({
                "title": s["title"],
                "level": s["level"],
                "content": s["content"][:2000]
            })

        prompt = SYSTEM_DOCUMENT_AUDITOR_PROMPT.format(
            document_full_json=json.dumps(doc_summary_for_audit, indent=2)
        )

        llm_output = generate_chat_response(
            messages=[
                {"role": "system", "content": "You are a Lead Quality Assurance Editor for technical documentation."},
                {"role": "user", "content": prompt}
            ],
            provider=provider
        )

        audit_result = extract_json_from_response(llm_output)

        if audit_result and isinstance(audit_result, dict):
            status = audit_result.get("status", "approved")
            audit_summary = audit_result.get("audit_summary", "Automated quality audit completed.")
            refined_sections = audit_result.get("sections")

            if status == "refined" and isinstance(refined_sections, list) and len(refined_sections) > 0:
                final_sections = []
                for r_sec in refined_sections:
                    if isinstance(r_sec, dict) and "title" in r_sec and "content" in r_sec:
                        final_sections.append({
                            "title": r_sec["title"],
                            "level": int(r_sec.get("level", 2)),
                            "content": clean_meta_instructions_from_content(r_sec["content"])
                        })
                if final_sections:
                    orig_len = sum(len(s.get("content", "")) for s in sections)
                    new_len = sum(len(s.get("content", "")) for s in final_sections)
                    if orig_len > 0 and new_len < orig_len * 0.8:
                        print(f"Auditor safety guard triggered: keeping original full text (orig_len={orig_len}, refined len={new_len}).")
                    else:
                        updated_doc = save_updated_sections(filepath, doc_info["format"], final_sections)
                        return updated_doc, f"🔍 **Automated Audit Pass**: Refined and quality-polished! ({audit_summary})"
    except Exception as e:
        print(f"Auditor pass note: {e}")

    return doc_info, "🔍 **Automated Audit Pass**: Document structure, headings, and formatting verified!"


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
        has_url = "http://" in s or "https://" in s
        if is_meta and not has_url:
            instructions.append(s)
        else:
            payloads.append(line)
            
    instruction_text = "\n".join(instructions) if instructions else "Structure and document the technical information cleanly into markdown sections."
    payload_text = "\n".join(payloads)
    
    return instruction_text, payload_text


def extract_json_from_response(text: str) -> Any:
    """
    Robust JSON parser that extracts JSON blocks and handles unescaped inner double quotes
    (common in Terraform/Bash code snippets like "chapp" = { application = "pe3" }),
    control characters, brackets, hashes, and mismatched quotes.
    """
    if not text:
        return None

    pattern = r'```(?:json)?\s*([\s\S]*?)\s*```'
    match = re.search(pattern, text)
    raw_str = match.group(1).strip() if match else text.strip()

    # Attempt 1: Standard json.loads with strict=False
    try:
        return json.loads(raw_str, strict=False)
    except Exception:
        pass

    # Attempt 2: Smart repair of unescaped quotes inside updated_section_content or string values
    try:
        def fix_field(m):
            prefix = m.group(1)
            inner = m.group(2)
            suffix = m.group(3)
            inner_fixed = inner.replace('\\"', '___ESCAPED_QUOTE___')
            inner_fixed = inner_fixed.replace('"', '\\"')
            inner_fixed = inner_fixed.replace('___ESCAPED_QUOTE___', '\\"')
            return f'{prefix}"{inner_fixed}"{suffix}'

        repaired_str = re.sub(
            r'("(?:updated_section_content|content|explanation|new_heading_title|target_heading)"\s*:\s*)"([\s\S]*?)"(\s*[\},])',
            fix_field,
            raw_str
        )
        return json.loads(repaired_str, strict=False)
    except Exception:
        pass

    # Attempt 3: Multi-key regex fallback (extract fields safely even if full JSON is malformed)
    try:
        if raw_str.startswith('[') and raw_str.endswith(']'):
            items = []
            item_blocks = re.findall(r'\{\s*"title"\s*:[\s\S]*?\}', raw_str)
            for blk in item_blocks:
                t_m = re.search(r'"title"\s*:\s*"([^"]*)"', blk)
                l_m = re.search(r'"level"\s*:\s*(\d+)', blk)
                c_m = re.search(r'"content"\s*:\s*"([\s\S]*)"', blk)
                if t_m:
                    items.append({
                        "title": t_m.group(1),
                        "level": int(l_m.group(1)) if l_m else 2,
                        "content": c_m.group(1).replace('\\"', '"').replace('\\n', '\n') if c_m else ""
                    })
            if items:
                return items

        content_val = None
        c_m = re.search(r'"updated_section_content"\s*:\s*"([\s\S]*?)"\s*,\s*"explanation"', raw_str)
        if not c_m:
            c_m = re.search(r'"updated_section_content"\s*:\s*"(.*)', raw_str, re.DOTALL)
            if c_m:
                tail = c_m.group(1)
                exp_idx = tail.rfind('"explanation"')
                if exp_idx != -1:
                    tail = tail[:exp_idx].rstrip().rstrip(',').rstrip('"')
                else:
                    tail = re.sub(r'["\s\}]+$', '', tail)
                content_val = tail.replace('\\"', '"').replace('\\n', '\n').strip()
        else:
            content_val = c_m.group(1).replace('\\"', '"').replace('\\n', '\n').strip()

        action_m = re.search(r'"action"\s*:\s*"([^"]+)"', raw_str)
        target_m = re.search(r'"target_heading"\s*:\s*"([^"]*)"', raw_str)
        title_m = re.search(r'"new_heading_title"\s*:\s*"([^"]*)"', raw_str)
        level_m = re.search(r'"heading_level"\s*:\s*(\d+)', raw_str)
        exp_m = re.search(r'"explanation"\s*:\s*"([^"]*)"', raw_str)

        if action_m or content_val:
            return {
                "action": action_m.group(1) if action_m else "add_new",
                "target_heading": target_m.group(1) if target_m else "",
                "new_heading_title": title_m.group(1) if title_m else None,
                "heading_level": int(level_m.group(1)) if level_m else 2,
                "updated_section_content": content_val or "",
                "explanation": exp_m.group(1) if exp_m else "Updated document."
            }
    except Exception as e:
        print(f"Failed to parse LLM JSON response: {e}")

    return None


def fallback_parse_prompt_to_sections(user_input: str) -> List[Dict[str, Any]]:
    """
    Generic failsafe parser that dynamically converts ANY raw prompt input 
    (chat transcripts, PR diffs, logs, scripts, or instructions) into clean Markdown sections.
    """
    instruction, payload = separate_instruction_and_payload(user_input)
    lines = payload.splitlines()
    sections = []
    
    chat_rows = []
    file_diff_map = []
    current_file = None
    current_file_lines = []
    general_lines = []
    pr_urls = []

    file_pat = re.compile(r'((?:modules|projects|[a-zA-Z0-9_\-\.\/]+)\/(?:[a-zA-Z0-9_\-\.]+\.)+(?:sh|tf|py|bat|cmd|json|yaml|yml|md|txt|c|cpp|h|java|go|js|ts))\b', re.IGNORECASE)
    teams_sender_patterns = [
        re.compile(r'^([A-Z][A-Za-z0-9\s_\-\.]{2,40}(?:\s+\([^\)]+\))?)\s+(?:\[?\d{1,2}:\d{2}(?:\:\d{2})?\s*(?:AM|PM)?\]?|\d{1,2}/\d{1,2}/\d{2,4})\s*[:\-\—]?\s*(.*)$', re.IGNORECASE),
        re.compile(r'^\[?\d{1,2}:\d{2}(?:\:\d{2})?\s*(?:AM|PM)?\]?\s*([A-Z][A-Za-z0-9\s_\-\.]{2,40}(?:\s+\([^\)]+\))?)\s*:\s*(.*)$', re.IGNORECASE),
        re.compile(r'^([A-Z][A-Za-z0-9\s_\-\.]{2,40}(?:\s+\((?:Contractor|Employee|User|Admin|Dev|QA|Guest|External|[^\)]+)\))?)\s*:\s*(.*)$', re.IGNORECASE)
    ]

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        if 'github.com' in stripped and '/pull/' in stripped:
            found_urls = re.findall(r'https?://github\.com/[^\s]+', stripped)
            pr_urls.extend(found_urls)
            
        if (
            stripped.startswith("Filter files") or 
            stripped.startswith("File tree") or 
            stripped.startswith("Original file line number") or 
            stripped.startswith("Lines changed:") or
            stripped.startswith("=======================") or
            stripped.startswith("📝 Document Updated!") or
            stripped.startswith("Updated file:") or
            stripped.startswith("1 section headings")
        ):
            continue

        file_match = file_pat.search(stripped)
        if file_match and len(stripped) < 120 and not stripped.startswith('#') and not stripped.startswith('+') and not stripped.startswith('-'):
            if current_file and current_file_lines:
                file_diff_map.append((current_file, current_file_lines))
            current_file = file_match.group(1).strip()
            current_file_lines = []
            continue

        if current_file:
            current_file_lines.append(line)
            continue

        chat_match = None
        for pat in teams_sender_patterns:
            m = pat.match(stripped)
            if m:
                chat_match = m
                break

        if chat_match:
            sender = chat_match.group(1).strip()
            message_text = chat_match.group(2).strip()
            chat_rows.append((sender, message_text))
        else:
            if chat_rows and chat_rows[-1][1] == "":
                prev_sender, _ = chat_rows[-1]
                chat_rows[-1] = (prev_sender, stripped)
            else:
                general_lines.append(line)

    if current_file and current_file_lines:
        file_diff_map.append((current_file, current_file_lines))

    section_counter = 1

    # 1. Chat Summary Table vs Anonymous Conversation Summary
    if chat_rows:
        has_identified_senders = any(
            sender and not sender.lower().startswith('unknown') and not sender.lower().startswith('anonymous')
            for sender, _ in chat_rows
        )
        if has_identified_senders:
            table_rows = ["| Participant / Team Member | Assigned Task / Request | Current Status | Progress & Resolution Details |", "| :--- | :--- | :--- | :--- |"]
            for sender, msg in chat_rows:
                if msg:
                    clean_msg = msg.replace('|', '\\|')
                    msg_lower = msg.lower()
                    
                    if any(kw in msg_lower for kw in ['done', 'completed', 'updated', 'merged', 'resuelto', 'listo', 'aplicado', 'creado', 'fixed']):
                        status = "**Completed**"
                    elif any(kw in msg_lower for kw in ['working', 'in progress', 'reviewing', 'pending', 'rebooting', 'probando', 'revisando', 'en proceso', 'verificando']):
                        status = "**In Progress**"
                    else:
                        status = "**Pending**"

                    table_rows.append(f"| **{sender}** | {clean_msg} | {status} | Request logged in conversation; requires technical follow-up. |")
                    
            if len(table_rows) > 2:
                sections.append({
                    "title": f"{section_counter}. Task Assignment & Status by Participant",
                    "level": 2,
                    "content": "\n".join(table_rows)
                })
                section_counter += 1
        else:
            summary_bullet_points = []
            for sender, msg in chat_rows:
                if msg:
                    summary_bullet_points.append(f"- {msg}")
            if summary_bullet_points:
                sections.append({
                    "title": f"{section_counter}. Conversation Summary Overview",
                    "level": 2,
                    "content": "The conversation covers the following key queries and main discussion points:\n\n" + "\n".join(summary_bullet_points)
                })
                section_counter += 1

    # 2. PR Reference & URLs
    if pr_urls:
        url_text = "The following Pull Request references were identified:\n\n"
        for url in set(pr_urls):
            url_text += f"- [{url}]({url})\n"
        sections.append({
            "title": f"{section_counter}. Pull Request References",
            "level": 2,
            "content": url_text
        })
        section_counter += 1

    # 3. File Diff Subsections
    if file_diff_map:
        for fname, f_lines in file_diff_map:
            descriptive_lines = []
            code_patch_lines = []
            for fl in f_lines:
                s_fl = fl.strip()
                if s_fl.startswith('+') or s_fl.startswith('-') or s_fl.startswith('@@') or s_fl.startswith('diff ') or s_fl.startswith('index '):
                    code_patch_lines.append(fl)
                elif re.match(r'^\s*(local\.|module\.|resource\.|"|\#|\{|\[|\})', s_fl):
                    code_patch_lines.append(fl)
                else:
                    descriptive_lines.append(fl)

            content_parts = []
            if descriptive_lines:
                content_parts.append("\n".join(descriptive_lines))
            if code_patch_lines:
                lang = "hcl" if fname.endswith('.tf') else ("bash" if fname.endswith('.sh') else "diff")
                content_parts.append(f"```{lang}\n" + "\n".join(code_patch_lines) + "\n```")

            sections.append({
                "title": f"{section_counter}. File Modification: {fname}",
                "level": 2,
                "content": "\n\n".join(content_parts)
            })
            section_counter += 1

    # 4. General Lines (Scripts or Notes)
    if general_lines:
        script_markers = [
            '@echo off', 'setlocal', 'set "', 'goto ', 'echo [', 'if exist ', 'title ', 
            'call "%gcloud%"', 'endlocal', 'exit /b', 'cls', '#!/bin/bash', 'def ', 
            'import ', 'resource "', 'select ', 'from ', 'where ', 'var ', 'const ', 'function '
        ]
        script_lines = []
        plain_notes = []
        for line in general_lines:
            s_lower = line.strip().lower()
            if any(marker in s_lower for marker in script_markers):
                script_lines.append(line)
            else:
                plain_notes.append(line)

        if script_lines:
            sections.append({
                "title": f"{section_counter}. Automation Script Implementation",
                "level": 2,
                "content": "```bat\n" + "\n".join(script_lines) + "\n```"
            })
            section_counter += 1

        if plain_notes:
            is_teams = any("teams" in line.lower() or "[" in line or ":" in line for line in plain_notes[:10])
            title_text = "Microsoft Teams Complete Conversation History & Discussion Details" if is_teams else "Technical Notes & Comprehensive Overview"
            
            bullet_lines = []
            for line in plain_notes:
                s = line.strip()
                if not s: continue
                if s.startswith("- ") or s.startswith("* ") or re.match(r'^\d+[\.\)]', s):
                    bullet_lines.append(s)
                else:
                    bullet_lines.append(f"- {s}")
                    
            sections.append({
                "title": f"{section_counter}. {title_text}",
                "level": 2,
                "content": "The following detailed conversation points and technical discussion items were extracted from Microsoft Teams:\n\n" + "\n".join(bullet_lines)
            })
            section_counter += 1

    if not sections:
        sections.append({
            "title": "Technical Documentation Overview",
            "level": 1,
            "content": payload if payload else user_input
        })
        
    return sections


def chunk_transcript_by_words(text: str, max_words: int = 900) -> List[str]:
    """
    Splits a raw chat transcript or long input string into logical chunks of ~800-1000 words.
    Always breaks cleanly at message boundaries (e.g. double line breaks, speaker headers).
    """
    if not text or len(text.split()) <= max_words:
        return [text] if text else []

    # Split into message blocks (separated by double newlines or speaker headers)
    blocks = re.split(r'\n\s*\n', text.strip())
    if len(blocks) <= 1:
        # Fallback to splitting by single line if no double newlines
        blocks = text.strip().splitlines()

    chunks = []
    current_chunk = []
    current_word_count = 0

    for block in blocks:
        block_words = len(block.split())
        if current_word_count + block_words > max_words and current_chunk:
            chunks.append("\n\n".join(current_chunk))
            current_chunk = [block]
            current_word_count = block_words
        else:
            current_chunk.append(block)
            current_word_count += block_words

    if current_chunk:
        chunks.append("\n\n".join(current_chunk))

    return chunks


def process_document_update_chunked(
    filepath: str,
    user_input: str,
    chat_history: Optional[List[Dict[str, Any]]] = None,
    provider: str = None,
    progress_callback = None
) -> Tuple[Dict[str, Any], str]:
    """
    Sequential Multi-Pass Chunk Processing Engine:
    Splits large chat transcripts/clipboard inputs into ~900-word chunks at message boundaries,
    and runs a sequential AI pass for each chunk to guarantee zero message loss in .docx.
    """
    word_count = len(user_input.split())
    if word_count <= 1000:
        return process_document_update(filepath, user_input, chat_history, provider, progress_callback)

    chunks = chunk_transcript_by_words(user_input, max_words=900)
    total_chunks = len(chunks)
    
    if total_chunks <= 1:
        return process_document_update(filepath, user_input, chat_history, provider, progress_callback)

    explanations = []
    updated_doc = None

    for idx, chunk in enumerate(chunks, 1):
        if progress_callback:
            progress_callback(
                "generating", 
                f"⚙️ Sequential Pass {idx}/{total_chunks}: Analyzing & appending conversation chunk (~{len(chunk.split())} words)..."
            )

        chunk_input = f"Teams Conversation Transcript Part {idx}/{total_chunks}:\n\n{chunk}"
        updated_doc, exp = process_document_update(
            filepath=filepath,
            user_input=chunk_input,
            chat_history=chat_history,
            provider=provider,
            progress_callback=None
        )
        explanations.append(f"Part {idx}/{total_chunks}: {exp}")

    full_explanation = f"Sequential Multi-Pass complete: Processed {total_chunks} conversation chunks (~{word_count} words total).\n\n" + "\n".join(explanations)
    return updated_doc, full_explanation


def process_document_update(
    filepath: str,
    user_input: str,
    chat_history: Optional[List[Dict[str, Any]]] = None,
    provider: str = None,
    progress_callback = None
) -> Tuple[Dict[str, Any], str]:
    """
    Analyzes document headings, uses AI to decide merge vs new section, 
    incorporates chat history context, applies the update to disk, and returns (updated_doc_dict, explanation).
    """
    if progress_callback:
        progress_callback("analyzing", "⚡ Paso 1/4: Analizando insumos y estructura del documento...")

    instruction, payload = separate_instruction_and_payload(user_input)
    doc_info = read_document(filepath)
    sections = doc_info["sections"]
    
    # If the user input is large (> 2500 chars) or contains multi-file diffs/logs,
    # process full payload into structured sections to prevent truncation.
    if len(payload) > 2500 or any(kw in payload for kw in ['modules/', 'projects/', 'diff --git', '+++ b/']):
        if progress_callback:
            progress_callback("generating", "⚙️ Paso 2/4: Sintetizando secciones y formateando parches de código...")

        fallback_sec_list = fallback_parse_prompt_to_sections(user_input)
        
        # If existing document is empty or has a single placeholder, replace with full structured sections
        if len(sections) <= 1 or (len(sections) >= 1 and any("diff --git" in s["content"] or "--- a/" in s["content"] for s in sections)):
            sections = fallback_sec_list
        else:
            for f_sec in fallback_sec_list:
                sections.append(f_sec)
            
        save_updated_sections(filepath, doc_info["format"], sections)

        if progress_callback:
            progress_callback("auditing", "🔍 Paso 3/4: Ejecutando auditoría de calidad y auto-corrección de formato...")

        audited_doc, audit_msg = audit_and_refine_document(filepath, provider=provider, progress_callback=progress_callback)

        if progress_callback:
            progress_callback("rendering", "📝 Paso 4/4: Renderizando y guardando el archivo Word .docx final...")

        explanation = f"Structured technical documentation generated with {len(fallback_sec_list)} sections.\n\n{audit_msg}"
        return audited_doc, explanation

    if progress_callback:
        progress_callback("generating", "⚙️ Paso 2/4: Sintetizando secciones y formateando parches de código con la IA...")

    payload_for_prompt = payload
    
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
            
        save_updated_sections(filepath, doc_info["format"], sections)
        audited_doc, audit_msg = audit_and_refine_document(filepath, provider=provider)
        explanation = f"{explanation}\n\n{audit_msg}"
        return audited_doc, explanation

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

    save_updated_sections(filepath, doc_info["format"], updated_sections)
    
    if progress_callback:
        progress_callback("auditing", "🔍 Paso 3/4: Ejecutando auditoría de calidad y auto-corrección de formato...")

    audited_doc, audit_msg = audit_and_refine_document(filepath, provider=provider, progress_callback=progress_callback)

    if progress_callback:
        progress_callback("rendering", "📝 Paso 4/4: Renderizando y guardando el archivo Word .docx final...")

    full_explanation = f"{explanation}\n\n{audit_msg}"
    return audited_doc, full_explanation


def build_mermaid_diagram_from_context(import_graph: Dict[str, List[str]], repo_name: str) -> str:
    """Generate a visual Mermaid flowchart diagram showing file-to-file relationships and imports."""
    if not import_graph:
        return ""
        
    lines = ["```mermaid", "graph TD", f"    subgraph {repo_name}_Architecture"]
    nodes_added = set()
    edges_added = set()

    for file_path, imports in import_graph.items():
        src_id = re.sub(r'[^a-zA-Z0-9_]', '_', file_path)
        src_label = os.path.basename(file_path)
        
        if src_id not in nodes_added:
            lines.append(f'        {src_id}["📄 {src_label}"]')
            nodes_added.add(src_id)

        for imp in imports:
            imp_clean = imp.split(' import ')[-1].split(' as ')[0].replace("from ", "").replace("require(", "").replace(")", "").strip("'\" ")
            if not imp_clean:
                continue
            target_id = re.sub(r'[^a-zA-Z0-9_]', '_', imp_clean)
            
            if target_id not in nodes_added:
                lines.append(f'        {target_id}["📦 {imp_clean}"]')
                nodes_added.add(target_id)

            edge = (src_id, target_id)
            if edge not in edges_added:
                lines.append(f'        {src_id} --> {target_id}')
                edges_added.add(edge)

    lines.append("    end")
    lines.append("```")
    return "\n".join(lines)


def generate_repo_documentation(
    repo_input: str,
    target_filepath: str,
    provider: str = None
) -> Tuple[Dict[str, Any], str]:
    """
    Multi-Pass Deep Repository Wiki Pipeline:
    Pass 1: High-Level Purpose, System Overview & Configuration Guide
    Pass 2: File-by-File Source Code Inventory & Functional Breakdown
    Pass 3: CI/CD & GitHub Actions Automation Specifications (if workflows exist)
    Pass 4: Governance Metrics (Stars, Forks, Issues, PRs, License) & Dependency Stack
    Guaranteed Sections: Directory Tree + Visual Mermaid Flowchart Diagram
    """
    # 1. Scan repo context
    context, temp_dir = analyze_repo_source(repo_input)
    
    try:
        # Prepare summaries for LLM prompt
        key_files_summary = ""
        for fname, content in context.get("key_files", {}).items():
            key_files_summary += f"\n--- File: {fname} ---\n{content[:2000]}\n"
            
        code_files_summary = ""
        for fname, content in context.get("sampled_code_files", {}).items():
            code_files_summary += f"\n--- File: {fname} ---\n{content[:1500]}\n"

        github_meta_summary = json.dumps(context.get("github_metadata", {}), indent=2)
        
        env_configs_summary = ""
        for fname, content in context.get("env_configs", {}).items():
            env_configs_summary += f"\n--- Config File: {fname} ---\n{content[:2000]}\n"
            
        actions_summary = ""
        for fname, content in context.get("github_actions", {}).items():
            actions_summary += f"\n--- Workflow File: .github/workflows/{fname} ---\n{content[:2000]}\n"

        import_graph_summary = ""
        for fname, imports in context.get("import_graph", {}).items():
            import_graph_summary += f"\nFile '{fname}' imports/depends on:\n" + "\n".join(f"  - {imp}" for imp in imports) + "\n"

        all_generated_sections = []

        # --- PASS 1: High-Level Purpose, Overview & Configuration Setup Guide ---
        p1_prompt = f"""You are a Principal Software Architect. Perform a deep analysis of repository '{context["repo_name"]}'.
Analyze its core purpose, technical domain, and configuration requirements.

Key Config & Readme Files:
{key_files_summary}

Environment Variables & Config Specs:
{env_configs_summary}

Generate 2 detailed sections in 100% English:
1. "Repository Purpose, System Overview & Core Capabilities" (Level 1)
2. "Configuration Files & Environment Variables Setup Guide" (Level 2) - Detail all config files (.env, config.py, settings.json, package.json), required environment variables, default values, and setup instructions.

Return JSON array:
[
  {{"title": "Repository Purpose, System Overview & Core Capabilities", "level": 1, "content": "..."}},
  {{"title": "Configuration Files & Environment Variables Setup Guide", "level": 2, "content": "..."}}
]
Only return valid JSON inside a ```json ``` block."""

        try:
            p1_out = generate_chat_response(
                messages=[
                    {"role": "system", "content": "You are a Senior Technical Writer performing repository architecture analysis."},
                    {"role": "user", "content": p1_prompt}
                ],
                provider=provider
            )
            p1_secs = extract_json_from_response(p1_out)
            if isinstance(p1_secs, list):
                all_generated_sections.extend(p1_secs)
        except Exception as e1:
            print(f"Pass 1 error: {e1}")

        # --- PASS 2: File-by-File Source Code Inventory & Functional Breakdown ---
        p2_prompt = f"""You are a Lead Software Author. Perform a comprehensive, file-by-file source code inventory of repository '{context["repo_name"]}'.

Directory Structure:
```
{context["directory_tree"]}
```

Sample Code Files:
{code_files_summary}

Import Dependency Graph:
{import_graph_summary}

Generate 1 detailed section in 100% English:
Title: "Comprehensive File Inventory & Source Code Analysis"
Level: 2
Content: Provide a thorough breakdown iterating over every significant file in the codebase. For each file, explain:
- File Path & Primary Role
- Key Functions, Classes, and Exports
- How it interacts with other files in the system.

Return JSON array:
[
  {{"title": "Comprehensive File Inventory & Source Code Analysis", "level": 2, "content": "..."}}
]
Only return valid JSON inside a ```json ``` block."""

        try:
            p2_out = generate_chat_response(
                messages=[
                    {"role": "system", "content": "You are a Lead Software Engineer analyzing source code files."},
                    {"role": "user", "content": p2_prompt}
                ],
                provider=provider
            )
            p2_secs = extract_json_from_response(p2_out)
            if isinstance(p2_secs, list):
                all_generated_sections.extend(p2_secs)
        except Exception as e2:
            print(f"Pass 2 error: {e2}")

        # --- PASS 3: CI/CD & GitHub Actions Pipeline Specifications (if workflows exist) ---
        if context.get("github_actions"):
            p3_prompt = f"""You are a DevSecOps Lead. Analyze the CI/CD GitHub Actions workflows for repository '{context["repo_name"]}'.

GitHub Actions Workflows:
{actions_summary}

Generate 1 detailed section in 100% English:
Title: "CI/CD & GitHub Actions Automation Specifications"
Level: 2
Content: Iterate over each workflow file in .github/workflows/, explaining trigger events (push, PR, schedule), job steps, automated test runners, build targets, and deployment actions.

Return JSON array:
[
  {{"title": "CI/CD & GitHub Actions Automation Specifications", "level": 2, "content": "..."}}
]
Only return valid JSON inside a ```json ``` block."""

            try:
                p3_out = generate_chat_response(
                    messages=[
                        {"role": "system", "content": "You are a DevSecOps Engineer analyzing GitHub Actions."},
                        {"role": "user", "content": p3_prompt}
                    ],
                    provider=provider
                )
                p3_secs = extract_json_from_response(p3_out)
                if isinstance(p3_secs, list):
                    all_generated_sections.extend(p3_secs)
            except Exception as e3:
                print(f"Pass 3 error: {e3}")

        # --- PASS 4: Governance Metrics, Dependency Stack & Third-Party Services ---
        p4_prompt = f"""You are a Governance Specialist and Software Architect. Analyze GitHub metadata and external dependencies for repository '{context["repo_name"]}'.

GitHub Statistics:
{github_meta_summary}

Key Files & Manifests (package.json / requirements.txt / Cargo.toml / etc.):
{key_files_summary}

Generate 1 detailed section in 100% English:
Title: "Governance Metrics, Dependency Stack & Third-Party Integrations"
Level: 2
Content:
1. Include a clear GitHub Metrics Summary Table: | Metric | Value | (Stars, Forks, Open Issues, Open PRs, License, Primary Language, Default Branch).
2. Detail all core frameworks, libraries, runtime requirements, and third-party API integrations used by the project.

Return JSON array:
[
  {{"title": "Governance Metrics, Dependency Stack & Third-Party Integrations", "level": 2, "content": "..."}}
]
Only return valid JSON inside a ```json ``` block."""

        try:
            p4_out = generate_chat_response(
                messages=[
                    {"role": "system", "content": "You are a Software Architect summarizing governance metrics and dependencies."},
                    {"role": "user", "content": p4_prompt}
                ],
                provider=provider
            )
            p4_secs = extract_json_from_response(p4_out)
            if isinstance(p4_secs, list):
                all_generated_sections.extend(p4_secs)
        except Exception as e4:
            print(f"Pass 4 error: {e4}")

        # --- PASS 5: Dedicated Architectural Mermaid Diagram Loop ---
        p5_prompt = f"""You are a Principal Systems Architect. Create a dedicated visual Mermaid flowchart diagram (```mermaid ... ```) mapping out the complete file relationships and component architecture for repository '{context["repo_name"]}'.

Directory Structure:
```
{context["directory_tree"]}
```

Import Dependency Graph:
{import_graph_summary}

Code Files & Scripts Overview:
{code_files_summary}

Generate 1 detailed section in 100% English:
Title: "Component Dependency Graph & File Relationships"
Level: 2
Content: Provide a clear explanatory paragraph followed by a valid visual Mermaid flowchart diagram (```mermaid ... ``` with `graph TD`) illustrating how frontend files, backend engines, CLI scripts, tools, and data files (JSON, CSV, API endpoints) interact and connect.

Return JSON array:
[
  {{"title": "Component Dependency Graph & File Relationships", "level": 2, "content": "..."}}
]
Only return valid JSON inside a ```json ``` block."""

        try:
            p5_out = generate_chat_response(
                messages=[
                    {"role": "system", "content": "You are a Principal Architect generating Mermaid component diagrams."},
                    {"role": "user", "content": p5_prompt}
                ],
                provider=provider
            )
            p5_secs = extract_json_from_response(p5_out)
            if isinstance(p5_secs, list) and len(p5_secs) > 0 and "mermaid" in p5_secs[0].get("content", "").lower():
                all_generated_sections.insert(2, p5_secs[0])
            else:
                mermaid_diag = build_mermaid_diagram_from_context(context.get("import_graph", {}), context["repo_name"])
                if mermaid_diag:
                    all_generated_sections.insert(2, {
                        "title": "Component Dependency Graph & File Relationships",
                        "level": 2,
                        "content": f"The following visual Mermaid flowchart diagram maps out how source files interact and depend on each other:\n\n{mermaid_diag}"
                    })
        except Exception as e5:
            print(f"Pass 5 error: {e5}")
            mermaid_diag = build_mermaid_diagram_from_context(context.get("import_graph", {}), context["repo_name"])
            if mermaid_diag:
                all_generated_sections.insert(2, {
                    "title": "Component Dependency Graph & File Relationships",
                    "level": 2,
                    "content": f"The following visual Mermaid flowchart diagram maps out how source files interact and depend on each other:\n\n{mermaid_diag}"
                })

        # --- GUARANTEED STRUCTURAL SECTIONS ---
        # 1. Directory Tree
        if context.get("directory_tree") and not any("directory" in s.get("title", "").lower() for s in all_generated_sections):
            all_generated_sections.insert(1, {
                "title": "Repository Directory Structure & File Map",
                "level": 2,
                "content": f"The repository filesystem hierarchy and directory tree structure is organized as follows:\n\n```\n{context['directory_tree']}\n```"
            })

        # Save to target document
        existing_doc = read_document(target_filepath)
        existing_sections = existing_doc["sections"]

        if len(all_generated_sections) > 0:
            final_sections = list(existing_sections)
            for gen_sec in all_generated_sections:
                g_title = gen_sec.get("title", "Repository Wiki Section")
                g_level = gen_sec.get("level", 2)
                g_content = gen_sec.get("content", "")

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
            
            save_updated_sections(target_filepath, existing_doc["format"], final_sections)
            explanation = f"Generated Multi-Pass Technical Wiki for **{context['repo_name']}** with {len(all_generated_sections)} sections into **{existing_doc['filename']}**."
        else:
            explanation = f"Analyzed repository **{context['repo_name']}**."

        # Automated Audit & Self-Correction Pass
        audited_doc, audit_msg = audit_and_refine_document(target_filepath, provider=provider)
        full_explanation = f"{explanation}\n\n{audit_msg}"
        return audited_doc, full_explanation
    finally:
        if temp_dir and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir, ignore_errors=True)
