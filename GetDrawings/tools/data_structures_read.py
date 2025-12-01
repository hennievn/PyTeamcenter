"""
Retrieve a specific data structure document by DOC id or path from the JSONL bundle.

Examples:
    # Read by DOC id
    python tools/data_structures_read.py DOC000018

    # Read by numeric id (auto-normalized)
    python tools/data_structures_read.py 18

    # Read by relative path (partial match supported)
    python tools/data_structures_read.py "documentation/external/.../index.html"
"""

from __future__ import annotations

import argparse
import sys

from data_structures_utils import get_doc, load_index, normalize_id


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("target", help="DOC id (e.g. DOC000018 or 18) or relative path.")
    args = parser.parse_args()

    target = args.target
    doc = None

    # 1. Try as ID
    doc_id = normalize_id(target)
    doc = get_doc(doc_id)

    # 2. Try as path (if ID failed or target looks like a path)
    if not doc:
        # Iterate index to find path match
        try:
            index = load_index()
            target_norm = target.replace("\\", "/").strip("/")
            for did, meta in index.items():
                # meta = [offset, title, rel_path]
                rel_path = meta[2]
                if rel_path and (rel_path == target_norm or rel_path.endswith(target_norm)):
                    doc = get_doc(did)
                    break
        except Exception as e:
            print(f"Index search error: {e}", file=sys.stderr)

    if not doc:
        print(f"Document not found: {target}", file=sys.stderr)
        return 1

    print(f"{doc.get('id')} | {doc.get('title')}")
    print(f"rel_path: {doc.get('rel_path')}")
    print("-" * 80)
    print(doc.get("content", ""))
    
    props = doc.get("properties", [])
    if props:
        print("\nProperties:")
        print("-" * 40)
        # Display a table-like format
        print(f"{ 'Name':<30} | { 'Type':<15} | { 'Data Type'}")
        print("-" * 80)
        for p in props[:50]:
            name = p.get('name', '')[:28]
            ptype = p.get('type', '')[:13]
            dtype = p.get('data_type', '')
            print(f"{name:<30} | {ptype:<15} | {dtype}")
        
        if len(props) > 50:
            print(f"... and {len(props)-50} more.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())