# Python HelloTeamcenter Sample

> **Note:** This Python example is fully based on the copyrighted Siemens example in `examples\HelloTeamcenter\`. It serves as a direct port to demonstrate how to achieve the same functionality using Python and `pythonnet`.

This example mirrors the Siemens **HelloTeamcenter** ClientX sample using
Python, `pythonnet`, and the shared session helpers in `ClientX/`. It performs
the same high-level workflow:

1. **Establish a Session:** Connects to the Teamcenter SOA server using `ClientX.Session`, handling credentials and login (including SSO support).
2. **Home Folder Listing:** Retrieves the logged-in user's Home folder and lists its contents, demonstrating property retrieval (`GetProperties`) and object loading (`LoadObjects`).
3. **Saved Query Execution:** Finds and executes the system "Item Name" saved query, paginating through results and displaying object details. This demonstrates `SavedQueryService`.
4. **Data Management Workflow:** Performs a complete lifecycle test:
    - Generates Item and Revision IDs (`GenerateItemIdsAndInitialRevisionIds`).
    - Creates Items with specific properties and forms (`CreateItems`, `CreateOrUpdateForms`).
    - Revises the created items (`Revise2`).
    - Deletes the created objects to clean up (`DeleteObjects`).

## Layout

```
examples/hello_teamcenter_py/
├─ home_folder.py      # Demonstrates traversing the Home Folder and loading properties.
├─ query_service.py    # Demonstrates finding and executing Saved Queries.
├─ data_management.py  # Demonstrates creating, revising, and deleting Items.
├─ cli.py              # Command-line entry point orchestrating the examples.
├─ __init__.py
└─ README.md           # You are here
```

## Running the sample

```bash
uv pip install -r requirements.txt
source .venv/bin/activate

python -m examples.hello_teamcenter_py.cli \
  --host http://localhost:7001/tc \
  --sso-login-url https://sso.example.com/tc \
  --sso-app-id Teamcenter \
  --verbose
```

Credentials follow the normal precedence (environment variables or interactive
prompt) via `ClientX.Session`. Logging captures both the descriptive output and
any partial errors returned from the strong services so you can inspect the
results of each stage. The SSO flags mirror the C# sample parameters and simply
populate `TC_SSO_LOGIN_URL` / `TC_SSO_APP_ID` (and `TC_AUTH=SSO`).
