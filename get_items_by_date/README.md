# Get Items by Date

This utility queries Teamcenter for Items created within a specific date range and exports their details, including Item Master and Latest Revision properties, to a JSON file.

It supports loading configuration (host, username, password) from a `.env` file in the project root, which can be overridden by command-line arguments.

## Usage

```bash
python get_items_by_date.py --start YYYY-MM-DD --end YYYY-MM-DD --output <output_file.json> [--host <tc_url>] [--user <username>] [--password <password>]
```

### Arguments

- `--start`: The start date (inclusive) in `YYYY-MM-DD` format.
- `--end`: The end date (inclusive) in `YYYY-MM-DD` format.
- `--output`: The path to the output JSON file.
- `--host`: (Optional) The Teamcenter host URL. Defaults to `TC_URL` in `.env` or `http://localhost:8080/tc`.
- `--user`: (Optional) Teamcenter username. Defaults to `TCUSER` in `.env`.
- `--password`: (Optional) Teamcenter password. Defaults to `TCPASSWORD` in `.env`.

### Example

```bash
python get_items_by_date.py --start 2025-01-01 --end 2025-01-31 --output january_items.json
```

## Output Format

The script produces a JSON array of objects with the following structure:

```json
[
  {
    "item_id": "000123",
    "uid": "QkRE...",
    "object_name": "Engine Bracket",
    "item_master": {
      "uid": "QkRE...",
      "object_name": "Engine Bracket Master"
    },
    "latest_revision": {
      "uid": "QkRE...",
      "item_revision_id": "A",
      "object_name": "Engine Bracket/A",
      "creation_date": "23-Jan-2025 14:30"
    }
  }
]
```

## Prerequisites

- This script requires the Teamcenter SOA client libraries and the `ClientX` session management modules to be available in the parent directory.
- Ensure you have set up your Teamcenter credentials (either via environment variables or interactive login).
