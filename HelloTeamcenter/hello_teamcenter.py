#!/usr/bin/env python3
"""
Python port of Siemens Teamcenter sample "HelloTeamcenter" (.NET)

What it does (one-to-one with the C# sample):
  1) Connects & logs in via SOA .NET client
  2) Lists the current user's Home Folder contents
  3) Executes the Saved Query "Item Name" with value "*" and prints results (paged)
  4) Demonstrates basic Data Management: generate IDs → create Items → generate new
     revision IDs → revise the Items → delete the Items

Prereqs
  • Python 3.9+
  • pythonnet (pip install pythonnet)
  • Teamcenter SOA .NET client assemblies available locally (netstandard2.0)
  • Environment variables:
      TC_SOA_NET_DIR  -> folder containing the DLLs (e.g. C:\\Siemens\\Teamcenter\\soa_client\\bin\\netstandard2.0)
  • Teamcenter web tier + Pool Manager running. Default URL is http://localhost:7001/tc

Notes
  • This sample follows the username/password flow. If your site uses SSO, you can
    extend the Connection/CredentialManager bits accordingly.
  • The Saved Query name "Item Name" must exist on your server (OOTB).
"""

import os
import sys
import getpass
import argparse
from typing import List

# --- pythonnet / CLR setup ----------------------------------------------------
try:
    import clr  # type: ignore
except Exception as e:
    print("pythonnet is required. Install with: pip install pythonnet")
    raise

DLL_DIR = os.environ.get("TC_SOA_NET_DIR")
if not DLL_DIR:
    print("Environment variable TC_SOA_NET_DIR is not set; cannot find Teamcenter .NET client DLLs.")
    sys.exit(2)

# Minimal set frequently used by the .NET sample
DLLS = [
    "TcSoaClient.dll",
    "TcSoaCommon.dll",
    "TcSoaCoreStrong.dll",
    "TcSoaQueryStrong.dll",
    "TcSoaStrongModel.dll",
    "TcServerNetBindingInterface.dll",
    "TcServerNetBinding.dll",
]

for dll in DLLS:
    path = os.path.join(DLL_DIR, dll)
    if not os.path.exists(path):
        print(f"Missing required assembly: {path}")
        sys.exit(2)
    clr.AddReference(path)

# --- Import .NET namespaces ---------------------------------------------------
from System import Array, String

# Core services & types
from Teamcenter.Schemas.Soa._2006_03.Exceptions import ServiceException, NotLoadedException, CanceledOperationException
from Teamcenter.Soa.Client import Connection
from Teamcenter.Services.Strong.Core import SessionService, DataManagementService
from Teamcenter.Services.Strong.Query import SavedQueryService
from Teamcenter.Soa.Client.Model import ModelObject
from Teamcenter.Soa.Client.Model.Strong import (
    User,
    Folder,
    WorkspaceObject,
    Item,
    ItemRevision,
)

# DataManagement DTOs (same namespace as service)
from Teamcenter.Services.Strong.Core import (
    GenerateItemIdsAndInitialRevisionIdsProperties,
    GenerateItemIdsAndInitialRevisionIdsResponse,
    ItemIdsAndInitialRevisionIds,
    ItemProperties,
    ExtendedAttributes,
    GenerateRevisionIdsProperties,
    ReviseInfo,
)

# Query DTOs
from Teamcenter.Services.Strong.Query import (
    GetSavedQueriesResponse,
    SavedQuery,
    QueryInput,
    SavedQueriesResponse,
)


# --- Helpers ------------------------------------------------------------------
class TcSession:
    def __init__(self, host: str):
        # Establish a connection object (listeners are optional and omitted for brevity)
        self.connection = Connection(host)
        self.session_service = SessionService.getService(self.connection)
        self.dm_service = DataManagementService.getService(self.connection)

    def login(self, user: str, password: str, group: str = "dba", role: str = "dba",
              locale: str = "", discriminator: str = "Python-Session") -> User:
        """Login and return the User object (same as C# sample)."""
        try:
            resp = self.session_service.Login(user, password, group, role, locale, discriminator)
            # The login response includes the User as the first created object
            return resp.User
        except CanceledOperationException as e:
            # Prompt canceled or similar
            raise SystemExit(str(e))

    def logout(self) -> None:
        try:
            self.session_service.Logout()
        finally:
            pass

    def ensure_properties(self, objs: List[ModelObject], prop_names: List[str]):
        if not objs:
            return
        # Convert to typed arrays for .NET interop
        net_objs = Array[ModelObject](objs)
        net_props = Array[String](prop_names)
        self.dm_service.GetProperties(net_objs, net_props)

    def print_objects(self, objs: List[ModelObject]):
        # make sure object_string is loaded for WorkspaceObject
        try:
            self.ensure_properties(objs, ["object_string"])  # noop if already loaded
        except ServiceException:
            pass
        for o in objs:
            try:
                if isinstance(o, WorkspaceObject):
                    print(o.GetPropertyDisplayableValue("object_string"))
                else:
                    print(o.Uid)
            except NotLoadedException:
                print(o.Uid)


# --- Feature parity classes ---------------------------------------------------
class HomeFolderLister:
    def __init__(self, tc: TcSession):
        self.tc = tc

    def list_home(self, user: User) -> None:
        # Get the user's home folder, then its contents
        try:
            home: Folder = user.Home_folder
        except NotLoadedException as e:
            print("home_folder wasn't in the property policy; trying to load it explicitly…")
            self.tc.ensure_properties([user], ["home_folder"])
            home = user.Home_folder

        self.tc.ensure_properties([home], ["contents"])  # load contents property
        try:
            contents = list(home.Contents)
        except NotLoadedException:
            contents = []
        print("\nHome Folder:")
        self.tc.print_objects(contents)


class SaverQueryDemo:
    def __init__(self, tc: TcSession):
        self.tc = tc
        self.query_svc = SavedQueryService.getService(tc.connection)

    def run(self):
        # Find the saved query named "Item Name"
        try:
            resp: GetSavedQueriesResponse = self.query_svc.GetSavedQueries()
        except ServiceException as e:
            print("GetSavedQueries failed:", e.Message)
            return

        target: SavedQuery = None
        for q in list(resp.Queries):
            if q.Name == "Item Name":
                target = q
                break
        if target is None:
            print("There is not an 'Item Name' query on this server.")
            return

        # Execute with value "*", page results 10 at a time
        qi = QueryInput()
        qi.Query = target
        qi.MaxNumToReturn = 25
        qi.LimitList = Array[ModelObject]([])
        qi.Entries = Array[String](["Item Name"])
        qi.Values = Array[String](["*"])

        try:
            sresp: SavedQueriesResponse = self.query_svc.ExecuteSavedQueries(Array[QueryInput]([qi]))
            results = sresp.ArrayOfResults[0]
        except ServiceException as e:
            print("ExecuteSavedQueries failed:", e.Message)
            return

        print("\nFound Items:")
        uids = list(results.ObjectUIDS)
        # Page size 10
        for i in range(0, len(uids), 10):
            page = uids[i:i+10]
            sd = self.tc.dm_service.LoadObjects(Array[String](page))
            objs = [sd.GetPlainObject(k) for k in range(sd.sizeOfPlainObjects())]
            self.tc.print_objects(objs)


class DataManagementDemo:
    def __init__(self, tc: TcSession):
        self.tc = tc
        self.dm = tc.dm_service

    def generate_item_ids(self, count: int, item_type: str) -> List[ItemIdsAndInitialRevisionIds]:
        props = GenerateItemIdsAndInitialRevisionIdsProperties()
        props.Count = count
        props.ItemType = item_type
        resp: GenerateItemIdsAndInitialRevisionIdsResponse = self.dm.GenerateItemIdsAndInitialRevisionIds(
            Array[GenerateItemIdsAndInitialRevisionIdsProperties]([props])
        )
        if resp.ServiceData.sizeOfPartialErrors() > 0:
            raise ServiceException("GenerateItemIdsAndInitialRevisionIds returned partial errors")
        # Index 0 corresponds to the only bucket we requested
        all_new = resp.OutputItemIdsAndInitialRevisionIds
        ids = list(all_new[0])  # Hashtable[int -> ItemIdsAndInitialRevisionIds[]]
        return ids

    def create_items(self, ids: List[ItemIdsAndInitialRevisionIds], item_type: str):
        # (Optional) get form info like the C# sample
        related = self.dm.GetItemCreationRelatedInfo(item_type, None)
        if related.ServiceData.sizeOfPartialErrors() > 0:
            raise ServiceException("GetItemCreationRelatedInfo returned partial errors")
        form_types = [fa.FormType for fa in list(related.FormAttrs)] if related.FormAttrs is not None else []

        item_props = []
        for ii in ids:
            ip = ItemProperties()
            ip.ClientId = "Py-Client"
            ip.ItemId = ii.NewItemId
            ip.RevId = ii.NewRevId
            ip.Name = "AppX-Test"
            ip.Type = item_type
            ip.Description = "Test Item created by Python port of HelloTeamcenter"
            ip.Uom = ""
            # Mirror the sample: populate a form attribute if empty (best-effort)
            if form_types:
                ext = ExtendedAttributes()
                ext.ObjectType = form_types[0]
                # A trivial attribute value; adjust to a valid key for your site
                from System.Collections import Hashtable
                ext.Attributes = Hashtable()
                ext.Attributes["project_id"] = "project_id"
                ip.ExtendedAttributes = Array[ExtendedAttributes]([ext])
            item_props.append(ip)

        resp = self.dm.CreateItems(Array[ItemProperties](item_props), None, "")
        if resp.ServiceData.sizeOfPartialErrors() > 0:
            raise ServiceException("CreateItems returned partial errors")
        return list(resp.Output)

    def generate_rev_ids(self, items: List[Item]):
        inputs = []
        for it in items:
            p = GenerateRevisionIdsProperties()
            p.Item = it
            p.ItemType = ""
            inputs.append(p)
        resp = self.dm.GenerateRevisionIds(Array[GenerateRevisionIdsProperties](inputs))
        if resp.ServiceData.sizeOfPartialErrors() > 0:
            raise ServiceException("GenerateRevisionIds returned partial errors")
        # Hashtable[int -> RevisionIds]
        return resp.OutputRevisionIds

    def revise(self, rev_ids_ht, item_revs: List[ItemRevision]):
        # Compose ReviseInfo[]
        infos = []
        for idx, ir in enumerate(item_revs):
            ri = ReviseInfo()
            ri.BaseItemRevision = ir
            ri.ClientId = f"{ir.Uid}--{idx}"
            ri.Description = "describe testRevise"
            ri.Name = "testRevise"
            ri.NewRevId = rev_ids_ht[idx].NewRevId  # same indexing as C# sample
            infos.append(ri)
        revised = self.dm.Revise2(Array[ReviseInfo](infos))
        if revised.ServiceData.sizeOfPartialErrors() > 0:
            raise ServiceException("Revise2 returned partial errors")

    def delete_items(self, items: List[Item]):
        sd = self.dm.DeleteObjects(Array[ModelObject](items))
        if sd.sizeOfPartialErrors() > 0:
            raise ServiceException("DeleteObjects returned partial errors")

    def create_revise_delete(self):
        # Exactly mirrors DataManagement.createReviseAndDelete()
        count = 3
        ids = self.generate_item_ids(count, "Item")
        created = self.create_items(ids, "Item")
        items = [co.Item for co in created]
        item_revs = [co.ItemRev for co in created]
        rev_ids = self.generate_rev_ids(items)
        self.revise(rev_ids, item_revs)
        self.delete_items(items)


# --- CLI / main ---------------------------------------------------------------

def parse_args():
    p = argparse.ArgumentParser(description="HelloTeamcenter Python port")
    p.add_argument("-host", default="http://localhost:7001/tc", help="Teamcenter server URL")
    p.add_argument("-user", help="Username (omit to be prompted)")
    p.add_argument("-password", help="Password (omit to be prompted)")
    # Placeholders to keep flag parity with the C# sample; not implemented here
    p.add_argument("-sso", default="", help="SSO URL (not implemented in this port)")
    p.add_argument("-appID", default="", help="SSO App ID (not implemented in this port)")
    return p.parse_args()


def main():
    args = parse_args()
    user = args.user or input("User name: ")
    if args.password is not None:
        pwd = args.password
    else:
        pwd = getpass.getpass("Password: ")

    tc = TcSession(args.host)

    try:
        tc_user = tc.login(user, pwd)
        # 1) Home folder
        HomeFolderLister(tc).list_home(tc_user)
        # 2) Saved query demo
        SaverQueryDemo(tc).run()
        # 3) Data management demo
        DataManagementDemo(tc).create_revise_delete()
    except ServiceException as e:
        print("ServiceException:", e.Message)
    finally:
        try:
            tc.logout()
        except Exception:
            pass


if __name__ == "__main__":
    main()
