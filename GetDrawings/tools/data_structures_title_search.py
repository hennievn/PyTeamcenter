"""
Quickly search data structure docs by title (and optionally rel_path) using
the lightweight CSV index. This avoids scanning the markdown content and keeps
lookups fast enough for Gemini prompts.

Examples:
    # Title search (default)
    python tools/data_structures_title_search.py "Audit Definition" --max 5

    # Restrict to DOC000001-DOC000120 and include rel_path matches
    python tools/data_structures_title_search.py "Capa" --range 1-120 --include-path

    # Exact ID lookup for the path/title
    python tools/data_structures_title_search.py DOC000018 --ids DOC000018
"""

from __future__ import annotations

import argparse
import sys
from typing import Iterable

from data_structures_utils import filter_records, load_index, normalize_id


def parse_range(value: str) -> tuple[int | None, int | None]:
    try:
        start, end = value.split("-", 1)
        start_val = int(start) if start.strip() else None
        end_val = int(end) if end.strip() else None
        return start_val, end_val
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Range must look like '1-120'") from exc


def flatten_ids(values: Iterable[str] | None) -> list[str]:
    if not values:
        return []
    result: list[str] = []
    for val in values:
        parts = [p for p in val.split(",") if p.strip()]
        result.extend(parts)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("term", help="Case-insensitive substring to match.")
    parser.add_argument(
        "--include-path",
        action="store_true",
        help="Match rel_path as well as title (title-only by default).",
    )
    parser.add_argument(
        "--ids",
        "-i",
        action="append",
        help="Limit search to specific DOC ids (repeatable or comma separated).",
    )
    parser.add_argument(
        "--range",
        "-r",
        type=parse_range,
        help="Numeric DOC id range, e.g. 1-120 (either side optional).",
    )
    parser.add_argument(
        "--max",
        "-n",
        type=int,
        default=20,
        help="Maximum results to print (default 20).",
    )
    args = parser.parse_args()

    id_min, id_max = (args.range or (None, None))
    ids = [normalize_id(i) for i in flatten_ids(args.ids)]

    term = args.term.lower()
    matches = []

    for rec in filter_records(ids=ids, id_min=id_min, id_max=id_max):
        title = rec.get("title", "")
        rel_path = rec.get("rel_path", "")
        target_texts = [title]
        if args.include_path:
            target_texts.append(rel_path)
        if any(term in (t or "").lower() for t in target_texts):
            matches.append((rec.get("id", ""), title, rel_path))
        if len(matches) >= args.max:
            break

    if not matches:
        print("No matches found.")
        return 0

    print(f"Found {len(matches)} match(es):")
    print("-" * 80)
    for doc_id, title, rel_path in matches:
        print(f"{doc_id} | {title} | {rel_path}")
    print("-" * 80)
    if matches:
        doc_id = matches[0][0]
        print(f"Read the full markdown with:\npython tools/data_structures_read.py {doc_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
