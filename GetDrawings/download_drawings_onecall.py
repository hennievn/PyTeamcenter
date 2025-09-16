# -*- coding: utf-8 -*-
"""
Download the latest drawing (PDF) for a list of Item IDs in one service call per item.

Key points
- Uses .NET namespaces (Teamcenter.*) via pythonnet.
- Connection(host, service, environment, protocol) ctor.
- Login via Loose SessionService.
- Latest rev through Strong Core 2008_06 DataManagement:
    Prefer GetItemAndRelatedObjects(itemId, revId="0") -> (Item, ItemRevision)
    Fallback to GetItemFromId(itemId, "0") if present.
- Object Property Policy pre-loads relations/properties we need to avoid NotLoadedException.
- Downloads with FileManagementUtility.GetFileToLocation(...).

Tested structure-wise against the SDK shape; depending on your site template,
you may tweak the relation names in POLICY_REL_PROPS or dataset/file property names.
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

# --------------------------------------------------------------------------------------
# Pythonnet bootstrap: make sure Teamcenter client DLLs are reachable
# --------------------------------------------------------------------------------------
TC_BIN = os.environ.get("TC_BIN")  # e.g. r"C:\Siemens\Teamcenter\soa_client\bin"
if TC_BIN and TC_BIN not in sys.path:
    sys.path.append(TC_BIN)

import clr  # type: ignore

# Required Teamcenter .NET assemblies (names align with Siemens redistributables)
# If your assembly names differ, adjust accordingly.
clr.AddReference("tcsoacommon")
clr.AddReference("tcsoaclient")

# --------------------------------------------------------------------------------------
# .NET / Teamcenter imports (use .NET casing for namespaces)
# --------------------------------------------------------------------------------------
from System import Array, String  # type: ignore

# Core SOA client & common
from Teamcenter.Soa import SoaConstants  # type: ignore
from Teamcenter.Soa.Client import Connection  # type: ignore
from Teamcenter.Soa.Client import DefaultExceptionHandler, ResponseExceptionHandler  # type: ignore
from Teamcenter.Soa.Client import FileManagementUtility  # type: ignore
from Teamcenter.Soa.Common import ObjectPropertyPolicy, PolicyType, PolicyProperty  # type: ignore

# ModelObject API (used for property access)
from Teamcenter.Soa.Client.Model import ModelObject  # type: ignore

# Loose SessionService for login
# (The unversioned Loose SessionService is common; fall back to versioned if needed.)
try:
    from Teamcenter.Services.Loose.Core import SessionService  # type: ignore
except Exception:
    from Teamcenter.Services.Loose.Core._2006_03 import Session as SessionService  # type: ignore


# --------------------------------------------------------------------------------------
# Strong DataManagement resolver (prefer Strong Core 2008_06)
# --------------------------------------------------------------------------------------
def resolve_dm_namespace():
    """
    Try to import Strong Core 2008_06 DataManagement first, then common fallbacks.
    Returns (module, service_class) where service_class exposes GetService(conn).
    """
    try:
        # Typical modern strong namespace for DataManagement:
        from Teamcenter.Services.Strong.Core._2008_06 import DataManagement as DM  # type: ignore
        return DM, DM.DataManagementService
    except Exception:
        pass

    # Some sites also expose an unversioned Strong.Core facade:
    try:
        from Teamcenter.Services.Strong.Core import DataManagement as DM  # type: ignore
        return DM, DM.DataManagementService
    except Exception:
        pass

    # As a last resort: some deployments also wire DataManagement under Loose Core (rare).
    try:
        from Teamcenter.Services.Loose.Core._2008_06 import DataManagement as DM  # type: ignore
        return DM, DM.DataManagementService
    except Exception:
        pass

    raise ImportError(
        "Could not resolve a DataManagement service under Strong.Core (_2008_06 or unversioned). "
        "Confirm your Teamcenter client libraries and namespaces."
    )


DM_ns, DMService = resolve_dm_namespace()


# --------------------------------------------------------------------------------------
# Typed config and results
# --------------------------------------------------------------------------------------
@dataclass(frozen=True)
class TcLogin:
    host: str                 # e.g. "http://your-tc-server/tc"
    service: str              # e.g. "soa" or site-specific app name
    environment: str          # TCCS environment name (e.g. "TCCS_DEV") or empty for direct
    protocol: str = "HTTP"    # "HTTP" or "IIOP" (SoaConstants)
    user: str = ""
    password: str = ""
    group: str = "dba"
    role: str = "dba"
    locale: str = "en_US"
    session_discriminator: str = ""


@dataclass(frozen=True)
class DrawingHit:
    item_id: str
    rev_id: str
    item_uid: str
    itemrev_uid: str
    file_uid: str
    saved_to: Path


# --------------------------------------------------------------------------------------
# Connection + session
# --------------------------------------------------------------------------------------
def connect_and_login(cfg: TcLogin) -> Connection:
    """
    Create a Teamcenter connection using the 4-arg ctor and log in via SessionService.
    """
    proto = getattr(SoaConstants, cfg.protocol.upper(), SoaConstants.HTTP)
    conn = Connection(cfg.host, cfg.service, cfg.environment, proto)

    # Exception handler is required by the client; defaults are fine for scripts
    conn.SetExceptionHandler(ResponseExceptionHandler(DefaultExceptionHandler()))

    # Optional app tagging (shows up server-side in request envelope)
    conn.SetApplicationName("download_drawings_onecall.py")
    conn.SetApplicationVersion("1.0")

    # Login (non-SSO path). For SSO, use SessionService.LoginSSO.
    sess = SessionService.GetService(conn)
    # Signature in C# samples: Login(user, password, group, role, locale, discriminator)
    sess.Login(cfg.user, cfg.password, cfg.group, cfg.role, cfg.locale, cfg.session_discriminator)
    return conn


# --------------------------------------------------------------------------------------
# Object Property Policy (OPP)
# --------------------------------------------------------------------------------------
# Relations we want preloaded off ItemRevision to find drawings:
POLICY_REL_PROPS = ("IMAN_rendering", "IMAN_reference", "fnd0Drawings")

def install_policy_for_drawings(conn: Connection) -> None:
    """
    Minimal policy that:
      - On ItemRevision: brings in drawing relations + revision ID.
      - On Dataset: brings in file-named references.
      - On ImanFile: original file name (for naming), and allow download tickets to resolve.
    This avoids NotLoadedException when reading ModelObject properties. See SDK notes on
    property access and NotLoadedException via ModelObject getters.  
    """
    policy = ObjectPropertyPolicy()

    t_itemrev = PolicyType("ItemRevision", None)
    t_itemrev.AddProperty(PolicyProperty("item_revision_id"))
    for rel in POLICY_REL_PROPS:
        t_itemrev.AddProperty(PolicyProperty(rel))
    policy.AddType(t_itemrev)

    t_dataset = PolicyType("Dataset", None)
    t_dataset.AddProperty(PolicyProperty("IMAN_file"))
    t_dataset.AddProperty(PolicyProperty("object_type"))
    policy.AddType(t_dataset)

    # Some sites use "ImanFile", others "ImanFile" (class, not type) is fine in policy.
    t_file = PolicyType("ImanFile", None)
    t_file.AddProperty(PolicyProperty("original_file_name"))
    # FMS tickets are usually resolved automatically by FileManagementUtility, but no harm:
    t_file.AddProperty(PolicyProperty("fms_ticket"))
    t_file.AddProperty(PolicyProperty("fms_tickets"))
    policy.AddType(t_file)

    # Install policy on the current thread (or globally, depending on your style).
    # setPolicy / setPolicyPerThread routes are exposed by the ObjectPropertyPolicyManager. 
    conn.GetObjectPropertyPolicyManager().SetPolicy(policy)


# --------------------------------------------------------------------------------------
# DataManagement: get latest revision in ONE call (prefer GetItemAndRelatedObjects)
# --------------------------------------------------------------------------------------
def _set_attr_anycase(obj, name: str, value) -> bool:
    """Try both lowerCamel and PascalCase on a property; return True if set."""
    if hasattr(obj, name):
        setattr(obj, name, value)
        return True
    alt = name[0].upper() + name[1:]
    if hasattr(obj, alt):
        setattr(obj, alt, value)
        return True
    return False


def resolve_latest_item_and_rev(conn: Connection, item_id: str) -> Tuple[ModelObject, ModelObject]:
    """
    Try Strong DM GetItemAndRelatedObjects(itemId, revId="0").
    If not available, fall back to GetItemFromId(itemId, "0").
    Returns (Item, ItemRevision) as ModelObject instances.
    """
    dm = DMService.GetService(conn)

    # 1) Prefer GetItemAndRelatedObjects
    #    Build the *versioned* input structure reflectively to avoid namespace drift.
    #    Typical types: GetItemAndRelatedObjectsInput[], with .itemId and .revId
    try:
        # Resolve input type from the same module
        try:
            GIAROInput = DM_ns.GetItemAndRelatedObjectsInput  # type: ignore[attr-defined]
        except Exception:
            # Some kits nest inputs under a "Types" class/namespace; try attribute walk:
            GIAROInput = getattr(DM_ns, "GetItemAndRelatedObjectsInput", None)
            if GIAROInput is None:
                raise AttributeError

        arr = Array  # typed .NET array
        inp = GIAROInput()
        if not _set_attr_anycase(inp, "itemId", item_id):
            raise AttributeError("GetItemAndRelatedObjectsInput.itemId not found")
        # "0" => latest revision (server semantics)
        _set_attr_anycase(inp, "revId", "0")

        # Optionally ask for extra info flags if present (not required when OPP is set)
        for flag_name in ("info", "infoFlags"):
            if hasattr(inp, flag_name):
                info = getattr(inp, flag_name)
                # When info is a struct/class, you may set booleans like includeItem/ItemRev/Relations.
                # We'll be conservative; OPP already asks for relations we need.
                try:
                    _set_attr_anycase(info, "includeItem", True)
                    _set_attr_anycase(info, "includeItemRev", True)
                except Exception:
                    pass
                break

        arr[0] = inp

        # Call service (handle both PascalCase and lowerCamel)
        if hasattr(dm, "GetItemAndRelatedObjects"):
            resp = dm.GetItemAndRelatedObjects(arr)
        else:
            resp = getattr(dm, "getItemAndRelatedObjects")(arr)

        # Typical shape: resp.Output[0].Item, resp.Output[0].ItemRev (names may vary slightly)
        out0 = getattr(resp, "Output", None) or getattr(resp, "output", None)
        if out0 is None or out0.Length == 0:
            raise RuntimeError("Empty GetItemAndRelatedObjects response")

        row0 = out0[0]
        item = getattr(row0, "Item", None) or getattr(row0, "item", None)
        itemrev = getattr(row0, "ItemRev", None) or getattr(row0, "itemRev", None)
        if item is None or itemrev is None:
            raise RuntimeError("Response did not include item and itemRev")

        return item, itemrev

    except Exception as ex_giaro:
        # 2) Fallback: GetItemFromId(itemId, "0")
        try:
            if hasattr(dm, "GetItemFromId"):
                resp = dm.GetItemFromId(item_id, "0")
            else:
                resp = getattr(dm, "getItemFromId")(item_id, "0")

            # Common response containers (adapt defensively)
            # Many servers return a small structure with .Item and .ItemRev;
            # others may return Servicedata-like content we can peel from.
            item = getattr(resp, "Item", None) or getattr(resp, "item", None)
            itemrev = getattr(resp, "ItemRev", None) or getattr(resp, "itemRev", None)

            if item is not None and itemrev is not None:
                return item, itemrev

            # Attempt to recover from servicedata if provided
            sd = getattr(resp, "ServiceData", None) or getattr(resp, "serviceData", None)
            if sd is not None and sd.SizeOfPlainObjects() > 0:
                # Heuristic: first two plain objects are often item, itemrev.
                mo0 = sd.GetPlainObject(0)
                mo1 = sd.GetPlainObject(1) if sd.SizeOfPlainObjects() > 1 else None
                # Decide which is which by type string if available
                mo0_type = mo0.GetTypeObject().GetName() if mo0 is not None else ""
                mo1_type = mo1.GetTypeObject().GetName() if mo1 is not None else ""
                if "ItemRevision" in (mo0_type or "") or "ItemRevision" in (mo1_type or ""):
                    itemrev = mo0 if "ItemRevision" in (mo0_type or "") else mo1
                    item = mo1 if itemrev is mo0 else mo0
                    if item is not None and itemrev is not None:
                        return item, itemrev

            raise RuntimeError("GetItemFromId did not yield (Item, ItemRevision).")
        except Exception as ex_gifi:
            raise RuntimeError(
                f"Could not resolve latest revision for '{item_id}'. "
                f"GetItemAndRelatedObjects error: {ex_giaro} | "
                f"GetItemFromId('0') error: {ex_gifi}"
            ) from ex_gifi


# --------------------------------------------------------------------------------------
# Discover PDF named references on an ItemRevision
# --------------------------------------------------------------------------------------
def _safe_get_string(mo: ModelObject, prop: str) -> Optional[str]:
    try:
        po = mo.GetPropertyObject(prop)
        return po.GetStringValue()
    except Exception:
        return None


def _safe_get_array(mo: ModelObject, prop: str) -> List[ModelObject]:
    try:
        po = mo.GetPropertyObject(prop)
        arr = po.GetModelObjectArrayValue()
        return [x for x in arr or [] if x is not None]
    except Exception:
        return []


def find_pdf_refs(itemrev: ModelObject) -> List[ModelObject]:
    """
    Collect file ModelObjects that are PDFs via:
      - ItemRevision -> IMAN_rendering / IMAN_reference / fnd0Drawings
      - Dataset -> IMAN_file -> ImanFile objects
      - Direct ImanFile references (rare)
    Model property access follows the ModelObject API (GetPropertyObject, etc.); if a
    property was not included by OPP, a NotLoadedException may be raised.  
    """
    datasets_or_files: List[ModelObject] = []
    for rel in POLICY_REL_PROPS:
        datasets_or_files.extend(_safe_get_array(itemrev, rel))

    file_mos: List[ModelObject] = []

    for mo in datasets_or_files:
        # Case 1: mo is already an ImanFile with a name
        fname = _safe_get_string(mo, "original_file_name")
        if fname and fname.lower().endswith(".pdf"):
            file_mos.append(mo)
            continue

        # Case 2: mo is a Dataset; get its IMAN_file refs
        for f in _safe_get_array(mo, "IMAN_file"):
            oname = _safe_get_string(f, "original_file_name")
            if oname and oname.lower().endswith(".pdf"):
                file_mos.append(f)

    # Deduplicate by UID (GetUid in .NET) / getUid in Java; handle both
    uniq: List[ModelObject] = []
    seen = set()
    for f in file_mos:
        try:
            uid = f.GetUid() if hasattr(f, "GetUid") else f.getUid()
        except Exception:
            uid = None
        if uid and uid not in seen:
            seen.add(uid)
            uniq.append(f)

    return uniq


# --------------------------------------------------------------------------------------
# Download
# --------------------------------------------------------------------------------------
def download_to(conn: Connection, file_obj: ModelObject, destination: Path) -> Path:
    """
    Use FileManagementUtility.GetFileToLocation to download a single file MO to a path.
    FileManagementUtility supports both single-ticket and MO-based downloads. :contentReference[oaicite:9]{index=9}
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    fmu = FileManagementUtility(conn)
    # GetFileToLocation(modelObject, path, progressCb, userData)
    fmu.GetFileToLocation(file_obj, str(destination), None, None)
    return destination


# --------------------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------------------
def iter_item_ids(csv_path: Path) -> Iterable[str]:
    with csv_path.open(newline="", encoding="utf-8") as f:
        for row in csv.reader(f):
            if not row:
                continue
            val = row[0].strip()
            if val:
                yield val


def run(csv_path: Path, out_dir: Path, cfg: TcLogin) -> List[DrawingHit]:
    out_dir.mkdir(parents=True, exist_ok=True)

    conn = connect_and_login(cfg)
    install_policy_for_drawings(conn)

    dm_results: List[DrawingHit] = []

    for item_id in iter_item_ids(csv_path):
        item, itemrev = resolve_latest_item_and_rev(conn, item_id)

        # Friendly revision id (falls back to 'LATEST' if not available)
        try:
            rev_id = _safe_get_string(itemrev, "item_revision_id") or "LATEST"
        except Exception:
            rev_id = "LATEST"

        pdf_refs = find_pdf_refs(itemrev)
        if not pdf_refs:
            print(f"[warn] No PDF found for {item_id} ({rev_id})")
            continue

        for file_mo in pdf_refs:
            fname = _safe_get_string(file_mo, "original_file_name") or f"{item_id}_{rev_id}.pdf"
            dest = out_dir / fname
            try:
                download_to(conn, file_mo, dest)
                hit = DrawingHit(
                    item_id=item_id,
                    rev_id=rev_id,
                    item_uid=(item.GetUid() if hasattr(item, "GetUid") else item.getUid()),
                    itemrev_uid=(itemrev.GetUid() if hasattr(itemrev, "GetUid") else itemrev.getUid()),
                    file_uid=(file_mo.GetUid() if hasattr(file_mo, "GetUid") else file_mo.getUid()),
                    saved_to=dest,
                )
                dm_results.append(hit)
                print(f"[ok] {item_id} ({rev_id}) -> {dest}")
            except Exception as ex:
                print(f"[warn] Download failed for {item_id} ({rev_id}): {ex}")

    return dm_results


# --------------------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser(description="Download latest drawing PDFs (one-call lookup).")
    ap.add_argument("csv", type=Path, help="Path to single-column CSV with Item IDs")
    ap.add_argument("-o", "--out", type=Path, default=Path("downloads"), help="Download directory")

    ap.add_argument("--host", required=True, help="Teamcenter host (e.g. http://server/tc)")
    ap.add_argument("--service", default="soa", help="Service/application name (e.g. 'soa')")
    ap.add_argument("--env", default="", help="TCCS environment name (e.g. 'TCCS_DEV'); empty for direct")
    ap.add_argument("--protocol", default="HTTP", choices=["HTTP", "IIOP"], help="Transport protocol")

    ap.add_argument("-u", "--user", required=True)
    ap.add_argument("-p", "--password", required=True)
    ap.add_argument("--group", default="dba")
    ap.add_argument("--role", default="dba")
    ap.add_argument("--locale", default="en_US")
    ap.add_argument("--session", default="")

    args = ap.parse_args()

    cfg = TcLogin(
        host=args.host,
        service=args.service,
        environment=args.env,
        protocol=args.protocol,
        user=args.user,
        password=args.password,
        group=args.group,
        role=args.role,
        locale=args.locale,
        session_discriminator=args.session,
    )

    hits = run(args.csv, args.out, cfg)
    print(f"\nDone. Downloaded {len(hits)} file(s) to {args.out.resolve()}")
    for h in hits:
        print(f" - {h.item_id} {h.rev_id} -> {h.saved_to}")


if __name__ == "__main__":
    main()
