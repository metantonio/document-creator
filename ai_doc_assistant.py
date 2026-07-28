import json
import re
from typing import Dict, Any, List, Tuple
from llm_service import generate_chat_response
from doc_service import read_document, save_updated_sections, create_document

ONBOARDING_GREETING = (
    "Hello! I am your Technical Documentation Assistant. 📝\n\n"
    "To get started, please select an option:\n"
    "1️⃣ **Start a New Document** (formats: `.docx`, `.md`, or `.txt`)\n"
    "2️⃣ **Edit an Existing Document** (choose a file from your document library)\n\n"
    "How would you like to proceed today?"
)


SYSTEM_DOCUMENT_ANALYZER_PROMPT = """You are an expert Technical Writer and Document Architect.
Your task is to analyze technical content provided by the user and decide how to incorporate it into an existing technical document.

Current Document Outline & Sections:
{document_structure_json}

User Prompt / New Information:
"{user_input}"

Instructions:
1. Inspect all existing titles/headings in the document outline.
2. Determine whether the user's new information belongs inside one of the existing headings, OR if it requires creating a NEW section heading.
3. If it belongs in an existing section:
   - Carefully merge/integrate the new information with the existing text of that section. Preserve existing valuable content, correct formatting, and maintain smooth flow.
4. If it requires a new section:
   - Create a concise, professional title for the new section and generate its content.
5. Provide your decision strictly in JSON format as follows:

```json
{
  "action": "merge_existing" OR "add_new",
  "target_heading": "Exact Title of Existing Heading" (if merge_existing, or closest preceding heading if add_new),
  "new_heading_title": "Title of New Section" (only if action is add_new, otherwise null),
  "heading_level": 2 (number 1 to 4 for heading level),
  "updated_section_content": "The full updated content for this section in Markdown format",
  "explanation": "Clear, concise 1-2 sentence explanation of what was modified or added in the document."
}
```
Only return valid JSON inside a ```json ``` block.
"""

def extract_json_from_response(text: str) -> Dict[str, Any]:
    """Helper to parse JSON block from LLM output."""
    pattern = r'```(?:json)?\s*({[\s\S]*?})\s*```'
    match = re.search(pattern, text)
    if match:
        try:
            return json.loads(match.group(1))
        except Exception:
            pass
    # Try direct JSON parse
    try:
        return json.loads(text.strip())
    except Exception as e:
        print(f"Failed to parse LLM JSON response: {e}")
        return {}


def process_document_update(
    filepath: str,
    user_input: str,
    provider: str = None
) -> Tuple[Dict[str, Any], str]:
    """
    Analyzes document headings, uses AI to decide merge vs new section, 
    applies the update to disk, and returns (updated_doc_dict, explanation).
    """
    doc_info = read_document(filepath)
    sections = doc_info["sections"]
    
    # Prepare document structure JSON for prompt
    structure_summary = []
    for s in sections:
        structure_summary.append({
            "title": s["title"],
            "level": s["level"],
            "preview": s["content"][:200] + ("..." if len(s["content"]) > 200 else "")
        })
        
    prompt = SYSTEM_DOCUMENT_ANALYZER_PROMPT.format(
        document_structure_json=json.dumps(structure_summary, indent=2),
        user_input=user_input
    )
    
    llm_output = generate_chat_response(
        messages=[
            {"role": "system", "content": "You are a professional documentation AI assistant."},
            {"role": "user", "content": prompt}
        ],
        provider=provider
    )
    
    analysis = extract_json_from_response(llm_output)
    
    if not analysis or "action" not in analysis:
        # Fallback if LLM output isn't strict JSON: append as a new section or update overview
        explanation = f"Updated document based on your input:\n{llm_output}"
        if sections:
            sections[0]["content"] += f"\n\n{user_input}"
        else:
            sections.append({"title": "General Updates", "level": 1, "content": user_input})
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
                sec["content"] = updated_content
                found_target = True
            updated_sections.append(sec)
        if not found_target and updated_sections:
            # If match not found, update the last section
            updated_sections[-1]["content"] += f"\n\n{updated_content}"
    else: # add_new
        new_sec = {
            "title": new_heading_title or "New Section",
            "level": heading_level,
            "content": updated_content
        }
        
        # Insert after target_heading or at the end
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
