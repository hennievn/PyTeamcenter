"""
Scans all documentation modules (.jsonl) and builds a lightweight index of Titles.
Output: docs/titles.json

This index allows for instant lookup of method/class names without scanning
hundreds of megabytes of text.
"""

import json
import sys
from pathlib import Path
import time

BASE = Path(__file__).resolve().parent.parent / "docs"
INDEX = BASE / "index.json"
OUTPUT = BASE / "titles.json"

def load_manifest():
    if not INDEX.exists():
        print(f"Error: Manifest not found at {INDEX}", file=sys.stderr)
        sys.exit(1)
    return json.loads(INDEX.read_text(encoding="utf-8"))

def main():
    print("Building title index...")
    start_time = time.time()
    
    manifest = load_manifest()
    modules = manifest.get("modules", [])
    
    # Structure: [ [Title, Module, ID], ... ]
    # Using list of lists/tuples is more space-efficient than list of dicts for JSON
    title_index = []
    
    total_records = 0
    processed_modules = 0
    
    for mod_entry in modules:
        mod_name = mod_entry["module"]
        filename = mod_entry["file"]
        path = BASE / filename
        
        if not path.exists():
            continue
            
        with path.open(encoding="utf-8") as f:
            for line in f:
                try:
                    rec = json.loads(line)
                    title = rec.get("title")
                    rec_id = rec.get("id")
                    
                    if title and rec_id:
                        # Store as concise tuple
                        title_index.append((title, mod_name, rec_id))
                        total_records += 1
                except json.JSONDecodeError:
                    continue
        
        processed_modules += 1
        print(f"\rProcessed {processed_modules}/{len(modules)} modules ({total_records} titles)...", end="")

    print(f"\n\nFinished.")
    print(f"Total Titles: {len(title_index)}")
    
    print(f"Writing to {OUTPUT}...")
    with OUTPUT.open("w", encoding="utf-8") as f:
        json.dump(title_index, f)
        
    size_mb = OUTPUT.stat().st_size / (1024 * 1024)
    print(f"Index size: {size_mb:.2f} MB")
    print(f"Time taken: {time.time() - start_time:.2f}s")

if __name__ == "__main__":
    main()
