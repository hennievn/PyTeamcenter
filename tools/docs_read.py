"""
Helper to retrieve the full content of a specific documentation record by its ID.
Can also search by exact Title.

Examples:
    # Read a specific record by UUID
    python tools/docs_read.py 24fe8065-9257-0c47-f1e4-559336b578f5

    # Read by exact title
    python tools/docs_read.py "SessionServiceLogin(Credentials) Method"

    # Restrict search to a specific module for speed
    python tools/docs_read.py 24fe8065-9257-0c47-f1e4-559336b578f5 --module CostCt0
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Iterable

BASE = Path(__file__).resolve().parent.parent / "docs"
INDEX = BASE / "index.json"


def load_modules(patterns: list[str] | None) -> list[str]:
    """Return module filenames filtered by the provided patterns (case-insensitive)."""
    if not INDEX.exists():
        print(f"Error: Index file not found at {INDEX}", file=sys.stderr)
        sys.exit(1)
        
    try:
        index = json.loads(INDEX.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        print(f"Error: Failed to parse index file: {e}", file=sys.stderr)
        sys.exit(1)

    modules = [m["module"] for m in index.get("modules", [])]
    
    if not patterns:
        return modules
        
    pats = [p.lower() for p in patterns]
    # Filter modules that contain any of the patterns
    return [m for m in modules if any(p in m.lower() for p in pats)]


def find_record(target: str, modules: list[str]) -> dict[str, Any] | None:
    """
    Scan the specified modules for a record with matching 'id' or 'title'.
    Returns the first match found.
    """
    target_lower = target.lower()
    
    for mod in modules:
        path = BASE / f"{mod}.jsonl"
        if not path.exists():
            continue
            
        with path.open(encoding="utf-8") as f:
            for line in f:
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                
                # Check ID match (exact)
                if rec.get("id") == target:
                    return rec
                
                # Check Title match (exact, case-insensitive fallback?)
                # Let's do exact string match first
                if rec.get("title") == target:
                    return rec
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("target", help="The UUID or Exact Title of the record to retrieve.")
    parser.add_argument(
        "--module",
        "-m",
        action="append",
        help="Module name or substring to restrict search (can be repeated).",
    )
    
    args = parser.parse_args()

    # Get relevant modules
    modules = load_modules(args.module)
    if not modules:
        print("No modules matched the provided criteria.", file=sys.stderr)
        return 1

    print(f"Scanning {len(modules)} module(s) for '{args.target}'...", file=sys.stderr)
    
    record = find_record(args.target, modules)
    
    if record:
        # Output the markdown content
        print(f"\nFound in module: {record.get('module')}\n")
        print("-" * 80)
        print(record.get("markdown", "No markdown content available."))
        print("-" * 80)
        return 0
    else:
        print(f"Error: Could not find record '{args.target}' in the selected modules.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
