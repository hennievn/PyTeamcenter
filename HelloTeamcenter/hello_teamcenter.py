# hello_teamcenter.py
# Demo driver matching HelloTeamcenter/hello/* (HomeFolder and Query).
from __future__ import annotations

import argparse
import sys
from importlib import import_module
from typing import Optional, Tuple

from clientx import Session, ConnectionConfig

# Strong services (service classes only; types live in versioned namespaces)
from Teamcenter.Services.Strong.Core import DataManagementService  # type: ignore
from Teamcenter.Services.Strong.Query import SavedQueryService  # type: ignore

# Strong model classes
from Teamcenter.Soa.Client.Model import ModelObject  # type: ignore
from Teamcenter.Soa.Client.Model.Strong import User, Folder  # type: ignore

from Teamcenter.Schemas.Soa._2006_03.Exceptions import (  # type: ignore
    ServiceException,
    NotLoadedException,
)


# --------- Helpers to import versioned type packages (match C# sample) -------
def _import_dm_types() -> object:
    """
    C# sample uses: Teamcenter.Services.Strong.Core._2006_03.DataManagement
    We import that first; if not present, fall back through known versions.
    """
    for ver in ("_2006_03", "_2008_06", "_2010_04", "_2012_10", "_2014_06", "_2016_10", "_2020_01", "_2023_12", "_2024_06"):
        ns = f"Teamcenter.Services.Strong.Core.{ver}.DataManagement"
        try:
            return import_module(ns)
        except Exception:
            continue
    raise ImportError("Could not import a Strong Core DataManagement types package.")


def _import_sq_types() -> object:
    """
    C# sample uses: Teamcenter.Services.Strong.Query._2007_06.SavedQuery
    """
    for ver in ("_2007_06", "_2008_06", "_2010_04", "_2012_10", "_2014_06", "_2016_10", "_2020_01", "_2023_12", "_2024_06"):
        ns = f"Teamcenter.Services.Strong.Query.{ver}.SavedQuery"
        try:
            return import_module(ns)
        except Exception:
            continue
    raise ImportError("Could not import a Strong Query SavedQuery types package.")


DMTypes = _import_dm_types()
SQTypes = _import_sq_types()


# ------------------------------- Demos ---------------------------------------
def demo_home_folder(user: User) -> None:
    """
    Mirror of hello/HomeFolder.cs: load home folder, list its contents.
    """
    conn = Session.getConnection()
    dm = DataManagementService.getService(conn)

    # Ensure user's home folder property is loaded; prop names vary slightly across kits.
    # We try the canonical strong property, else fall back to generic getPropertyObject.
    home: Optional[Folder] = None

    # Try to load via properties call (safer for NotLoadedException)
    props = ["home_folder", "home", "awp0HomeFolder"]
    try:
        dm.GetProperties([user], props)  # noqa: N802
    except ServiceException:
        pass

    # Probe the likely attributes
    for attr in ("Home_folder", "Home", "HomeFolder"):
        if hasattr(user, attr):
            try:
                home = getattr(user, attr)
                if isinstance(home, Folder):
                    break
            except Exception:
                pass

    # Fallback via generic property object
    if home is None:
        for p in ("home_folder", "home"):
            try:
                po = user.getPropertyObject(p)
                if po is not None:
                    mo = po.GetModelObjectValue()  # noqa: N802
                    if isinstance(mo, Folder):
                        home = mo
                        break
            except Exception:
                continue

    if home is None:
        print("[home] Could not resolve user's home folder property.")
        return

    # Load contents then print
    try:
        dm.GetProperties([home], ["contents"])  # noqa: N802
        contents = getattr(home, "Contents", None)
        if contents is None:
            # Fallback through generic property
            po = home.getPropertyObject("contents")
            contents = po.GetModelObjectArrayValue() if po is not None else []
    except NotLoadedException:
        contents = []

    print("\nHome Folder:")
    Session.print_objects(list(contents or []))


def demo_saved_query() -> None:
    """
    Mirror of hello/Query.cs: locate the "Item Name" saved query and run it with '*'.
    """
    conn = Session.getConnection()
    sq = SavedQueryService.getService(conn)
    dm = DataManagementService.getService(conn)

    try:
        # Get list of saved queries
        saved = sq.GetSavedQueries()  # returns SQTypes.GetSavedQueriesResponse
        queries = getattr(saved, "Queries", []) or []
        if not queries:
            print("There are no saved queries in the system.")
            return

        # Find one called "Item Name"
        target = None
        for entry in queries:
            if getattr(entry, "Name", "") == "Item Name":
                target = entry.Query
                break
        if target is None:
            print('Saved query "Item Name" not found.')
            return

        # Build request
        sq_in = Array[SQTypes.SavedQueryInput]([SQTypes.SavedQueryInput()])  # type: ignore
        sq_in[0].Query = target
        sq_in[0].MaxNumToReturn = 25
        sq_in[0].LimitList = Array[ModelObject]([])  # no limiting
        sq_in[0].Entries = Array[String]([String("Item Name")])  # parameter name
        sq_in[0].Values = Array[String]([String("*")])

        # Execute
        sq_out = sq.ExecuteSavedQueries(sq_in)  # -> SQTypes.SavedQueriesResponse
        results = sq_out.ArrayOfResults[0]  # SQTypes.QueryResults

        # Page 10 at a time (as in C# sample)
        uids = results.ObjectUIDS or []
        print("\nFound Items:")
        for i in range(0, len(uids), 10):
            page = uids[i : i + 10]
            sd = dm.LoadObjects(Array[String](page))  # noqa: N802
            objs = [sd.GetPlainObject(k) for k in range(sd.sizeOfPlainObjects())]
            Session.print_objects(objs)

    except ServiceException as e:
        print("ExecuteSavedQuery service request failed.")
        print(e)


# Optional: the create/revise/delete example from HelloTeamcenter/DataManagement.cs
# Many sites restrict create permissions; keep this commented unless you need it.
# def demo_datamanagement_create_cycle() -> None:
#     ...

# ------------------------------- CLI -----------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser(description="Python HelloTeamcenter (ClientX + demos)")
    ap.add_argument("-host", default="http://localhost:7001/tc", help="Teamcenter web-tier URL or tccs://ENVNAME")
    ap.add_argument("-sso", default="", help="SSO login URL (optional)")
    ap.add_argument("-appID", default="", help="SSO application ID (optional)")
    ap.add_argument("-user", default="", help="Username (STD login). If omitted, you will be prompted.")
    ap.add_argument("-password", default="", help="Password (STD login). If omitted, you will be prompted.")
    ap.add_argument("-group", default="dba")
    ap.add_argument("-role", default="dba")
    ap.add_argument("-locale", default="en_US")
    ap.add_argument("-disc", default="SoaAppX", help="Session discriminator")
    ap.add_argument("--no-query", action="store_true", help="Skip the Saved Query demonstration")
    args = ap.parse_args()

    # Emulate ClientX’s TCCS argument resolution (only if you passed -host tccs://…)
    arg_map = Session.get_configuration_from_tccs(["-host", args.host, "-sso", args.sso, "-appID", args.appID])
    host = arg_map.get("-host", args.host)
    sso = arg_map.get("-sso", args.sso)
    appID = arg_map.get("-appID", args.appID)

    preset: Optional[Tuple[str, str, str, str, str]] = None
    if args.user and args.password:
        preset = (args.user, args.password, args.group, args.role, args.disc)

    session = Session(host=host, sso_url=sso, app_id=appID, preset_creds=preset)
    try:
        user = session.login()
        print(f"\nLogged in as: {user.User_name}")

        # Home folder demo
        demo_home_folder(user)

        # Saved query demo
        if not args.no_query:
            demo_saved_query()

    finally:
        session.logout()
        print("Logged out.")


if __name__ == "__main__":
    main()
