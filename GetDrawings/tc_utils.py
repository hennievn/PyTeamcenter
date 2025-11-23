from __future__ import annotations

import os
import sys
import clr  # type: ignore
import logging
from pathlib import Path
from typing import List
import shutil
import traceback


"""Utility functions for Teamcenter Get Drawings (UV/site-packages friendly).

This module handles:
- TC_LIBS / assembly discovery (no env vars needed)
- .NET assembly load + resolver
- Teamcenter helper functions for latest-revision discovery
- FMU + Loose FMS download flows
- A background worker that the GUI calls

Designed to live at: teamcenter_get_drawings/tc_utils.py
"""

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.ERROR)

PKG_NAME = "teamcenter_get_drawings"

# ------------------------------------------------------------
# Assembly & package discovery
# ------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent


def _candidate_pkg_roots() -> List[Path]:
    """Generates a list of candidate directories where the package might be installed."""
    roots: List[Path] = [BASE_DIR]
    try:
        # Use importlib.resources to find the installed package path
        import importlib.resources as ir

        p = Path(ir.files(PKG_NAME))  # type: ignore[attr-defined]
        if p.exists():
            roots.append(p)
    except (ImportError, AttributeError, ModuleNotFoundError):
        pass

    # Fallback to checking sys.path and common venv layouts
    try:
        exe = Path(sys.executable).resolve()
        for cand in [
            exe.parent.parent / "Lib" / "site-packages" / PKG_NAME,
            exe.parent.parent.parent / "Lib" / "site-packages" / PKG_NAME,
        ]:
            if cand.exists():
                roots.append(cand)
    except Exception:
        pass

    # Remove duplicates
    return list(dict.fromkeys(r.resolve() for r in roots))


def _find_tc_libs() -> Path:
    """Finds the TC_LIBS directory containing Teamcenter DLLs."""
    required = "TcSoaClient.dll"  # Sentinel file
    for root in _candidate_pkg_roots():
        for cand in [root / "TC_LIBS", root / PKG_NAME / "TC_LIBS", root]:
            if cand.is_dir() and (cand / required).exists():
                return cand.resolve()
    return (BASE_DIR / "TC_LIBS").resolve()  # Last resort


TC_LIBS = _find_tc_libs()
if str(TC_LIBS) not in sys.path:
    sys.path.insert(0, str(TC_LIBS))

# Help Windows locate native dependencies
if os.name == "nt" and hasattr(os, "add_dll_directory"):
    os.add_dll_directory(str(TC_LIBS))

# Managed assembly resolver for .NET dependencies
try:
    from System.Runtime.Loader import AssemblyLoadContext  # type: ignore
    from System.Reflection import AssemblyName  # type: ignore

    def _managed_resolver(alc, name):
        try:
            simple = AssemblyName(name).Name
            cand = TC_LIBS / f"{simple}.dll"
            if cand.exists():
                return alc.load_from_assembly_path(str(cand))
        except Exception:
            pass
        return None

    AssemblyLoadContext.get_default().resolving += _managed_resolver
except (ImportError, AttributeError):
    import System  # type: ignore
    from System.Reflection import Assembly  # type: ignore

    def _managed_resolver_netfx(sender, args):
        try:
            simple = args.Name.split(",")[0]
            cand = TC_LIBS / f"{simple}.dll"
            if cand.exists():
                return Assembly.LoadFrom(str(cand))
        except Exception:
            pass
        return None

    System.AppDomain.CurrentDomain.AssemblyResolve += _managed_resolver_netfx

# Load all required Teamcenter assemblies
_DLLS = [
    "TcSoaCommon",
    "TcSoaClient",
    "TcSoaCoreStrong",
    "TcSoaStrongModel",
    "TcSoaFMS",
    "TcSoaFSC",
    "FMSNetTicket",
    "TcLogging",
    "TcSoaAiStrong",
]
for name in _DLLS:
    try:
        clr.AddReference(name)  # type: ignore
    except Exception as e:
        log.debug("Optional assembly not loaded: %s (%s)", name, e)

def worker_download(conn, items: List[str], downloads_root: str, q, cancel_evt, latest_only: bool):
    """The main background worker function called by the GUI to perform downloads."""
    try:
        from teamcenter_get_drawings.tc_net.core import (  # type: ignore
            download_drawing_datasets,
            get_drawing_datasets,
            set_default_policy,
        )

        def log_q(msg):
            q.put(("msg", msg))

        def display(obj, prop):
            try:
                return (obj.GetPropertyDisplayableValue(prop) or "").strip()
            except Exception:
                return ""

        set_default_policy(conn)
        log_q(f"Querying {len(items)} item id(s) for drawings...")
        all_saved_paths = {}

        for item_id in items:
            if cancel_evt.is_set():
                return

            log_q(f"{item_id}: fetching drawing datasets...")
            try:
                datasets, result = get_drawing_datasets(conn, item_id, latest_only)
            except Exception as exc:
                log_q(f"{item_id}: Query failed - {exc}")
                all_saved_paths[item_id] = []
                continue

            item = getattr(result, "Item", None) or getattr(result, "item", None)
            if item is not None:
                item_name = display(item, "object_name")
                if item_name:
                    log_q(f"{item_id}: {item_name}")

            if not datasets:
                log_q(f"{item_id}: No drawings found.")
                all_saved_paths[item_id] = []
                continue

            log_q(f"{item_id}: Found {len(datasets)} dataset(s). Starting download...")
            target_dir = os.path.join(downloads_root, item_id)
            try:
                saved_results = download_drawing_datasets(conn, list(datasets), target_dir)
            except Exception as exc:
                log_q(f"{item_id}: Download failed - {exc}")
                all_saved_paths[item_id] = []
                continue

            all_saved_paths[item_id] = []
            for _, paths in saved_results:
                for path in paths:
                    log_q(f"  ✓ Saved {os.path.basename(path)}")
                    all_saved_paths[item_id].append(path)

        q.put(("done", all_saved_paths))

    except Exception as e:
        tb = traceback.format_exc()
        q.put(("error", f"{e}\n{tb}"))
