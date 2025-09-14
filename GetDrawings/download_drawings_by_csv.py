#!/usr/bin/env python3
"""
Batch-download drawing PDFs for a list of items from Teamcenter (SOA .NET via pythonnet).

Changes in this version
  • Latest revision is obtained using DataManagementService.GetItemFromId(info[], 0, ...)
    when the CSV column contains Item IDs (fast & canonical).
  • If GetItemFromId is not available, falls back to GetLatestItemRevisions, then to a
    last_mod_date sort (as before).

What it does
  1) Reads a CSV file with one column containing item identifiers (IDs by default; --name-column for Names).
  2) Logs into Teamcenter using your username/password.
  3) For each item, resolves the LATEST item revision (GetItemFromId(..., 0, ...) preferred).
  4) Finds PDF-bearing datasets on that revision (IMAN_specification/rendering/reference).
  5) Downloads the PDFs to ./downloads/<timestamp>/ and writes download_results.csv.

Setup
  • pip install pythonnet
  • Set TC_SOA_NET_DIR to your netstandard2.0 DLL folder, e.g.
      Windows PowerShell:
        $env:TC_SOA_NET_DIR = "C:\\Siemens\\Teamcenter\\soa_client\\bin\\netstandard2.0"
"""

import os, sys, csv, argparse, getpass
from pathlib import Path
from datetime import datetime
from typing import List, Tuple, Optional
from importlib import import_module

# ----- pythonnet / CLR bootstrap ---------------------------------------------
try:
    import clr  # type: ignore
except Exception:
    print("pythonnet is required. Install with: pip install pythonnet")
    raise

DLL_DIR = os.environ.get("TC_SOA_NET_DIR")
if not DLL_DIR:
    print("ERROR: TC_SOA_NET_DIR is not set; cannot locate Teamcenter .NET client DLLs.")
    sys.exit(2)

for fname in os.listdir(DLL_DIR):
    if fname.lower().endswith(".dll"):
        try:
            clr.AddReference(os.path.join(DLL_DIR, fname))
        except Exception:
            pass

# ----- .NET imports -----------------------------------------------------------
from System import Array, String
from Teamcenter.Soa.Client import Connection
from Teamcenter.Soa.Client.Model import ModelObject
from Teamcenter.Soa.Client.Model.Strong import Item, ItemRevision, WorkspaceObject
from Teamcenter.Schemas.Soa._2006_03.Exceptions import ServiceException
from Teamcenter.Services.Strong.Core import SessionService, DataManagementService
from Teamcenter.Services.Strong.Query import SavedQueryService, QueryInput
from Teamcenter.Services.Loose.Core._2006_03.FileManagement import FileManagementUtility

# ----- Session + tiny helpers -------------------------------------------------
class Tc:
    def __init__(self, host: str):
        self.connection = Connection(host)
        self.session    = SessionService.getService(self.connection)
        self.dm         = DataManagementService.getService(self.connection)
        self.sq         = SavedQueryService.getService(self.connection)
        self.fm         = FileManagementUtility(self.connection)

    def login(self, user: str, pwd: str, group: str = "dba", role: str = "dba"):
        self.session.Login(user, pwd, group, role, "", "Python-PDF-Downloader")

    def logout(self):
        try:
            self.session.Logout()
        except Exception:
            pass

    def ensure(self, objs: List[ModelObject], props: List[str]):
        if objs:
            self.dm.GetProperties(Array[ModelObject](objs), Array[String](props))

# ----- CSV input --------------------------------------------------------------
def read_single_column_csv(path: Path) -> List[str]:
    vals: List[str] = []
    with path.open("r", newline="", encoding="utf-8-sig") as f:
        for row in csv.reader(f):
            if row and row[0].strip():
                vals.append(row[0].strip())
    return vals

# ----- Saved query lookup (fallback / for name search) ------------------------
def _find_saved_query(tc: Tc, names: List[str]):
    g = tc.sq.GetSavedQueries()
    for want in names:
        for q in list(g.Queries):
            if q.Name == want or q.Name.endswith(want):
                return q
    return None

def find_item_by_name(tc: Tc, name: str) -> Optional[Item]:
    q = _find_saved_query(tc, ["Item Name"])
    if q is None:
        return None
    qi = QueryInput()
    qi.Query = q
    qi.MaxNumToReturn = 25
    qi.LimitList = Array[ModelObject]([])
    qi.Entries = Array[String]([ "Item Name" ])
    qi.Values  = Array[String]([ name ])
    sresp = tc.sq.ExecuteSavedQueries(Array[QueryInput]([qi]))
    res = sresp.ArrayOfResults[0]
    if not res.ObjectUIDS or res.ObjectUIDS.Length == 0:
        return None
    sd = tc.dm.LoadObjects(Array[String](list(res.ObjectUIDS)))
    objs = [sd.GetPlainObject(i) for i in range(sd.sizeOfPlainObjects())]
    for o in objs:
        if isinstance(o, Item):
            return o
    return None

# ----- Preferred path: GetItemFromId(..., 0, ...) -----------------------------
def _resolve_GetItemFromIdInfo_type():
    # Try common versioned namespaces where GetItemFromIdInfo lives
    candidates = [
        "Teamcenter.Services.Strong.Core._2007_01.DataManagement",
        "Teamcenter.Services.Strong.Core._2008_06.DataManagement",
        "Teamcenter.Services.Strong.Core._2011_06.DataManagement",
        "Teamcenter.Services.Strong.Core.DataManagement",  # unversioned fallback
    ]
    for modname in candidates:
        try:
            mod = import_module(modname)
            t = getattr(mod, "GetItemFromIdInfo", None)
            if t is not None:
                return t
        except Exception:
            continue
    return None

_GetItemFromIdInfo = _resolve_GetItemFromIdInfo_type()

def get_item_and_latest_rev_by_id_fast(tc: Tc, item_id: str) -> Tuple[Optional[Item], Optional[ItemRevision]]:
    """Use DataManagementService.GetItemFromId(info[], 0, ...) to get latest revision."""
    if _GetItemFromIdInfo is None:
        return (None, None)
    try:
        info = _GetItemFromIdInfo()
        # property name is usually ItemId (PascalCase); some bindings expose itemId
        if hasattr(info, "ItemId"):
            setattr(info, "ItemId", item_id)
        elif hasattr(info, "itemId"):
            setattr(info, "itemId", item_id)
        else:
            return (None, None)

        resp = tc.dm.GetItemFromId(Array[_GetItemFromIdInfo]([info]), 0, None)  # 0 = latest
        # Pull item + revision from typical response members
        item = rev = None
        try:
            out = resp.Output[0]
            item = getattr(out, "Item", None) or getattr(out, "item", None)
            # common field names seen in practice
            for fld in ("ItemRev", "ItemRevision", "LatestItemRev", "LatestRevision"):
                rev = rev or getattr(out, fld, None)
        except Exception:
            pass

        # If the typed output fields weren’t present, harvest from ServiceData
        if item is None or rev is None:
            sd = getattr(resp, "ServiceData", None)
            if sd is not None:
                items, revs = [], []
                for i in range(sd.sizeOfPlainObjects()):
                    o = sd.GetPlainObject(i)
                    if isinstance(o, Item): items.append(o)
                    if isinstance(o, ItemRevision): revs.append(o)
                if item is None and items: item = items[0]
                if rev is None and revs:   rev  = revs[0]
        return (item, rev)
    except ServiceException:
        return (None, None)
    except Exception:
        return (None, None)

# ----- Fallback latest-revision helpers ---------------------------------------
def get_latest_revision_fallback(tc: Tc, item: Item) -> Optional[ItemRevision]:
    # Try GetLatestItemRevisions if present
    fn = getattr(tc.dm, "GetLatestItemRevisions", None)
    if fn is not None:
        try:
            resp = fn(Array[Item]([item]))
            try:
                return resp.OutputItemRevisions[0]
            except Exception:
                pass
        except ServiceException:
            pass
    # Last resort: pick by last_mod_date
    try:
        tc.ensure([item], ["revision_list"])
        revs = list(item.Revision_list)
    except Exception:
        return None
    tc.ensure(revs, ["last_mod_date"])
    def key(ir: ItemRevision):
        try: return ir.GetPropertyDisplayableValue("last_mod_date")
        except Exception: return ""
    revs.sort(key=key, reverse=True)
    return revs[0] if revs else None

# High-level resolver used by the main loop
def resolve_latest_by_value(tc: Tc, value: str, treat_as_id: bool) -> Tuple[Optional[Item], Optional[ItemRevision]]:
    if treat_as_id:
        item, rev = get_item_and_latest_rev_by_id_fast(tc, value)
        if item is not None and rev is not None:
            return (item, rev)
        # soft fallback: try to find item via saved query, then latest via fallback
        item = find_item_by_name(tc, value) if not treat_as_id else None
        if item is None:
            # If it's an ID but GetItemFromId failed, try the Item ID query
            q = _find_saved_query(tc, ["Item ID"])
            if q is not None:
                qi = QueryInput()
                qi.Query = q
                qi.MaxNumToReturn = 1
                qi.LimitList = Array[ModelObject]([])
                qi.Entries = Array[String]([ "Item ID" ])
                qi.Values  = Array[String]([ value ])
                sresp = tc.sq.ExecuteSavedQueries(Array[QueryInput]([qi]))
                res = sresp.ArrayOfResults[0]
                if res.ObjectUIDS and res.ObjectUIDS.Length > 0:
                    sd = tc.dm.LoadObjects(Array[String](list(res.ObjectUIDS)))
                    for i in range(sd.sizeOfPlainObjects()):
                        obj = sd.GetPlainObject(i)
                        if isinstance(obj, Item):
                            item = obj
                            break
        if item is not None:
            return (item, get_latest_revision_fallback(tc, item))
        return (None, None)
    else:
        item = find_item_by_name(tc, value)
        if item is None:
            return (None, None)
        return (item, get_latest_revision_fallback(tc, item))

# ----- Drawing/PDF discovery (unchanged) --------------------------------------
_IR_REL_NAMES = ["IMAN_specification", "IMAN_rendering", "IMAN_reference"]
_DATASET_FILE_PROPS = ["ref_list", "object_name", "object_type"]
_FILE_NAME_PROPS = ["original_file_name", "ref_name", "object_string"]

def _collect_related_datasets(tc: Tc, rev: ItemRevision) -> List[ModelObject]:
    datasets: List[ModelObject] = []
    for rel in _IR_REL_NAMES:
        # generic: try property-by-name to avoid strong-name mismatches
        try:
            tc.ensure([rev], [rel])
            rel_objs = list(rev.GetPropertyObject(rel))
        except Exception:
            rel_objs = []
        datasets.extend(rel_objs)
    # de-dup by UID
    uniq, seen = [], set()
    for d in datasets:
        u = getattr(d, "Uid", None)
        if u and u not in seen:
            seen.add(u); uniq.append(d)
    return uniq

def _dataset_has_pdf_type(ds) -> bool:
    try:
        return "pdf" in (ds.GetPropertyDisplayableValue("object_type") or "").lower()
    except Exception:
        return False

def _files_from_dataset(tc: Tc, ds: ModelObject) -> List[ModelObject]:
    try:
        tc.ensure([ds], _DATASET_FILE_PROPS)
    except Exception:
        pass
    files = []
    try:
        files = list(ds.Ref_list)
    except Exception:
        try:
            files = list(ds.GetPropertyObject("ref_list"))
        except Exception:
            files = []
    return files

def _imanfile_is_pdf(tc: Tc, f: ModelObject) -> Tuple[bool, str]:
    try:
        tc.ensure([f], _FILE_NAME_PROPS)
    except Exception:
        pass
    name = None
    for p in _FILE_NAME_PROPS:
        try:
            name = f.GetPropertyDisplayableValue(p)
            if name: break
        except Exception:
            continue
    if not name:
        name = getattr(f, "Uid", "file")
    return (name.lower().endswith(".pdf"), name)

def find_pdf_files_for_revision(tc: Tc, rev: ItemRevision) -> List[ModelObject]:
    datasets = _collect_related_datasets(tc, rev)
    hits: List[ModelObject] = []
    for ds in datasets:
        for f in _files_from_dataset(tc, ds):
            is_pdf, _ = _imanfile_is_pdf(tc, f)
            if is_pdf: hits.append(f)
    # de-dup
    uniq, seen = [], set()
    for f in hits:
        u = getattr(f, "Uid", None)
        if u and u not in seen:
            seen.add(u); uniq.append(f)
    return uniq

# ----- Download ---------------------------------------------------------------
def ensure_output_dir(base: Optional[Path]) -> Path:
    when = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = (base or Path.cwd()) / "downloads" / when
    out.mkdir(parents=True, exist_ok=True)
    return out

def download_files(tc: Tc, iman_files: List[ModelObject], out_dir: Path) -> List[Tuple[str, str]]:
    if not iman_files:
        return []
    try:
        tc.fm.GetFiles(Array[ModelObject](iman_files), str(out_dir))
    except Exception:
        # read-ticket fallback
        tickets = tc.fm.GetFileReadTickets(Array[ModelObject](iman_files))
        try:
            tc.fm.DownloadFiles(tickets, str(out_dir))
        except Exception:
            tc.fm.GetFilesFromTickets(tickets, str(out_dir))
    results = []
    for f in iman_files:
        _, name = _imanfile_is_pdf(tc, f)
        results.append((getattr(f, "Uid", name), str(out_dir / name)))
    return results

# ----- CLI --------------------------------------------------------------------
def build_parser():
    p = argparse.ArgumentParser(description="Download drawing PDFs for items listed in a CSV")
    p.add_argument("csv", type=Path, help="Path to single-column CSV with Item IDs (default) or Names")
    p.add_argument("-host", default="http://localhost:7001/tc", help="Teamcenter server URL")
    p.add_argument("-user", help="Username (prompt if omitted)")
    p.add_argument("-password", help="Password (prompt if omitted)")
    p.add_argument("--name-column", action="store_true",
                   help="Interpret CSV values as Item Names (default is Item IDs)")
    p.add_argument("--out", type=Path, help="Output root folder (default ./downloads/<timestamp>/)")
    return p

def main():
    args = build_parser().parse_args()
    if not args.csv.exists():
        print("CSV not found:", args.csv); sys.exit(1)
    values = read_single_column_csv(args.csv)
    if not values:
        print("CSV appears empty."); sys.exit(1)

    user = args.user or input("User name: ")
    pwd  = args.password if args.password is not None else getpass.getpass("Password: ")
    out_dir = ensure_output_dir(args.out)

    tc = Tc(args.host)
    rows = [("input_value", "item_uid", "rev_uid", "pdf_count", "saved_to")]

    try:
        tc.login(user, pwd)
        for val in values:
            try:
                item, rev = resolve_latest_by_value(tc, val, treat_as_id=not args.name_column)
                if item is None:
                    print(f"[MISS] {val}: item not found")
                    rows.append((val, "", "", "0", "")); continue
                if rev is None:
                    print(f"[MISS] {val}: latest revision not found")
                    rows.append((val, getattr(item, "Uid", ""), "", "0", "")); continue

                pdfs = find_pdf_files_for_revision(tc, rev)
                if not pdfs:
                    print(f"[MISS] {val}: no PDF files on latest revision")
                    rows.append((val, getattr(item,"Uid",""), getattr(rev,"Uid",""), "0", "")); continue

                dl = download_files(tc, pdfs, out_dir)
                print(f"[HIT] {val}: downloaded {len(dl)} file(s)")
                rows.append((val, getattr(item,"Uid",""), getattr(rev,"Uid",""), str(len(dl)), str(out_dir)))
            except ServiceException as e:
                msg = getattr(e, "Message", str(e))
                print(f"[ERR] {val}: {msg}")
                rows.append((val, "", "", "0", "ERROR:"+msg))
            except Exception as e:
                print(f"[ERR] {val}: {e}")
                rows.append((val, "", "", "0", "ERROR:"+str(e)))
    finally:
        tc.logout()

    # summary CSV
    summary = out_dir / "download_results.csv"
    with summary.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerows(rows)
    print("\nSummary written to", summary)

if __name__ == "__main__":
    main()
