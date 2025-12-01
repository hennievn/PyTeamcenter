# Python Runtime Business Object Sample

> **Note:** This Python example is fully based on the copyrighted Siemens example in `examples\RuntimeBO\`. It serves as a direct port to demonstrate how to achieve the same functionality using Python and `pythonnet`.

This example mirrors the Siemens **RuntimeBO** ClientX sample using Python,
`pythonnet`, and the shared Teamcenter session infrastructure in `ClientX/`.
It demonstrates how to interact with **Runtime Business Objects (RBOs)**, which are transient objects not persisted in the database but used for runtime operations or temporary data structures.

The workflow consists of:

1.  **Session Setup**: Authenticates with Teamcenter using `ClientX.Session`.
2.  **RBO Creation**: Uses `DataManagementService.CreateObjects` to instantiate a specific Runtime Business Object type (default: `SRB9runtimebo1`).
3.  **Property Population**: Sets initial values for runtime properties (`srb9StringProp`, `srb9IntegerProperty`) during creation.
4.  **Verification**: Logs the UID and type of the created object to confirm successful instantiation.

## Layout

```
examples/runtime_bo_py/
├─ runtime_bo.py  # Service helper that issues CreateObjects
├─ cli.py         # Command-line entry point (mirrors RuntimeBO.cs)
├─ __init__.py
└─ README.md      # You are here
```

## Running the sample

```bash
uv pip install -r requirements.txt
source .venv/bin/activate

python -m examples.runtime_bo_py.cli \
  --host http://localhost:7001/tc \
  --sso-login-url https://sso.example.com/tc \
  --sso-app-id Teamcenter \
  --bo-name SRB9runtimebo1 \
  --string-prop MySampleRuntimeBO \
  --int-prop 42 \
  --verbose
```
You can also override the defaults with environment variables
(`TC_RUNTIME_BO_NAME`, `TC_RUNTIME_BO_STRING`, `TC_RUNTIME_BO_INT`). The SSO flags
mirror the C# sample parameters and simply populate `TC_SSO_LOGIN_URL` /
`TC_SSO_APP_ID` (and `TC_AUTH=SSO`). Credentials follow the same precedence as
other samples (`TCUSER`/`TCPASSWORD`, SSO env vars, or interactive prompt).

Partial error counts are logged via Python’s `logging` module so you can see when
the server returns additional diagnostics. The CLI exits non-zero on login failure
or CreateObjects issues so wrapper scripts can detect problems.
