"""
Lightweight helper to stream search the pre-extracted Teamcenter docs.

Examples:
    # Find LoginSSO in the core SOA docs
    python tools/docs_search.py LoginSSO --module CostCt0 --max 5

    # Fuzzy module match (ServiceRequest) and show first 3 hits
    python tools/docs_search.py CredentialType --module servicerequest --max 3

Modules come from docs/index.json and are matched case-insensitively.
Search scans title, path, and markdown text for the term.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable, Sequence

BASE = Path(__file__).resolve().parent.parent / "docs"
INDEX = BASE / "index.json"


def load_modules(patterns: Sequence[str] | None) -> list[str]:
    """Return modules filtered by the provided patterns (case-insensitive)."""
    index = json.loads(INDEX.read_text(encoding="utf-8"))
    modules = [m["module"] for m in index.get("modules", [])]
    if not patterns:
        return modules
    pats = [p.lower() for p in patterns]
    return [m for m in modules if any(p in m.lower() for p in pats)]


def iter_records(modules: Iterable[str]):
    """Yield records (module, record dict) from the selected modules."""
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
                yield mod, rec


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("term", help="Substring to search for (case-insensitive).")
    parser.add_argument(
        "--module",
        "-m",
        action="append",
        help="Module name or substring (can be repeated). Defaults to all modules.",
    )
    parser.add_argument(
        "--max",
        type=int,
        default=5,
        help="Maximum number of matches to print.",
    )
    args = parser.parse_args()

    modules = load_modules(args.module)
    if not modules:
        raise SystemExit("No modules matched the provided patterns.")

    term = args.term.lower()
    printed = 0
    for mod, rec in iter_records(modules):
        text = " ".join(
            [
                rec.get("title", ""),
                rec.get("path", ""),
                rec.get("markdown", ""),
            ]
        ).lower()
        if term not in text:
            continue
        print(f"[{mod}] {rec.get('title', '<no title>')} :: {rec.get('path', '')}")
        printed += 1
        if printed >= args.max:
            break

    if printed == 0:
        print("No matches found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
