# Python ProductConfigurator Sample

This example mirrors the Siemens **ProductConfigurator** VB sample using Python
3.12, `pythonnet`, and the reusable infrastructure under `ClientX/`.
It demonstrates how to:

- establish a Teamcenter SOA session with `ClientX.Session`,
- initialise strong object factories and property policies required by the
  configurator model,
- retrieve a product item by `item_id` using `GetItemFromAttribute`,
- resolve the associated configurator perspective, and
- call `ConfiguratorManagementService.GetVariability`.

The structure intentionally matches the original VB project so the flow can be
compared side-by-side.

## Layout

```
examples/product_configurator_py/
├─ configurator_management.py  # Utility functions ported from the VB code
├─ product_configurator.py     # CLI entry point
├─ __init__.py
└─ README.md                   # You are here
```

## Running the sample

```bash
uv pip install -r requirements.txt  # ensure pythonnet + dependencies
source .venv/bin/activate           # or your environment workflow

python -m examples.product_configurator_py.product_configurator \
  --host http://localhost:7001/tc \
  --sso-login-url https://sso.example.com/tc \
  --sso-app-id Teamcenter \
  030989
```

Authentication behaviour follows the reusable `ClientX.Session` module:
credentials come from `TCUSER`/`TCPASSWORD` (or SSO environment variables), or
you will be prompted interactively.

Enable verbose logging with:

```bash
python -m examples.product_configurator_py.product_configurator --host http://GVWTCUPRODAPP.gvwholdings.com:8001/tc AE650009-001 --verbose
```

The script exits with a non-zero status when any step fails (login, item lookup,
missing perspective, or variability retrieval) so that CI or wrapper scripts can
detect failures. The SSO flags mirror the VB sample parameters and simply
populate `TC_SSO_LOGIN_URL` / `TC_SSO_APP_ID` (and `TC_AUTH=SSO`).
