# Python FileManagement Sample

> **Note:** This Python example is fully based on the copyrighted Siemens example in `examples\FileManagement\`. It serves as a direct port to demonstrate how to achieve the same functionality using Python and `pythonnet`.

This example mirrors the Siemens **ClientX** `FileManagement` sample using Python
3.12, `pythonnet`, and the reusable infrastructure that lives in `ClientX/`.
It demonstrates the following File Management Service (FMS) workflows:

1.  **Session Setup**: Establishes a connection using `ClientX.Session`.
2.  **Dataset Creation**: Uses `DataManagementService.CreateDatasets2` to create temporary *Text* datasets to hold the files.
3.  **File Staging**: Prepares local text files (copies of `ReadMe.txt`) to simulate user content.
4.  **File Upload (PutFiles)**: Uses the `FileManagementUtility.PutFiles` high-level API to upload files to the created datasets. This handles the complexity of FMS tickets (`GetDatasetWriteTickets`) internally.
5.  **Cleanup**: Deletes the temporary datasets using `DataManagementService.DeleteObjects`.
6.  **Termination**: Cleans up FMS resources using `FileManagementUtility.Term`.

The implementation intentionally follows the structure of
`examples/FileManagement/fms/FMS.cs` so readers can compare the code paths
side-by-side. By default it mirrors the C# constants: 1 single-file upload
and a 120-dataset, 3-files-per-dataset bulk upload. You can scale those
down for test rigs with `FMS_DATASET_COUNT` and `FMS_FILES_PER_DATASET`.

## Layout

```
examples/file_management_py/
├─ resources/ReadMe.txt        # Base file that gets uploaded
├─ file_management.py          # High-level helper that mirrors the C# Sample
├─ fms.py                      # CLI entry point
└─ README.md                   # You are here
```

## Running the sample

```bash
uv pip install -r requirements.txt  # ensure pythonnet + dependencies are present
source .venv/bin/activate           # or activate via your workflow

python -m examples.file_management_py.fms \
  --host http://localhost:7001/tc \
  --sso-login-url https://sso.example.com/tc \
  --sso-app-id Teamcenter \
  --work-dir ./scratch/work
```

You will be prompted for Teamcenter credentials unless the standard `TCUSER`
env vars (or SSO configuration) are provided. By default the script stages
temporary files in `examples/file_management_py/work/` and removes the
datasets it created once the upload completes.

For Single Sign-On scenarios, configure the usual environment variables used
by `ClientX.Session` (`TC_SSO_LOGIN_URL`, `TC_SSO_APP_ID`, `TC_AUTH=SSO`, …)
before launching the script, or pass the `--sso-login-url` / `--sso-app-id`
flags shown above.

Enable verbose logging with:

```bash
python -m examples.file_management_py.fms --verbose
```

The CLI exits with a non-zero status when login fails so that higher-level
automation can detect the failure.
