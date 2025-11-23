# Python Runtime Business Object Sample

This example mirrors the Siemens **RuntimeBO** ClientX sample using Python,
`pythonnet`, and the shared Teamcenter session infrastructure in `ClientX/`.
It performs the same steps as the original:

1. Establish a Teamcenter SOA session.
2. Create a runtime business object (RBO) instance.
3. Populate a couple of runtime properties (`srb9StringProp`, `srb9IntegerProperty`).
4. Display the service outcome and report any partial errors.

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
