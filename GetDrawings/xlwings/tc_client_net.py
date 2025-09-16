from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# --- Pythonnet / .NET bootstrap ----------------------------------------------
TC_BIN = os.environ.get("TC_BIN")  # e.g. r"C:\Siemens\Teamcenter\soa_client\bin"
if TC_BIN and TC_BIN not in sys.path:
    sys.path.append(TC_BIN)

import clr  # type: ignore

# Load the core assemblies (names differ by packing; these are typical)
# If your site uses different assembly names, call AddReference with the DLL filename.
for asm in ("tcsoacommon", "tcsoaclient"):
    try:
        clr.AddReference(asm)
    except Exception:
        pass  # If already loaded or bundled under a different name

# --- Import .NET namespaces (PascalCase in .NET) ------------------------------
from Teamcenter.Soa.Client import Connection, FileManagementUtility  # type: ignore

# Session comes from Loose
try:
    from Teamcenter.Services.Loose.Core import SessionService  # type: ignore
except ImportError as ex:
    raise ImportError("Could not import Teamcenter.Services.Loose.Core.SessionService") from ex

# DataManagement is Strong, not Loose. Try unversioned first, then versioned.
DMServiceType = None
try:
    # Newer clients sometimes provide an unversioned strong core
    from Teamcenter.Services.Strong.Core import DataManagementService as _DM_unversioned  # type: ignore
    DMServiceType = _DM_unversioned
except Exception:
    pass

if DMServiceType is None:
    # Commonly present versioned namespace; adjust or extend as needed
    try:
        from Teamcenter.Services.Strong.Core._2008_06 import DataManagementService as _DM_2008_06  # type: ignore
        DMServiceType = _DM_2008_06
    except Exception:
        DMServiceType = None

# Final fallback: search all loaded types for a Strong/Core/*/DataManagementService
if DMServiceType is None:
    import System  # type: ignore
    assemblies = list(System.AppDomain.CurrentDomain.GetAssemblies())
    candidates = []
    for asm in assemblies:
        try:
            for t in asm.GetTypes():
                fn = t.FullName or ""
                if (fn.startswith("Teamcenter.Services.Strong.Core")
                        and fn.endswith(".DataManagementService")):
                    candidates.append(t)
        except Exception:
            continue
    # Prefer unversioned, then lowest version tag
    if candidates:
        # If both unversioned and versioned exist, unversioned usually has exactly 4 dots
        def _score(t):
            fn = t.FullName
            return (0 if fn.count(".") <= 5 else 1, fn)  # crude but effective
        candidates.sort(key=_score)
        DMServiceType = candidates[0]

if DMServiceType is None:
    raise ImportError(
        "Could not locate Teamcenter.Services.Strong.Core.*.DataManagementService. "
        "Verify your client DLLs and versioned namespace."
    )


# ------------------ DataManagement: latest revision resolvers ------------------

def _get_dm(conn) -> object:
    """Get a DataManagementService instance from Strong.Core."""
    # In .NET the service classes expose a static GetService(Connection) factory.
    get_service = getattr(DMServiceType, "GetService", None)
    if get_service is None:
        raise RuntimeError(f"{DMServiceType} does not expose static GetService(Connection).")
    return get_service(conn)


def fetch_latest_via_get_item_by_id(conn: Connection, item_id: str):
    """
    Resolve (Item, latest ItemRevision) using revId='0' semantics.
    This wires to Strong.Core DataManagementService.
    """
    dm = _get_dm(conn)

    # Prefer the canonical call if available
    if hasattr(dm, "GetItemFromId"):
        resp = dm.GetItemFromId(item_id, "0")
        # Try common shapes in a tolerant order.
        for obj in (resp, getattr(resp, "Output", None),):
            if obj is None:
                continue
            # 1) Direct properties
            for i_name, r_name in (
                ("Item", "ItemRev"),
                ("Item", "ItemRevision"),
                ("item", "itemRev"),
                ("Item", "LatestItemRevision"),
            ):
                if hasattr(obj, i_name) and hasattr(obj, r_name):
                    return getattr(obj, i_name), getattr(obj, r_name)
            # 2) Array of outputs with named fields
            try:
                if hasattr(obj, "__len__") and len(obj) > 0:
                    first = obj[0]
                    for i_name, r_name in (("Item", "ItemRev"), ("Item", "ItemRevision")):
                        if hasattr(first, i_name) and hasattr(first, r_name):
                            return getattr(first, i_name), getattr(first, r_name)
            except Exception:
                pass

        # As a pragmatic fallback, look for two modelobjects in the response whose types look like Item and ItemRevision
        mo_pairs = []
        for attr in dir(resp):
            try:
                val = getattr(resp, attr)
                # Heuristic: collect strong model objects-like
                if val is not None and hasattr(val, "GetType") and hasattr(val, "GetUid"):
                    mo_pairs.append((attr, val))
            except Exception:
                continue
        if len(mo_pairs) >= 2:
            # Last resort: return whichever two appear to be Item/ItemRevision
            mo_pairs.sort(key=lambda kv: kv[0].lower())
            return mo_pairs[0][1], mo_pairs[1][1]

        raise RuntimeError(
            "GetItemFromId(itemId,'0') returned an unexpected shape; "
            "inspect resp to map out Item/ItemRevision properties."
        )

    # If your site doesn’t expose GetItemFromId, fall back to the all‑in‑one path
    return fetch_latest_via_get_item_and_related(conn, item_id)


def fetch_latest_via_get_item_and_related(conn: Connection, item_id: str):
    """
    Resolve (Item, latest ItemRevision) in one shot using Strong.Core DataManagementService.GetItemAndRelatedObjects.
    """
    dm = _get_dm(conn)

    if not hasattr(dm, "GetItemAndRelatedObjects"):
        raise RuntimeError(
            "DataManagementService does not expose GetItemAndRelatedObjects on this client. "
            "Enable the 'fallback' path or wire GetItemFromId."
        )

    # Build the typed input using the same namespace as DM service
    ns = DMServiceType.__module__  # e.g., Teamcenter.Services.Strong.Core._2008_06
    # The input type is typically named GetItemAndRelatedObjectsInput in the same namespace
    # We resolve it reflectively to avoid spelling/version mismatches.
    import System  # type: ignore
    inp_type = None
    for asm in System.AppDomain.CurrentDomain.GetAssemblies():
        try:
            t = asm.GetType(f"{ns}.GetItemAndRelatedObjectsInput")
            if t is not None:
                inp_type = t
                break
        except Exception:
            continue
    if inp_type is None:
        raise RuntimeError(f"Could not resolve {ns}.GetItemAndRelatedObjectsInput type.")

    # Create and populate input; common properties are ItemId and RevId.
    inp = inp_type()
    if hasattr(inp, "ItemId"):
        setattr(inp, "ItemId", item_id)
    else:
        raise RuntimeError("GetItemAndRelatedObjectsInput lacks ItemId property on this client.")
    if hasattr(inp, "RevId"):
        setattr(inp, "RevId", "0")  # '0' means latest revision in standard TC services
    else:
        # Some templates use RevisionId or similar
        for alt in ("RevisionId", "Rev", "ItemRevisionId"):
            if hasattr(inp, alt):
                setattr(inp, alt, "0")
                break
        else:
            raise RuntimeError("No RevId-like property found to request 'latest' revision.")

    # Optional: request flags (site templates vary). Safe to attempt common flags.
    for flag_name in ("RequestItem", "RequestItemRevision"):
        if hasattr(inp, flag_name):
            setattr(inp, flag_name, True)

    # Call service
    res = dm.GetItemAndRelatedObjects(System.Array[System.Object]([inp]))

    # Extract the pair from the response structure (typical: res.Output[0].Item / ItemRev)
    out = getattr(res, "Output", None)
    if out is not None and len(out) > 0:
        first = out[0]
        for i_name, r_name in (("Item", "ItemRev"), ("Item", "ItemRevision")):
            if hasattr(first, i_name) and hasattr(first, r_name):
                return getattr(first, i_name), getattr(first, r_name)

    raise RuntimeError(
        "Could not locate (Item, ItemRevision) in GetItemAndRelatedObjects response; "
        "dump res.Output to see property names for your template."
    )

def find_pdf_named_references(item_rev) -> List[object]:
    candidates: List[object] = []
    for relation_prop in ["IMAN_rendering", "IMAN_reference", "fnd0Drawings"]:
        try:
            prop = item_rev.GetPropertyObject(relation_prop)
            if prop is None:
                continue
            arr = prop.GetModelObjectArrayValue()
            if arr:
                for mo in arr:
                    if mo is not None:
                        candidates.append(mo)
        except Exception:
            continue

    pdf_refs: List[object] = []
    for mo in candidates:
        try:
            name_prop = mo.GetPropertyObject("original_file_name")
            if name_prop:
                try:
                    fname = name_prop.GetStringValue()
                    if isinstance(fname, str) and fname.lower().endswith(".pdf"):
                        pdf_refs.append(mo)
                        continue
                except Exception:
                    pass

            try:
                ref_prop = mo.GetPropertyObject("IMAN_file")
                if ref_prop:
                    files = ref_prop.GetModelObjectArrayValue()
                    for f in files:
                        try:
                            oname = f.GetPropertyObject("original_file_name").GetStringValue()
                            if isinstance(oname, str) and oname.lower().endswith(".pdf"):
                                pdf_refs.append(f)
                        except Exception:
                            continue
            except Exception:
                pass
        except Exception:
            continue

    # Deduplicate by UID
    seen: set[str] = set()
    uniq: List[object] = []
    for f in pdf_refs:
        try:
            uid = f.GetUid()
        except Exception:
            uid = None
        if uid and uid not in seen:
            seen.add(uid)
            uniq.append(f)
    return uniq


def download_named_reference_to(conn: Connection, ref_obj, dest_path: Path) -> Path:
    fmu = FileManagementUtility(conn)
    fmu.GetFileToLocation(ref_obj, str(dest_path), None, None)
    return dest_path


def print_available_core_services():
    import System
    svc_types = []
    for asm in System.AppDomain.CurrentDomain.GetAssemblies():
        try:
            for t in asm.GetTypes():
                fn = t.FullName or ""
                if fn.startswith("Teamcenter.Services.") and fn.endswith("Service"):
                    svc_types.append(fn)
        except Exception:
            continue
    svc_types = sorted(set(svc_types))
    print("\n".join(svc_types))





OLD START

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
