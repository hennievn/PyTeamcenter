tc_excel_app/
├─ app.py                 # Excel entry points (xlwings)
├─ tc_client_net.py       # Your Teamcenter/.NET bridge (pythonnet)
├─ config_example.json    # Optional config template
├─ requirements.txt
└─ workbook.xlsm          # Your Excel file (with xlwings add-in enabled)


Why not show the full login call here? Teamcenter .NET packaging (assembly names/namespaces and auth flow) differs between deployments and versions. I don’t want to hand you brittle code; instead, drop in the login you already use in your Pythonnet scripts. The Excel part above is fully wired and won’t change.

Wiring Excel

Install the xlwings add-in (classic) on your Windows machine (this is different from xlwings Lite).

Open workbook.xlsm and enable macros.

In the xlwings ribbon, set Run Python > Project Interpreter to your venv with xlwings & pythonnet.

Add a button on a sheet (e.g., “Items”), assign it to the macro: download_drawings_from_sheet.

Create sheets:

Items: Put the header Item ID in A1, then your IDs in A2..An.

Config: optional, set B2=server_url, B3=username, B4=password.

Log: the code will populate this automatically.