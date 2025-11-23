#!/usr/bin/env python3
"""
Simple console helper to experiment with DataManagementService.GetItemAndRelatedObjects.

It logs into Teamcenter using the ClientX Session helper, issues a single
GetItemAndRelatedObjects request for the provided item_id, and then prints
the debug log so you can inspect the exact payload and server response.
"""

from __future__ import annotations

import argparse
import logging
import traceback
import os
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, Sequence
from dotenv import load_dotenv

# Allow running directly via "python tools/test_getiar.py" by adding project root
_project_root = Path(__file__).resolve().parents[2]
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

# ClientX.Session uses top-level "tc_utils", so expose the package root too
_package_root = Path(__file__).resolve().parents[1]
if str(_package_root) not in sys.path:
    sys.path.insert(0, str(_package_root))

from teamcenter_get_drawings.ClientX.Session import Session  # type: ignore
from teamcenter_get_drawings.tc_net.core import DATASET_RELATIONS  # type: ignore

from System import Array, String  # type: ignore
from System.Collections import Hashtable  # type: ignore
from Teamcenter.Services.Strong.Core import DataManagementService  # type: ignore
from Teamcenter.Services.Strong.Core._2007_01 import DataManagement as DM2007  # type: ignore
from Teamcenter.Services.Strong.Core._2008_06 import DataManagement as DM2008  # type: ignore
from Teamcenter.Services.Strong.Core._2009_10 import DataManagement as DM2009  # type: ignore


def _attr_info(name: str, value: str):
    attr = DM2008.AttrInfo()
    attr.Name = name
    attr.Value = value
    return attr


def _dataset_relation_filters(relations: Sequence[str], dataset_types: Iterable[str] | None = None):
    rel_filters = []
    type_names = list(dataset_types or [None])
    for rel in relations:
        for dtype in type_names:
            rel_filter = DM2008.DatasetRelationFilter()
            rel_filter.RelationTypeName = rel
            if dtype:
                rel_filter.DatasetTypeName = dtype
            rel_filters.append(rel_filter)
    return rel_filters


def _build_dataset_info(relations: Sequence[str], dataset_types: Iterable[str] | None = None):
    ds_info = DM2008.DatasetInfo()
    dataset_filter = DM2008.DatasetFilter()
    dataset_filter.Processing = "All"
    rel_filters = _dataset_relation_filters(relations, dataset_types)
    if rel_filters:
        dataset_filter.RelationFilters = Array[DM2008.DatasetRelationFilter](rel_filters)
    ds_info.Filter = dataset_filter
    return ds_info


def _get_item_from_attribute(dms, item_id: str):
    """Fetches Item/ItemRevision output using GetItemFromAttribute (safe fallback)."""
    info = DM2009.GetItemFromAttributeInfo()
    attrs = Hashtable()
    attrs["item_id"] = item_id
    info.ItemAttributes = attrs
    pref = DM2007.GetItemFromIdPref()
    resp = dms.GetItemFromAttribute(Array[DM2009.GetItemFromAttributeInfo]([info]), 1, pref)
    outputs = getattr(resp, "Output", None) or getattr(resp, "output", None)
    if not outputs:
        raise RuntimeError("GetItemFromAttribute returned no outputs.")
    return outputs[0]


def _describe_dataset_info(dataset_info) -> Dict[str, Any]:
    filt = getattr(dataset_info, "Filter", None)
    rel_filters = []
    try:
        rel_filters = [
            {
                "relation": getattr(rel, "RelationTypeName", None),
                "dataset_type": getattr(rel, "DatasetTypeName", None),
            }
            for rel in (getattr(filt, "RelationFilters", None) or [])
        ]
    except Exception:
        rel_filters = ["<unavailable>"]
    return {
        "client_id": getattr(dataset_info, "ClientId", None),
        "filter": {
            "processing": getattr(filt, "Processing", None) if filt is not None else None,
            "relation_filters": rel_filters,
        },
    }


def _describe_info(item_info, rev_info, dataset_info) -> Dict[str, Any]:
    def _ids():
        try:
            return [(attr.Name, attr.Value) for attr in (item_info.Ids or [])]
        except Exception:
            return "<unavailable>"

    return {
        "item_info": {
            "client_id": getattr(item_info, "ClientId", None),
            "use_id_first": getattr(item_info, "UseIdFirst", None),
            "uid": getattr(item_info, "Uid", None),
            "ids": _ids(),
        },
        "rev_info": {
            "client_id": getattr(rev_info, "ClientId", None),
            "processing": getattr(rev_info, "Processing", None),
            "use_id_first": getattr(rev_info, "UseIdFirst", None),
            "uid": getattr(rev_info, "Uid", None),
            "id": getattr(rev_info, "Id", None),
            "nrevs": getattr(rev_info, "NRevs", None),
            "revision_rule": getattr(rev_info, "RevisionRule", None),
        },
        "dataset_info": _describe_dataset_info(dataset_info),
    }


def main() -> int:
    load_dotenv()

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("item_id", help="Item ID to query")
    parser.add_argument("--url", default=os.getenv("TC_URL"), help="TC SOA URL")
    parser.add_argument("--user", default=os.getenv("TCUSER"), help="Teamcenter user id")
    parser.add_argument("--password", default=os.getenv("TCPASSWORD"), help="Teamcenter password")
    parser.add_argument("--group", default=os.getenv("TCGROUP", "default"))
    parser.add_argument("--role", default=os.getenv("TCROLE", "default"))
    parser.add_argument(
        "--revision-rule",
        default=os.getenv("TC_REVISION_RULE", "Released Status; Working"),
        help="Revision rule string",
    )
    parser.add_argument(
        "--force-ids",
        action="store_true",
        help="Force UseIdFirst=True even when a UID is available.",
    )
    parser.add_argument(
        "--uid",
        help="Explicit UID to use for ItemInfo. Defaults to UID returned by GetItemFromAttribute.",
    )
    parser.add_argument(
        "--log-path",
        default=Path("./getiar-debug.log"),
        type=Path,
        help="Debug log file to create (will be overwritten).",
    )
    args = parser.parse_args()

    log_path: Path = args.log_path
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.touch(exist_ok=True)
    file_handler = logging.FileHandler(str(log_path), mode="w", encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter("%(levelname)s:%(name)s:%(message)s"))
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    root_logger.addHandler(file_handler)

    if not args.url or not args.user or not args.password:
        parser.error("TC_URL, TCUSER, and TCPASSWORD must be provided via args or environment variables.")

    session = Session(args.url)
    try:
        cred = Session.credentialManager
        cred.name = args.user
        cred.password = args.password
        group = ""
        role = ""
        if group or role:
            cred.SetGroupRole(group or "", role or "")

        user_obj = session.login()
    except:
        exit("Login failed, please check your credentials and URL.")

    try:
        conn = session.connection
        dms = DataManagementService.getService(conn)

        logging.info("Fetching fallback Item via GetItemFromAttribute for %s", args.item_id)
        fallback_output = _get_item_from_attribute(dms, args.item_id)
        fallback_item = getattr(fallback_output, "Item", None)
        fallback_uid = getattr(fallback_item, "Uid", None)

        info = DM2008.GetItemAndRelatedObjectsInfo()
        info.ClientId = args.item_id

        item_info = DM2008.ItemInfo()
        dataset_info = DM2008.DatasetInfo()
        dataset_filter = DM2008.DatasetFilter()
        dataset_filter.Processing = "All"
        dataset_info.DatasetFilter = dataset_filter
        item_info.DatasetInfo = dataset_info

        item_info.ClientId = args.item_id
        if not args.force_ids and (args.uid or fallback_uid):
            item_info.UseIdFirst = False
            item_info.Uid = args.uid or fallback_uid
        else:
            item_info.UseIdFirst = True
            item_info.Ids = Array[DM2008.AttrInfo]([_attr_info("item_id", args.item_id)])
        info.ItemInfo = item_info

        rev_info = DM2008.RevInfo()
        rev_info.ClientId = args.item_id
        rev_info.Id = args.item_id
        rev_info.Processing = "Rule"
        rev_info.RevisionRule = args.revision_rule
        rev_info.NRevs = 1
        info.RevInfo = rev_info

        dataset_info = _build_dataset_info(DATASET_RELATIONS)
        dataset_info.ClientId = args.item_id
        info.DatasetInfo = dataset_info

        logging.debug(
            "Issuing GetItemAndRelatedObjects for %s payload=%s",
            args.item_id,
            _describe_info(item_info, rev_info, dataset_info),
        )
        resp = dms.GetItemAndRelatedObjects(Array[DM2008.GetItemAndRelatedObjectsInfo]([info]))
        logging.info(
            "Response service data: %s",
            getattr(resp, "ServiceData", None) or getattr(resp, "serviceData", None),
        )
        outputs = getattr(resp, "Output", None) or getattr(resp, "output", None)
        logging.info("Response output count: %s", 0 if not outputs else len(outputs))
        print(f"GetItemAndRelatedObjects completed for {args.item_id}. See {log_path} for details.")
    except Exception as e:
        tb = traceback.format_exc()
        logging.error("Error during GetItemAndRelatedObjects: %s\n%s", e, tb)   
    finally:
        try:
            session.logout()
        except Exception as exc:
            logging.warning("Logout encountered an error: %s", exc)

    print("\n--- Debug Log ---")
    if log_path.exists():
        print(log_path.read_text(encoding="utf-8"))
    else:
        print(f"No log output was generated at {log_path}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
