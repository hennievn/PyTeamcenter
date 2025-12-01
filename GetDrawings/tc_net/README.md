# Teamcenter Network Core (`tc_net.core`)

This module provides a Pythonic abstraction layer over the low-level Teamcenter Service Oriented Architecture (SOA) client libraries (`Teamcenter.Services.*`). It simplifies connection management, data retrieval, and file operations.

## Purpose

Directly interacting with the Teamcenter SOA API in Python (via `pythonnet`) can be verbose and error-prone due to the strict typing of .NET and the complexity of the data model (e.g., property policies, partial errors, ModelObject handling).

`tc_net.core` addresses this by:
- **Managing Sessions**: Encapsulating `Connection` creation and `SessionService` login.
- **Optimizing Performance**: Implementing `ObjectPropertyPolicy` to limit network payload size.
- **Simplifying Queries**: Providing high-level functions like `get_item_latest_with_datasets` that combine multiple SOA calls (`GetItemFromAttribute`, `GetItemAndRelatedObjects`) and handle fallbacks automatically.
- **Handling Files**: Abstracting the complexity of the File Management System (FMS), handling both cached file retrieval (`FileManagementUtility`) and ticket-based downloads (`FileManagementService`).

## Key Functions

### Connection & Session
- **`connect(url, user, pwd, ...)`**: Establishes a connection to the Teamcenter server.
- **`set_default_policy(conn)`**: Applies a standard property policy to ensure commonly used properties (like `object_name`, `item_id`) are always loaded, avoiding `NotLoadedException`.

### Data Retrieval
- **`get_item_latest_with_datasets(conn, item_id, ...)`**: The robust workhorse for finding items. It attempts to use the efficient `GetItemAndRelatedObjects` service (returning the item, revision, and datasets in one go) and falls back to `GetItemFromAttribute` if necessary.
- **`get_drawing_datasets(conn, item_id, ...)`**: Specialized logic to find "drawing" files. It looks for datasets attached directly to the Item Revision *and* recursively checks related Document Revisions (e.g., `Fnd0IsDescribedByDocument`).

### File Operations
- **`download_drawing_datasets(conn, datasets, output_dir)`**: Downloads the physical files (PDFs, Excel, etc.) associated with the given dataset objects. It intelligently prioritizes the local FMS cache to speed up repeated downloads and falls back to requesting new FMS tickets from the server if the cache is cold.

## Usage Example

```python
from tc_net import core

# 1. Connect
conn = core.connect("http://tcserver:8080/tc", "user", "password")
core.set_default_policy(conn)

# 2. Find Datasets
# This finds the item, its latest revision, and any PDF/Excel datasets
datasets, item_output = core.get_drawing_datasets(conn, "12345", wanted=("pdf",))

# 3. Download
# Downloads the found datasets to the local "downloads" folder
results = core.download_drawing_datasets(conn, datasets, "downloads")

print(f"Downloaded {len(results)} files.")
```

## Dependencies

This module relies on the `pythonnet` CLR to interface with the Teamcenter .NET DLLs. It expects the following namespaces to be available:
- `Teamcenter.Soa.Client`
- `Teamcenter.Services.Strong.Core`
- `Teamcenter.Services.Loose.Core`
