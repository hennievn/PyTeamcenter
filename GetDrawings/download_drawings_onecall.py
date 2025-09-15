# fetch_drawings.py
from __future__ import annotations

import argparse
import csv
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, List, Optional, Sequence, Tuple, Protocol, Dict

# --- Pythonnet / .NET bootstrap ------------------------------------------------
# 1) Ensure Teamcenter client DLLs are discoverable.
#    Typically this includes tcsoaclient.dll, tcsoacommon.dll and your site strong model DLLs.
#    Append the TC client bin folder to sys.path *before* adding references.
TC_BIN = os.environ.get("TC_BIN")  # e.g. r"C:\Siemens\Teamcenter\soa_client\bin"
if TC_BIN and TC_BIN not in sys.path:
    sys.path.append(TC_BIN)

import clr  # type: ignore

# Add references to required Teamcenter .NET assemblies
# If your DLL names differ, adjust here.
clr.AddReference("tcsoacommon")
clr.AddReference("tcsoaclient")

# --- Import .NET namespaces (note: Teamcenter uses lower-case namespaces) -----
# Connection + model
from teamcenter.soa.client import Connection  # type: ignore
from teamcenter.soa.client.model import ModelObject  # type: ignore
from teamcenter.soa.client import FileManagementUtility  # type: ignore

# Session + services (loose)
from teamcenter.services.loose.core import SessionService  # type: ignore
# Some deployments expose a versioned namespace for DataManagement:
# e.g., teamcenter.services.loose.core._2008_06.datamanagement
try:
    from teamcenter.services.loose.core import DataManagementService  # type: ignore
    HAS_UNVERSIONED_DM = True
except Exception:
    HAS_UNVERSIONED_DM = False
    # Try common versioned namespace (adjust if your site uses a different one)
    from teamcenter.services.loose.core._2008_06 import datamanagement as dm_v2008  # type: ignore


# ---------- Typed configuration / results -------------------------------------

@dataclass(frozen=True)
class TcLogin:
    host: str                 # e.g. "http://your-tc-server/tc"
    user: str
    password: str
    group: str = "dba"
    role: str = "dba"
    locale: str = "en_US"
    session_discriminator: str = ""  # empty/constant/unique per your sharing needs


@dataclass(frozen=True)
class DrawingHit:
    item_id: str
    item_rev_id: str
    item_uid: str
    item_rev_uid: str
    dataset_uid: str
    file_local_path: Path


class LatestRevisionFetcher(Protocol):
    """Strategy to resolve latest Item + ItemRevision for a given item_id."""
    def __call__(self, conn: Connection, item_id: str) -> Tuple[ModelObject, ModelObject]:
        """
        Return (item, item_revision) for the latest revision.
        Should raise RuntimeError with a clear message on failure.
        """
        ...


# ---------------- Session, policy, and login helpers --------------------------

def connect_and_login(cfg: TcLogin) -> Tuple[Connection, SessionService]:
    """
    Create a connection and log in the user.
    """
    conn = Connection(cfg.host)
    sess = SessionService.getService(conn)  # factory method pattern

    # Standard login (non-SSO). For SSO, use sess.loginSSO(...)
    # sessiondiscriminator controls server instance sharing; see Teamcenter docs.
    sess.login(cfg.user, cfg.password, cfg.group, cfg.role, cfg.locale, cfg.session_discriminator)
    return conn, sess


def build_object_property_policy_for_drawings(conn: Connection) -> None:
    """
    Keep payloads small but include the bits we need:
    - On ItemRevision: properties that expose relations to drawings/datasets.
    - On Dataset: type and named references (IMAN_file / rendering / etc.).
    - On ImanFile (named reference objects): original file name/path tickets.

    This is intentionally minimal; add or remove props to fit your data model.
    """
    # Using the client-side policy manager is typical, but the exact API is verbose in Python.
    # Start without a custom OPP; add one if you see NotLoadedException on any property access.
    # See Teamcenter's object property policy docs; the Connection exposes a policy manager.
    # conn.getObjectPropertyPolicyManager().setPolicy(policy)
    pass


# ------------------ DataManagement: latest revision resolvers ------------------

def fetch_latest_via_get_item_by_id(conn: Connection, item_id: str) -> Tuple[ModelObject, ModelObject]:
    """
    Resolve (Item, latest ItemRevision) using 'revId = "0"' semantics.
    Adjust the exact call to match your server's DataManagementService signature.
    """
    # Get the service
    dm = (DataManagementService.getService(conn) if HAS_UNVERSIONED_DM
          else dm_v2008.DataManagementService.getService(conn))  # type: ignore

    # --- IMPORTANT ---
    # Your site’s DataManagement service may expose any of:
    #   getItemById(itemId: string)
    #   getItemAndRelatedObjects(inputs: GetItemAndRelatedObjectsInput[])
    #   getItemFromId(itemId: string, revId: string)  <-- common
    #
    # Many deployments accept revId="0" to mean "latest".
    #
    # Replace the following placeholder with the exact method your site uses:
    try:
        # Example pattern: item + itemRev returned in a response structure
        # resp = dm.getItemFromId(item_id, "0")  # <-- adjust for your API
        # Below we raise to force you to wire in the specific call.
        raise NotImplementedError("Wire this to your site's DataManagementService call, e.g. getItemFromId(item_id, '0').")
    except Exception as ex:
        raise RuntimeError(f"Failed to resolve latest revision for item '{item_id}': {ex}") from ex


def fetch_latest_via_get_item_and_related(conn: Connection, item_id: str) -> Tuple[ModelObject, ModelObject]:
    """
    Resolve (Item, latest ItemRevision) in one go via GetItemAndRelatedObjects.
    """
    dm = (DataManagementService.getService(conn) if HAS_UNVERSIONED_DM
          else dm_v2008.DataManagementService.getService(conn))  # type: ignore

    try:
        # Typical outline (names can differ by version/template):
        #   inputs = Array
        #   inp = GetItemAndRelatedObjectsInput()
        #   inp.itemId = item_id
        #   inp.revId  = "0"  # latest
        #   inp.infoFlags = ...  # request item, itemRev, and specific relations
        #   inputs[0] = inp
        #   resp = dm.getItemAndRelatedObjects(inputs)
        #   item     = resp.output[0].item
        #   item_rev = resp.output[0].itemRev
        #
        # Replace with your exact types and property names; raise for wiring step.
        raise NotImplementedError("Wire this to getItemAndRelatedObjects(...) for your versioned namespace.")
    except Exception as ex:
        raise RuntimeError(f"GetItemAndRelatedObjects failed for '{item_id}': {ex}") from ex


# --------------------------- Drawing discovery --------------------------------

def find_pdf_named_references(item_rev: ModelObject) -> List[ModelObject]:
    """
    Given an ItemRevision, return the .NET ModelObjects that represent the file
    named references we want to download (PDFs). We check common relations.
    """
    # Strategies (keep both; your data model will make at least one true):
    candidates: List[ModelObject] = []

    # Strong-model convenience accessors differ by template; fall back to generic property access
    # Try a few well-known relations first; if a NotLoadedException appears, add OPP or try others.
    for relation_prop in [
        "IMAN_rendering",     # many sites attach PDFs as renderings of the revision
        "IMAN_reference",     # sometimes PDFs are held as general references
        "fnd0Drawings",       # configurable drawings relation
    ]:
        try:
            prop = item_rev.getPropertyObject(relation_prop)  # type: ignore
            if prop is None:
                continue
            # This may trigger a server fetch unless OPP included it
            arr = prop.getModelObjectArrayValue()  # type: ignore
            if arr:
                for mo in arr:
                    if mo is not None:
                        candidates.append(mo)
        except Exception:
            # Property missing or not loaded; continue trying others
            continue

    # Filter to dataset named references or files that look like PDFs
    pdf_refs: List[ModelObject] = []
    for mo in candidates:
        try:
            # If mo is a Dataset, try to gather its file references
            # Otherwise, mo could already be an ImanFile. Check original file name.
            # Try to read a couple of common properties without being brittle:
            #   - original_file_name on ImanFile
            #   - object_type / type name on Dataset
            name_prop = getattr(mo, "getPropertyObject")("original_file_name")  # type: ignore
            if name_prop:
                try:
                    fname = name_prop.getStringValue()  # type: ignore
                    if isinstance(fname, str) and fname.lower().endswith(".pdf"):
                        pdf_refs.append(mo)  # it’s an ImanFile for a PDF
                        continue
                except Exception:
                    pass

            # Dataset path: pull its IMAN_file references and inspect
            try:
                ref_prop = mo.getPropertyObject("IMAN_file")  # type: ignore
                if ref_prop:
                    files = ref_prop.getModelObjectArrayValue()  # type: ignore
                    for f in files:
                        try:
                            oname = f.getPropertyObject("original_file_name").getStringValue()  # type: ignore
                            if isinstance(oname, str) and oname.lower().endswith(".pdf"):
                                pdf_refs.append(f)
                        except Exception:
                            continue
            except Exception:
                # Not a dataset with IMAN_file; skip
                pass
        except Exception:
            continue

    # Deduplicate by UID if possible
    seen: set[str] = set()
    uniq: List[ModelObject] = []
    for f in pdf_refs:
        try:
            uid = f.getUid()  # type: ignore
        except Exception:
            uid = None
        if uid and uid not in seen:
            seen.add(uid)
            uniq.append(f)

    return uniq


# ------------------------------ Downloads -------------------------------------

def download_named_reference_to(
    conn: Connection,
    ref_obj: ModelObject,
    dest_path: Path,
) -> Path:
    """
    Use FileManagementUtility to download a single named reference to a destination path.
    """
    fmu = FileManagementUtility(conn)
    # Use getFileToLocation when you want precise control of the saved path.
    # (There are also getFiles(...) overloads that return a response object.)
    # See: filemanagementutility.getFileToLocation(modelobject, string, ...) in the API.
    fmu.getFileToLocation(ref_obj, str(dest_path), None, None)  # progress callback omitted
    return dest_path


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


# ------------------------------- Orchestration --------------------------------

def run(
    csv_path: Path,
    download_dir: Path,
    cfg: TcLogin,
    prefer_all_in_one: bool = True,
) -> List[DrawingHit]:
    ensure_dir(download_dir)

    conn, _sess = connect_and_login(cfg)
    build_object_property_policy_for_drawings(conn)

    # Select fetcher
    fetcher: LatestRevisionFetcher = (
        fetch_latest_via_get_item_and_related if prefer_all_in_one
        else fetch_latest_via_get_item_by_id
    )

    results: List[DrawingHit] = []

    for item_id in iter_item_ids(csv_path):
        item, item_rev = fetcher(conn, item_id)

        # Extract a user-friendly rev ID if available; fall back to UID-based naming
        try:
            rev_id = item_rev.getPropertyObject("item_revision_id").getStringValue()  # type: ignore
        except Exception:
            rev_id = "LATEST"

        # Find PDFs
        pdf_refs = find_pdf_named_references(item_rev)
        if not pdf_refs:
            print(f"[warn] No PDF drawing found for {item_id} ({rev_id})")
            continue

        # Download all PDFs we found for this revision
        for nr in pdf_refs:
            try:
                # Attempt to derive a good filename
                try:
                    base_name = nr.getPropertyObject("original_file_name").getStringValue()  # type: ignore
                except Exception:
                    base_name = f"{item_id}_{rev_id}.pdf"

                dest = download_dir / base_name
                download_named_reference_to(conn, nr, dest)

                results.append(
                    DrawingHit(
                        item_id=item_id,
                        item_rev_id=str(rev_id),
                        item_uid=item.getUid(),           # type: ignore
                        item_rev_uid=item_rev.getUid(),  # type: ignore
                        dataset_uid=getattr(nr, "getUid")(),  # type: ignore
                        file_local_path=dest,
                    )
                )
            except Exception as ex:
                print(f"[warn] Failed to download PDF for {item_id} ({rev_id}): {ex}")

    return results


def iter_item_ids(csv_path: Path) -> Iterable[str]:
    with csv_path.open(newline="", encoding="utf-8") as f:
        for row in csv.reader(f):
            if not row:
                continue
            yield row[0].strip()


# ---------------------------------- CLI ---------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description="Download latest drawing PDFs for item IDs.")
    ap.add_argument("csv", type=Path, help="Path to single-column CSV with item IDs")
    ap.add_argument("-o", "--out", type=Path, default=Path("downloads"), help="Download directory")
    ap.add_argument("--host", required=True, help="Teamcenter host URL (e.g. http://server/tc)")
    ap.add_argument("-u", "--user", required=True)
    ap.add_argument("-p", "--password", required=True)
    ap.add_argument("--group", default="dba")
    ap.add_argument("--role", default="dba")
    ap.add_argument("--locale", default="en_US")
    ap.add_argument("--session", default="")
    ap.add_argument("--fallback", action="store_true",
                    help="Use the getItemById('0') path instead of GetItemAndRelatedObjects.")
    args = ap.parse_args()

    cfg = TcLogin(
        host=args.host,
        user=args.user,
        password=args.password,
        group=args.group,
        role=args.role,
        locale=args.locale,
        session_discriminator=args.session,
    )
    results = run(
        csv_path=args.csv,
        download_dir=args.out,
        cfg=cfg,
        prefer_all_in_one=not args.fallback,
    )

    print(f"\nCompleted: downloaded {len(results)} file(s) to {args.out.resolve()}")
    for r in results:
        print(f" - {r.item_id} {r.item_rev_id} -> {r.file_local_path}")


if __name__ == "__main__":
    main()
