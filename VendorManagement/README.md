# Python VendorManagement Sample

> **Note:** This Python example is fully based on the copyrighted Siemens example in `examples\VendorManagement\`. It serves as a direct port to demonstrate how to achieve the same functionality using Python and `pythonnet`.

This example mirrors the Siemens **VendorManagement** ClientX sample using
Python 3.12, `pythonnet`, and the reusable session infrastructure in `ClientX/`.
It demonstrates calling the vendor management strong services to create/update
vendors, bid packages, line items, vendor roles, and vendor parts.

The sample covers the following operations using `VendorManagementService`:

1.  **createVendors**: Creates or updates a Vendor object (`CreateOrUpdateVendors`).
2.  **createBidPackages**: Creates or updates a Bid Package (`CreateOrUpdateBidPackages`).
3.  **createLineItems**: Creates a line item and associates it with a bid package revision (`CreateOrUpdateLineItems`).
4.  **deleteVendorRoles**: Removes a specific role from a vendor (`DeleteVendorRoles`).
5.  **deleteVendors**: Deletes a vendor and its associated revisions/roles (`DeleteVendors`).
6.  **createParts**: Creates a vendor part, either a Commercial Part or Manufacturer Part (`CreateOrUpdateVendorParts`).

## Layout

```
examples/vendor_management_py/
├─ vendor_management.py   # Service helpers (ported from the VB code)
├─ cli.py                 # Interactive menu, mirrors VendorManagementMain.cs
├─ __init__.py
└─ README.md              # You are here
```

## Running the sample

```bash
uv pip install -r requirements.txt
source .venv/bin/activate

python -m examples.vendor_management_py.cli --host http://GVWTCUPRODAPP.gvwholdings.com:8001/tc --verbose


```

You can also pass SSO options to mirror the C# sample:

```bash
python -m examples.vendor_management_py.cli \
  --host http://localhost:7001/tc \
  --sso-login-url https://sso.example.com/tc \
  --sso-app-id Teamcenter \
  --verbose
```

Authentication uses the `ClientX.Session` helper: credentials are pulled from
`TCUSER`/`TCPASSWORD` (or SSO environment variables) when available, otherwise
you will be prompted. The SSO flags simply populate `TC_SSO_LOGIN_URL` /
`TC_SSO_APP_ID` (and `TC_AUTH=SSO`).

After login an interactive menu is shown. Enter the number of the service you
wish to execute and provide the prompted data (matching the VB example). The
script logs partial-error counts returned by each service to aid debugging.

Exit the loop by selecting option `7`, at which point the session is logged out
cleanly.
