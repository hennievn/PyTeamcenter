# Python ProductConfigurator Sample

> **Note:** This Python example is fully based on the copyrighted Siemens example in `examples\ProductConfigurator\`. It serves as a direct port to demonstrate how to achieve the same functionality using Python and `pythonnet`.

This example mirrors the Siemens **ProductConfigurator** VB sample using Python
3.12, `pythonnet`, and the reusable infrastructure under `ClientX/`.
It demonstrates how to perform the following configuration management tasks:

1.  **Initialize Factories & Policies**: Sets up the `StrongObjectFactory` for configurator types (`Cfg0SoaStrongModelConfigurator`) and configures an `ObjectPropertyPolicy` to ensure necessary properties (e.g., `cfg0ConfigPerspective`) are loaded.
2.  **Find Product Item**: Retrieves a `Cfg0ProductItem` (or standard `Item`) by its ID using `DataManagementService.GetItemFromAttribute`.
3.  **Get Perspective**: Resolves the `cfg0ConfigPerspective` property from the product item. This object is the entry point for variability queries.
4.  **Get Variability**: Calls `ConfiguratorManagementService.GetVariability` using the resolved perspective to fetch configuration data (options, families, etc.).

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
