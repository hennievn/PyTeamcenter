# Python FileManagement Sample

This example mirrors the Siemens **ClientX** `FileManagement` sample using Python
3.12, `pythonnet`, and the reusable infrastructure that lives in `ClientX/`.
It demonstrates how to:

- bootstrap a Teamcenter SOA session with the existing Python `ClientX.Session`
  helper,
- use `DataManagementService.CreateDatasets2` to create scratch *Text* datasets,
- stage local files and upload them through `FileManagementUtility.PutFiles`,
- delete the temporary datasets, and
- gracefully terminate the FMS connection with `FileManagementUtility.Term`.

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
