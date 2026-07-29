import sys
import os
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, '.')

import doc_service

def inspect_deep_wiki():
    target_path = os.path.join("docs_storage", "Deep-Quality-Driven-Wiki.docx")
    if not os.path.exists(target_path):
        print(f"File {target_path} not found!")
        return

    doc_info = doc_service.read_document(target_path)
    print("=== INSPECTING Deep-Quality-Driven-Wiki.docx ===")
    print("Filename:", doc_info["filename"])
    print("Full text character length:", len(doc_info["full_text"]))
    print("Total Sections:", len(doc_info["sections"]))
    
    for idx, sec in enumerate(doc_info["sections"]):
        print(f"\n--- Section {idx+1}: [{sec['level']}] {sec['title']} ({len(sec['content'])} chars) ---")
        print(sec['content'][:400].replace('\n', ' '))

if __name__ == "__main__":
    inspect_deep_wiki()
