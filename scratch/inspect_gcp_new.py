import sys
import doc_service

sys.stdout.reconfigure(encoding='utf-8')

def inspect():
    res = doc_service.read_document('docs_storage/GCP new.docx')
    print("Full text length:", len(res['full_text']))
    print("Parsed sections count:", len(res['sections']))
    for idx, sec in enumerate(res['sections'][:10]):
        print(f"\n--- Section {idx+1}: [{sec['level']}] {sec['title']} ---")
        print(sec['content'][:300])

if __name__ == "__main__":
    inspect()
