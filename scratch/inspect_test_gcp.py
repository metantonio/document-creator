import sys
import os
sys.stdout.reconfigure(encoding='utf-8')
sys.path.insert(0, '.')

import doc_service

def inspect_test_gcp():
    target_path = os.path.join("docs_storage", "Test-GCP.docx")
    if not os.path.exists(target_path):
        print(f"File {target_path} not found!")
        return

    doc_info = doc_service.read_document(target_path)
    print("=== INSPECTING Test-GCP.docx ===")
    print("Filename:", doc_info["filename"])
    print("Full text character length:", len(doc_info["full_text"]))
    print("Total Sections:", len(doc_info["sections"]))
    
    for idx, sec in enumerate(doc_info["sections"]):
        print(f"\n--- Section {idx+1}: [{sec['level']}] {sec['title']} ---")
        content_preview = sec['content'][:300].replace('\n', ' ')
        print("Length:", len(sec['content']))
        print("Content Preview:", repr(content_preview))
        if len(sec['content']) > 300:
            print("Tail Preview:", repr(sec['content'][-200:].replace('\n', ' ')))

if __name__ == "__main__":
    inspect_test_gcp()
