"""
Instantly find documentation records by title using the pre-built title index.
Requires: tools/build_title_index.py to be run first.

Examples:
    # Fuzzy search (default)
    python tools/find_title.py "ExecuteSavedQuery"

    # Exact match only
    python tools/find_title.py "DataManagementService" --exact
"""

import argparse
import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent / "docs"
TITLES_INDEX = BASE / "titles.json"

def load_titles():
    if not TITLES_INDEX.exists():
        print(f"Error: Title index not found at {TITLES_INDEX}", file=sys.stderr)
        print("Please run 'python tools/build_title_index.py' first.", file=sys.stderr)
        sys.exit(1)
    try:
        return json.loads(TITLES_INDEX.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        print(f"Error: Failed to parse {TITLES_INDEX}", file=sys.stderr)
        sys.exit(1)

def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("term", help="Title substring or exact name to search for.")
    parser.add_argument("--exact", "-e", action="store_true", help="Require exact title match.")
    parser.add_argument("--max", "-n", type=int, default=20, help="Maximum results to display (default 20).")
    
    args = parser.parse_args()
    
    entries = load_titles()
    term_lower = args.term.lower()
    
    matches = []
    
    # entry structure: [Title, Module, ID]
    for title, module, rec_id in entries:
        if args.exact:
            if title.lower() == term_lower:
                matches.append((title, module, rec_id))
        else:
            if term_lower in title.lower():
                matches.append((title, module, rec_id))
                
        if len(matches) >= args.max:
            break
            
    if not matches:
        print("No matches found.")
        return 1
        
    print(f"Found {len(matches)} matches (showing top {len(matches)}):")
    print("-" * 80)
    print(f"{ 'Module':<25} | {'Title'}")
    print("-" * 80)
    
    for title, module, rec_id in matches:
        # print nicely aligned
        print(f"{module:<25} | {title}")
        # print the command to read it easily
        # print(f"  Read: python tools/docs_read.py {rec_id} --module {module}")
        
    print("-" * 80)
    print(f"\nTo read a record, use:\npython tools/docs_read.py <UUID> --module <Module>")
    # Print the first match's read command as a convenience example
    if matches:
        first_title, first_mod, first_id = matches[0]
        print(f"Example:\npython tools/docs_read.py {first_id} --module {first_mod}")

if __name__ == "__main__":
    sys.exit(main())
