"""
Search specific properties across Teamcenter data structures.
Requires: tools/build_property_index.py to be run first.

Examples:
    # Find which objects have the 'checked_out_user' property
    python tools/data_structures_property_search.py "checked_out_user"

    # List all properties for 'ItemRevision' (using BO filter)
    python tools/data_structures_property_search.py --bo "ItemRevision"

    # Find exact property name 'object_name'
    python tools/data_structures_property_search.py "object_name" --exact
"""

import argparse
import json
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent / "docs" / "data_structures"
INDEX_FILE = BASE / "properties.json"

def load_properties():
    if not INDEX_FILE.exists():
        print(f"Error: Property index not found at {INDEX_FILE}", file=sys.stderr)
        print("Please run 'python tools/build_property_index.py' first.", file=sys.stderr)
        sys.exit(1)
    try:
        data = json.loads(INDEX_FILE.read_text(encoding="utf-8"))
        return data.get("properties", [])
    except json.JSONDecodeError:
        print(f"Error: Failed to parse {INDEX_FILE}", file=sys.stderr)
        sys.exit(1)

def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("term", nargs="?", help="Property name to search for.")
    parser.add_argument("--bo", help="Filter by Business Object title (substring).")
    parser.add_argument("--exact", action="store_true", help="Require exact property name match.")
    parser.add_argument("--max", "-n", type=int, default=50, help="Maximum results to display (default 50).")
    
    args = parser.parse_args()
    
    if not args.term and not args.bo:
        parser.print_help()
        return 1

    all_props = load_properties()
    matches = []
    
    term_lower = args.term.lower() if args.term else None
    bo_lower = args.bo.lower() if args.bo else None
    
    for p in all_props:
        # 1. Filter by BO Title if provided
        if bo_lower:
            if bo_lower not in p.get("bo_title", "").lower():
                continue
        
        # 2. Filter by Property Name if provided
        if term_lower:
            prop_name = p.get("name", "").lower()
            if args.exact:
                if prop_name != term_lower:
                    continue
            else:
                if term_lower not in prop_name:
                    continue
        
        matches.append(p)
        if len(matches) >= args.max:
            break
            
    if not matches:
        print("No matches found.")
        return 0
        
    print(f"Found {len(matches)} matches (showing top {args.max}):")
    print("-" * 100)
    # Header
    print(f"{'Business Object':<40} | {'Property Name':<30} | {'Type':<15} | {'Data Type'}")
    print("-" * 100)
    
    for m in matches:
        bo_title = m.get('bo_title', 'Unknown')[:38]
        name = m.get('name', '')[:28]
        ptype = m.get('type', '')[:13]
        dtype = m.get('data_type', '')
        
        print(f"{bo_title:<40} | {name:<30} | {ptype:<15} | {dtype}")

if __name__ == "__main__":
    sys.exit(main())
