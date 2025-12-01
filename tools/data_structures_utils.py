"""
Shared helpers for working with the Teamcenter data structure JSONL bundle.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional, Any

BASE = Path(__file__).resolve().parent.parent / "docs"
JSONL_PATH = BASE / "data_structures.jsonl"
INDEX_PATH = BASE / "data_structures.index.json"

_INDEX_CACHE = None

def normalize_id(raw: str) -> str:
    """Normalize IDs to DOC###### form."""
    cleaned = raw.strip().upper()
    digits = re.search(r"(\d+)", cleaned)
    if not digits:
        return cleaned
    return f"DOC{int(digits.group(1)):06d}"


def id_to_int(doc_id: str) -> Optional[int]:
    match = re.search(r"(\d+)", doc_id)
    return int(match.group(1)) if match else None


def load_index() -> Dict[str, List[Any]]:
    """Return index: {doc_id: [offset, title, rel_path]}."""
    global _INDEX_CACHE
    if _INDEX_CACHE is not None:
        return _INDEX_CACHE
    
    if not INDEX_PATH.exists():
        # Fallback or error?
        raise FileNotFoundError(f"Index file not found at {INDEX_PATH}. Run tools/build_jsonl_index.py.")
    
    with INDEX_PATH.open("r", encoding="utf-8") as f:
        _INDEX_CACHE = json.load(f)
    return _INDEX_CACHE


def get_doc(doc_id: str) -> Optional[Dict[str, Any]]:
    """Retrieve full document record by ID."""
    doc_id = normalize_id(doc_id)
    index = load_index()
    meta = index.get(doc_id)
    if not meta:
        return None
    
    offset = meta[0]
    if not JSONL_PATH.exists():
         raise FileNotFoundError(f"JSONL file not found at {JSONL_PATH}")

    with JSONL_PATH.open("rb") as f:
        f.seek(offset)
        line = f.readline()
        return json.loads(line)


def filter_records(
    ids: Iterable[str] | None = None,
    id_min: Optional[int] = None,
    id_max: Optional[int] = None,
) -> Iterator[Dict[str, Any]]:
    """Yield records (metadata) filtered by ID set and/or numeric range."""
    index = load_index()
    allowed = {normalize_id(i) for i in ids} if ids else None
    
    for doc_id, meta in index.items():
        if allowed and doc_id not in allowed:
            continue
        
        numeric = id_to_int(doc_id)
        if id_min is not None and (numeric is None or numeric < id_min):
            continue
        if id_max is not None and (numeric is None or numeric > id_max):
            continue
        
        yield {
            "id": doc_id,
            "title": meta[1],
            "rel_path": meta[2]
        }