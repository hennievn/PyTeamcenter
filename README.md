# PyTeamcenter

**PyTeamcenter** is a comprehensive collection of Python modules, examples, and utilities for interacting with **Siemens Teamcenter** using the Service Oriented Architecture (SOA) APIs.

It leverages [`pythonnet`](https://github.com/pythonnet/pythonnet) to bridge Python with the standard Teamcenter .NET client libraries, providing a Pythonic interface to the robust Teamcenter ecosystem. This project serves as both a learning resource (porting official Siemens C# examples to Python) and a toolkit for real-world automation tasks.

## Core Infrastructure

### [ClientX](./ClientX/README.md)
The backbone of this project. It is a direct Python port of the official Siemens `ClientX` .NET example. It provides reusable classes for:
*   **Session Management**: Singleton-based connection handling.
*   **Authentication**: Supports both Classic (User/Password) and **Single Sign-On (SSO)**.
*   **Error Handling**: robust handling of `InternalServerException`, `PartialErrors`, and connection retries.
*   **Model Listening**: Monitoring changes to the client-side data model.
*   **Logging**: Detailed inspection of SOA requests and responses.

All other examples and utilities in this repository rely on `ClientX` for stable connectivity.

---

## Official Example Ports

These directories contain faithful Python translations of the standard Siemens .NET SOA samples. They demonstrate specific service capabilities while maintaining the structure of the original C# code for easy comparison.

| Module | Description |
| :--- | :--- |
| **[HelloTeamcenter](./HelloTeamcenter/README.md)** | The entry point. Demonstrates basic login, Home folder traversal, Saved Queries, and basic Item CRUD (Create, Revise, Delete) workflows. |
| **[FileManagement](./FileManagement/README.md)** | Covers the **File Management Service (FMS)**. Shows how to upload/download files, manage datasets, and handle FMS tickets. |
| **[ProductConfigurator](./ProductConfigurator/README.md)** | Demonstrates the **Configurator** services, including retrieving product variability, handling perspectives, and resolving configuration options. |
| **[RunTimeBO](./RunTimeBO/README.md)** | Shows how to work with **Runtime Business Objects (RBOs)**—transient objects used for temporary data or calculation results. |
| **[VendorManagement](./VendorManagement/README.md)** | Covers the **Vendor Management** solution, including creating Vendors, Bid Packages, Line Items, and Vendor Parts. |

---

## Productivity Utilities

Stand-alone tools designed for common administrative or data extraction tasks.

### [Get Drawings](./GetDrawings/README.md)
A production-ready utility to batch download drawing files (PDF, Excel, etc.) for a list of part numbers.
*   **Features**: GUI and CLI support, efficient bulk loading, FMS cache utilization.
*   **Internals**: Powered by the custom `tc_net` abstraction layer.

### [Get Items By Date](./get_items_by_date/README.md)
Queries Teamcenter for Items created within a specific date range.
*   **Output**: Exports Item Master and Latest Revision details to JSON.
*   **Usage**: Ideal for reporting or feeding into other automation pipelines.

### [Get Where Used](./get_where_used/README.md)
Performs "Where Used" analysis on a list of items.
*   **Input**: Consumes the JSON output from `get_items_by_date`.
*   **Features**: Finds parent assemblies (precise/imprecise) and resolves their latest revisions.

---

## Documentation Tools

### [Documentation Search & Indexing](./GetDrawings/tools/README.md)
A suite of scripts located in `GetDrawings/tools/` designed to index and search massive Teamcenter API documentation (JSONL format).
*   **Capabilities**: Fast title search, full-text search (Lunr), and deep property inspection.
*   **Use Case**: Essential for developers navigating the vast Teamcenter data model or feeding context to LLMs.

---

## Prerequisites

1.  **Python 3.8+** (Recommended: 3.10+)
2.  **pythonnet**: `pip install pythonnet`
3.  **Teamcenter .NET Libraries**: You must have the Teamcenter SOA client DLLs (e.g., `Teamcenter.Soa.Client.dll`, `Teamcenter.Services.Strong.Core.dll`) available in your environment or registered in the GAC.
4.  **Teamcenter Connection**: A running Teamcenter server (HTTP/HTTPS) and valid credentials.

## Getting Started

1.  **Install Dependencies**:
    ```bash
    pip install -r requirements.txt
    ```
2.  **Configure Environment**:
    Set up a `.env` file or environment variables for your connection:
    ```bash
    export TC_URL="http://localhost:8080/tc"
    export TCUSER="infodba"
    export TCPASSWORD="infodba"
    # For SSO:
    # export TC_SSO_LOGIN_URL="..."
    # export TC_SSO_APP_ID="Teamcenter"
    ```
3.  **Run an Example**:
    ```bash
    python -m HelloTeamcenter.cli --verbose
    ```