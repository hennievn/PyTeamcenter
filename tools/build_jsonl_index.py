"""
Builds a byte-offset index for the large `data_structures.jsonl` file.

This script scans `docs/data_structures.jsonl` and generates a corresponding
`docs/data_structures.index.json`. This index maps Document IDs (e.g., DOC000123)
to their byte offset in the JSONL file, allowing for O(1) retrieval of specific
records without loading the entire multi-megabyte dataset into memory.

It also stores metadata like the Title and Relative Path for quick lookups.
"""

import json
import sys
from pathlib import Path

JSONL = Path(__file__).resolve().parent.parent / "docs" / "data_structures.jsonl"
INDEX_OUT = Path(__file__).resolve().parent.parent / "docs" / "data_structures.index.json"

def main():
    if not JSONL.exists():
        print(f"{JSONL} not found.")
        return 1
    
    index = {}
    offset = 0
    count = 0
    max_len = 0
    
    print(f"Indexing {JSONL}...")
    
    with open(JSONL, "rb") as f:
        for line in f:
            length = len(line)
            try:
                # Optimization: Parse only metadata (id, title, rel_path)
                # We know 'content' is the heavy field.
                # Find where "content" starts.
                # line is bytes.
                
                # Search for "content": pattern
                # JSON keys are quoted.
                idx_content = line.find(b'"content":')
                if idx_content > 0:
                    # Extract everything before content, add closing brace to make valid JSON
                    # Note: This assumes 'content' is after the metadata we want
                    # and that the pre-content part is valid JSON if we close it.
                    # Structure: {"id": "...", "title": "...", "rel_path": "...", "content": ...
                    # Slicing before "content": gives {"id": ..., "rel_path": ..., 
                    # We need to strip the trailing comma if present.
                    
                    pre_content = line[:idx_content].strip()
                    if pre_content.endswith(b","):
                        pre_content = pre_content[:-1]
                    
                    pre_content += b"}"
                    
                    meta = json.loads(pre_content)
                    doc_id = meta.get("id")
                    if doc_id:
                        # Store [offset, title, rel_path]
                        index[doc_id] = [offset, meta.get("title", ""), meta.get("rel_path", "")]
                else:
                    # Fallback: parse whole line (rare case where content is missing or at end?)
                    # Or maybe content is missing.
                    meta = json.loads(line)
                    doc_id = meta.get("id")
                    if doc_id:
                         index[doc_id] = [offset, meta.get("title", ""), meta.get("rel_path", "")]

            except Exception as e:
                # print(f"Error parsing line at {offset}: {e}")
                pass
            
            if length > max_len:
                max_len = length
            offset += length
            count += 1
            if count % 1000 == 0:
                print(f"Indexed {count} records... (Max line: {max_len/1024/1024:.2f} MB)", end="\r")

    print(f"\nIndexed {len(index)} records. Index saved to {INDEX_OUT}")
    with open(INDEX_OUT, "w", encoding="utf-8") as f:
        json.dump(index, f)
    return 0

if __name__ == "__main__":
    sys.exit(main())
