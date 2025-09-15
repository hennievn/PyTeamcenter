from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# --- pythonnet/bootstrap -----------------------------------------------------
import clr  # type: ignore[import-not-found]

# 1) Make sure your TC .NET client assemblies are on sys.path:
#    e.g., r"C:\Siemens\Teamcenter\install\soa_client\dotnet", adjust as needed.
ASSEMBLY_DIRS = [
    os.environ.get("TC_NET_ASM", ""),   # allow override
]
for d in ASSEMBLY_DIRS:
    if d and d not in sys.path:
        sys.path.append(d)

# 2) Load the assemblies you actually have (names can differ by version).
#    Adjust these if AddReference fails and use the names from your bin folder.
clr.AddReference("Teamcenter.Soa.Client")
clr.AddReference("Teamcenter.Services.Core")
clr.AddReference("Teamcenter.Services.Strong.Core")
clr.AddReference("Teamcenter.Fms.Client")  # for FileManagementUtility

# --- Imports from .NET (names may vary across versions) ----------------------
# NAMESPACE NOTE:
# The namespaces below follow common TC .NET layouts. If an import fails,
# open Object Browser (ILDASM/dotPeek) and adjust.
from System import Array, String  # type: ignore
from System import Convert  # type: ignore

from Teamcenter.Soa.Client import Connection  # type: ignore
from Teamcenter.Soa.Client import Model  # type: ignore
from Teamcenter.Soa.Client.FileManagement import FileManagementUtility  # type: ignore

from Teamcenter.Services.Strong.Core import DataManagementService  # type: ignore
from Teamcenter.Services.Core._2008_06.DataManagement import (  # type: ignore
    GetItemAndRelatedObjectsInputData,
)

# You may need additional namespaces for credentials, object property policy, etc.


@dataclass
class TeamcenterClient:
    server_url: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None

    @contextmanager
    def session(self) -> "TeamcenterSession":
        sess = TeamcenterSession(
            server_url=self.server_url,
            username=self.username,
            password=self.password,
        )
        try:
            sess.login()
            yield sess
        finally:
            sess.logout()


class TeamcenterSession:
    """Holds the .NET Connection and services while logged in."""

    def __init__(
        self,
        server_url: Optional[str],
        username: Optional[str],
        password: Optional[str],
    ) -> None:
        self.server_url = server_url or os.environ.get("TC_SERVER_URL", "")
        self.username = username or os.environ.get("TC_USERNAME", "")
        self.password = password or os.environ.get("TC_PASSWORD", "")
        self._conn: Optional[Connection] = None
        self._dms: Optional[DataManagementService] = None
        self._fmu: Optional[FileManagementUtility] = None

    # --- lifecycle -----------------------------------------------------------
    def login(self) -> None:
        # NOTE: exact login wiring depends on your CredentialManager choice.
        # Many teams wrap this in a helper; reuse your working code here.
        if not self.server_url:
            raise RuntimeError("Missing server_url")

        # Example (adjust to your environment):
        # self._conn = Connection(self.server_url, MyCredentialManager(self.username, self.password))
        # ModelObject factory init is often required before Strong services:
        # Model.StrongObjectFactoryXXXX.Init()
        #
        # For clarity and safety, call your proven login helper instead:
        self._conn = self._dotnet_login(self.server_url, self.username, self.password)
        self._dms = DataManagementService.GetService(self._conn)
        self._fmu = FileManagementUtility(self._conn)

    def logout(self) -> None:
        if self._conn is not None:
            try:
                self._conn.Logout()
            finally:
                self._conn = None

    # --- public API ----------------------------------------------------------
    def download_latest_pdf_for_item(self, item_id: str, dest_dir: Path) -> Path:
        """
        1) Resolve the Item (latest revision using your '0' rule).
        2) Resolve the drawing dataset for that revision (PDF).
        3) Download via FMU and return the local path.
        """
        if not self._conn or not self._dms or not self._fmu:
            raise RuntimeError("Not logged in")

        # --- 1) Get Item + latest revision in one go -------------------------
        # The following mirrors the classic GetItemAndRelatedObjects usage.
        # If you prefer GetItemById("0") semantics on the revision field,
        # plug in your existing implementation here.

        inp = GetItemAndRelatedObjectsInputData()
        # Typical fields (verify exact property names on your version):
        inp.item = item_id
        inp.revisionId = "0"  # << '0' = latest revision per your rule
        inp.includeWorkflow = False
        inp.includeAttachments = True

        resp = self._dms.GetItemAndRelatedObjects(Array[GetItemAndRelatedObjectsInputData]([inp]))
        if resp.serviceData.sizeOfPartialErrors() > 0:
            # surface the first error message
            es = resp.serviceData.GetPartialError(0)
            raise RuntimeError("; ".join([ev.GetMessages()[0] for ev in es.GetErrorValues()]))

        # Extract the ItemRevision (adjust according to the response shape).
        item_rev = self._first_revision_from(resp)  # implement helper below

        # --- 2) Find the drawing dataset (PDF) -------------------------------
        pdf_dataset = self._pick_pdf_dataset(item_rev)  # implement helper below
        if pdf_dataset is None:
            raise FileNotFoundError(f"No PDF drawing dataset found for {item_id}")

        # --- 3) Download via FMU ---------------------------------------------
        dest_dir.mkdir(parents=True, exist_ok=True)
        file_resp = self._fmu.GetFileToLocation(pdf_dataset, str(dest_dir), None, None)
        # Return the first file’s path:
        files = file_resp.GetFiles()
        if files is None or files.Length == 0:
            raise RuntimeError(f"FMU returned no files for {item_id}")
        return Path(str(files[0].GetLocalFileName()))

    # --- helpers (you will adapt these to your TC schema) --------------------
    def _first_revision_from(self, resp) -> Model.ModelObject:
        """Pull the ItemRevision from DMS response in your version’s shape."""
        # Many orgs access resp.output[0].itemRev or similar; adjust as needed.
        try:
            return resp.output[0].itemRev
        except Exception as ex:  # noqa: BLE001
            raise RuntimeError(f"Cannot locate ItemRevision in response: {ex}")

    def _pick_pdf_dataset(self, item_rev) -> Optional[Model.ModelObject]:
        """Return the drawing dataset that is a PDF (by type or named reference)."""
        # Strategies vary: IMAN_rendering, fnd0Drawings, or a custom relation.
        # If your org uses IMAN_rendering with a named ref 'PDF', filter that.
        try:
            # Example; replace with your proven logic:
            renderings = item_rev.Get_iman_rendering()
            for ds in renderings:
                # Check dataset’s type or file refs to pick a PDF
                if "PDF" in ds.Get_object_type().ToUpper():
                    return ds
        except Exception:
            pass
        return None

    # --- place for your proven login implementation -------------------------
    def _dotnet_login(self, url: str, user: str, pwd: str) -> Connection:
        """
        Plug in your standard .NET login here (CredentialManager, SSO, etc.).
        Returning a connected Teamcenter.Soa.Client.Connection is enough.
        """
        raise NotImplementedError(
            "Wire your existing .NET login here: Connection(url, CredentialManager(user, pwd))"
        )
