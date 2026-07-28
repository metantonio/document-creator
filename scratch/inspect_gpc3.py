import sys
import doc_service

sys.stdout.reconfigure(encoding='utf-8')

def inspect():
    res = doc_service.read_document('docs_storage/GPC3.docx')
    print("Full text length:", len(res['full_text']))
    print("Parsed sections count:", len(res['sections']))
    for idx, sec in enumerate(res['sections']):
        print(f"\n==========================================")
        print(f"Section {idx+1}: [{sec['level']}] {sec['title']}")
        print(f"==========================================")
        print(sec['content'][:500])
        print("...")

if __name__ == "__main__":
    inspect()
