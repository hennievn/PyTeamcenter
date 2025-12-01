"""
List available documentation modules from the index.
Useful for finding the exact module name to pass to docs_search.py or docs_read.py.
"""

import json
from pathlib import Path
import sys

BASE = Path(__file__).resolve().parent.parent / "docs"
INDEX = BASE / "index.json"

def main():
    if not INDEX.exists():
        print(f"Error: Index file not found at {INDEX}", file=sys.stderr)
        return 1
        
    try:
        data = json.loads(INDEX.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"Error parsing index: {e}", file=sys.stderr)
        return 1

    modules = data.get("modules", [])
    print(f"Found {len(modules)} modules:\n")
    
    # Print in a neat columns format
    for m in sorted(modules, key=lambda x: x["module"]):
        name = m["module"]
        count = m.get("records", 0)
        print(f"{name:<35} ({count} records)")

if __name__ == "__main__":
    sys.exit(main())

