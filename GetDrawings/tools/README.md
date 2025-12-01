# Teamcenter Documentation Tools

This directory contains a suite of utility scripts designed to index, search, and retrieve Teamcenter documentation efficiently. Because the full documentation set is massive (often exceeding hundreds of megabytes of text), these tools rely on pre-built indices to provide fast response times suitable for CLI interaction and LLM context retrieval.

> **Important:** Access to the underlying Teamcenter documentation requires a valid Siemens license. The documentation files (`docs/*.jsonl`) and generated indices are not included in the public repository for copyright reasons.

## Indexing Workflow

Before using the search tools, you must generate the necessary indices. These scripts parse the raw JSONL documentation bundles and create lightweight JSON/CSV mappings.

1.  **General API Titles Index**
    *   **Script:** `python tools/build_title_index.py`
    *   **Input:** `docs/*.jsonl` (all module files listed in `docs/index.json`)
    *   **Output:** `docs/titles.json`
    *   **Purpose:** Maps every API class/method/service title to its Module and UUID. Used by `find_title.py`.

2.  **Data Structures Offset Index**
    *   **Script:** `python tools/build_jsonl_index.py`
    *   **Input:** `docs/data_structures.jsonl`
    *   **Output:** `docs/data_structures.index.json`
    *   **Purpose:** Maps `DOC######` IDs to byte offsets. Allows `data_structures_read.py` to jump instantly to a record without reading the whole file.

3.  **Data Structures Property Index** (Optional)
    *   **Script:** `python tools/build_property_index.py` (Not shown in file list, but referenced in `data_structures_property_search.py`)
    *   **Output:** `docs/data_structures/properties.json`
    *   **Purpose:** creates a reverse lookup for properties to their owning business objects.

4.  **Full-Text Search Index (Lunr)** (Optional - Node.js)
    *   **Script:** `node tools/build_lunr_index.js`
    *   **Input:** `docs/*.jsonl`
    *   **Output:** `docs/lunr-index.json`
    *   **Purpose:** Creates a static inverted index for fuzzy full-text search.

## Search & Retrieval Tools

Once indexed, use these tools to query the documentation.

### 1. General Teamcenter .NET API (Classes, Methods, Services)

*   **Find by Title (Fast):**
    *   **Script:** `find_title.py`
    *   **Usage:** `python tools/find_title.py "SessionService"`
    *   **Description:** Instantly looks up exact or fuzzy titles. Best for finding the Module and UUID of a known class or method.

*   **Search Content (Broad):**
    *   **Script:** `docs_search.py`
    *   **Usage:** `python tools/docs_search.py "Login" --module CostCt0`
    *   **Description:** Streams through JSONL files searching for a substring in the title or markdown content. Can be slow if not restricted by `--module`.

*   **Read Record:**
    *   **Script:** `docs_read.py`
    *   **Usage:** `python tools/docs_read.py <UUID> --module <ModuleName>`
    *   **Description:** Retrieves the full markdown content for a specific record.

*   **List Modules:**
    *   **Script:** `list_modules.py`
    *   **Usage:** `python tools/list_modules.py`
    *   **Description:** Lists all available API modules and their record counts.

### 2. Teamcenter Data Structures (Business Objects, Properties)

*   **Search by Title:**
    *   **Script:** `data_structures_title_search.py`
    *   **Usage:** `python tools/data_structures_title_search.py "ItemRevision"`
    *   **Description:** Finds Business Objects or Types by name.

*   **Search Properties:**
    *   **Script:** `data_structures_property_search.py`
    *   **Usage:** `python tools/data_structures_property_search.py "checked_out_user"`
    *   **Description:** Finds which Business Objects contain a specific property, or lists all properties of a specific object.

*   **Search Content (Deep):**
    *   **Script:** `data_structures_search.py`
    *   **Usage:** `python tools/data_structures_search.py "regex_pattern"`
    *   **Description:** Uses `ripgrep` (if available) to scan the raw `data_structures.jsonl` for text matches.

*   **Read Document:**
    *   **Script:** `data_structures_read.py`
    *   **Usage:** `python tools/data_structures_read.py DOC000123`
    *   **Description:** Retrieves the full definition of a data structure object using the byte-offset index.

### 3. Full Text Search (Node.js)

*   **Script:** `search_lunr.js`
*   **Usage:** `node tools/search_lunr.js "query terms"`
*   **Description:** Performs a ranked full-text search against the pre-built Lunr index. Useful when you don't know where a concept resides.

## Testing & Debugging

*   **SOA Diagnostics:**
    *   **Script:** `test_getiar.py`
    *   **Usage:** `python tools/test_getiar.py <Item_ID>`
    *   **Description:** A standalone script to test the `GetItemAndRelatedObjects` service call. It handles login, payload construction, and logging, which is useful for debugging connectivity or data issues without running the full GUI application.
