#!/usr/bin/env python3
"""
Python port of Siemens Teamcenter sample "RuntimeBO" (.NET)

What this demonstrates (typical for the RuntimeBO sample):
  1) Login via SOA .NET client (username/password path)
  2) Resolve a business object by Item ID (or UID)
  3) Treat it generically as a Runtime Business Object and:
       • Read common properties by name (dynamic, runtime)
       • (Best-effort) Update a string property via name→value
       • Print selected relations/children generically
  4) (Optional) Create *an arbitrary type* by type name using
     the Loose DataManagement CreateObjects path, then delete it

The script leans on pythonnet to consume the Teamcenter .NET assemblies
and intentionally uses the LOOSE DataManagement API for the generic
create/update because that mirrors the "runtime" (type-agnostic) pattern
in the .NET sample sets.

Prereqs
  • Python 3.9+
  • pythonnet → pip install pythonnet
  • Teamcenter SOA .NET assemblies on disk → set:
        TC_SOA_NET_DIR=C:\\Siemens\\Teamcenter\\soa_client\\bin\\netstandard2.0
  • Teamcenter web tier and Pool Manager running

Usage examples
  set TC_SOA_NET_DIR=C:\Siemens\Teamcenter\soa_client\bin\netstandard2.0
  python runtime_bo_demo.py -host http://localhost:7001/tc -item 000001
  # Update only (no create/delete):
  python runtime_bo_demo.py -host http://localhost:7001/tc -item 000001 -update-prop object_name "New Name"
  # Create a runtime object generically by type, set props, delete:
  python runtime_bo_demo.py -host http://localhost:7001/tc -create-type Folder -set object_name "Runtime Folder"

Notes
  • The property names used here (e.g., object_name, object_desc, owning_user)
    are OOTB; site schemas vary. Use -props to specify your own list.
  • Property updates respect object protections; on read-only objects, the
    SetProperties call will return partial errors — we print them.
"""

import os
import sys
import argparse
import getpass
from typing import List, Dict, Optional

# --- pythonnet bootstrap ------------------------------------------------------
try:
    import clr  # type: ignore
except Exception:
    print("pythonnet is required. Install with: pip install pythonnet")
    raise

DLL_DIR = os.environ.get("TC_SOA_NET_DIR")
if not DLL_DIR:
    print("Environment variable TC_SOA_NET_DIR is not set; cannot locate Teamcenter .NET client DLLs.")
    sys.exit(2)

# Load all DLLs from the folder (catch-all so we get Core + Loose assemblies)
for fname in os.listdir(DLL_DIR):
    if fname.lower().endswith('.dll'):
        fpath = os.path.join(DLL_DIR, fname)
        try:
            clr.AddReference(fpath)
        except Exception:
            pass

# --- .NET imports -------------------------------------------------------------
from System import Array, String

from Teamcenter.Soa.Client import Connection, ServiceData
from Teamcenter.Soa.Client.Model import ModelObject
from Teamcenter.Soa.Client.Model.Strong import WorkspaceObject, Item

from Teamcenter.Schemas.Soa._2006_03.Exceptions import ServiceException, NotLoadedException

from Teamcenter.Services.Strong.Core import SessionService, DataManagementService
from Teamcenter.Services.Strong.Query import SavedQueryService, QueryInput

# Loose DM for runtime create/update
from Teamcenter.Services.Loose.Core._2006_03 import DataManagement as LooseDM

# --- Session wrapper ----------------------------------------------------------
class TcSession:
    def __init__(self, host: str):
        self.connection = Connection(host)
        self.session = SessionService.getService(self.connection)
        self.dm = DataManagementService.getService(self.connection)
        self.sq = SavedQueryService.getService(self.connection)

    def login(self, user: str, password: str, group: str = 'dba', role: str = 'dba'):
        self.session.Login(user, password, group, role, '', 'Python-RuntimeBO')

    def logout(self):
        try:
            self.session.Logout()
        except Exception:
            pass

    def ensure_properties(self, objs: List[ModelObject], prop_names: List[str]):
        if not objs:
            return
        self.dm.GetProperties(Array[ModelObject](objs), Array[String](prop_names))

# --- Find object helpers ------------------------------------------------------

def find_item_by_id(tc: TcSession, item_id: str) -> Item:
    g = tc.sq.GetSavedQueries()
    target = None
    for q in list(g.Queries):
        if q.Name.endswith("Item ID") or q.Name == "Item ID":
            target = q
            break
    if target is None:
        raise RuntimeError("Saved Query 'Item ID' not found on server")

    qi = QueryInput()
    qi.Query = target
    qi.MaxNumToReturn = 25
    qi.LimitList = Array[ModelObject]([])
    qi.Entries = Array[String](["Item ID"])
    qi.Values  = Array[String]([item_id])
    sresp = tc.sq.ExecuteSavedQueries(Array[QueryInput]([qi]))
    res = sresp.ArrayOfResults[0]
    if res.ObjectUIDS is None or res.ObjectUIDS.Length == 0:
        raise RuntimeError(f"No object found with Item ID '{item_id}'")

    sd = tc.dm.LoadObjects(Array[String](list(res.ObjectUIDS)))
    objs = [sd.GetPlainObject(i) for i in range(sd.sizeOfPlainObjects())]
    for o in objs:
        if isinstance(o, Item):
            return o
    raise RuntimeError("Found objects, but none were Item instances")


def load_by_uid(tc: TcSession, uid: str) -> ModelObject:
    sd = tc.dm.LoadObjects(Array[String]([uid]))
    if sd.sizeOfPlainObjects() == 0:
        raise RuntimeError(f"No object for UID {uid}")
    return sd.GetPlainObject(0)

# --- Runtime (type-agnostic) operations --------------------------------------

def print_runtime_properties(tc: TcSession, obj: ModelObject, prop_names: List[str]):
    try:
        tc.ensure_properties([obj], prop_names)
    except ServiceException:
        pass
    print("\nRuntime properties:")
    for p in prop_names:
        try:
            val = obj.GetPropertyDisplayableValue(p)
        except Exception:
            val = "<not loaded>"
        print(f"  {p}: {val}")


def try_set_string_properties(tc: TcSession, obj: ModelObject, updates: Dict[str, str]):
    if not updates:
        return
    print("\nAttempting SetProperties (loose) …")
    pnvs = []
    for name, value in updates.items():
        pnv = LooseDM.PropertyNameValue()
        pnv.Object = obj
        pnv.PropertyName = name
        pnv.Values = Array[String]([value])
        pnvs.append(pnv)
    try:
        sd: ServiceData = LooseDM.DataManagementService.getService(tc.connection).SetPropertiesNameValue(Array[LooseDM.PropertyNameValue](pnvs))
    except AttributeError:
        # Older/newer sites may use SetProperties with PropertyNameValuesStruct
        try:
            pstructs = []
            for name, value in updates.items():
                s = LooseDM.PropertyNameValuesStruct()
                s.Object = obj
                s.PropertyName = name
                s.StringValues = Array[String]([value])
                pstructs.append(s)
            sd: ServiceData = LooseDM.DataManagementService.getService(tc.connection).SetProperties(Array[LooseDM.PropertyNameValuesStruct](pstructs))
        except Exception as e:
            print("  Could not call a SetProperties variant:", e)
            return
    # Report partial errors if any
    pe = sd.sizeOfPartialErrors()
    if pe:
        print(f"  SetProperties returned {pe} partial error(s)")
    else:
        print("  SetProperties completed without partial errors")


def list_children(tc: TcSession, obj: ModelObject, relation: str = 'contents'):
    print(f"\nListing relation '{relation}':")
    try:
        tc.ensure_properties([obj], [relation])
        kids = list(getattr(obj, relation.capitalize()) if relation == 'contents' else getattr(obj, relation))
    except Exception:
        # Try generic property access by name
        try:
            kids = list(obj.GetPropertyObject(relation))  # may not exist in all versions
        except Exception:
            kids = []
    for k in kids:
        try:
            tc.ensure_properties([k], ["object_string"]) 
            if isinstance(k, WorkspaceObject):
                label = k.GetPropertyDisplayableValue("object_string")
            else:
                label = getattr(k, 'Uid', '<child>')
        except Exception:
            label = getattr(k, 'Uid', '<child>')
        print("  •", label)

# --- Generic create/delete using Loose DM ------------------------------------

def create_runtime_object(tc: TcSession, type_name: str, props: Dict[str, List[str]]):
    svc = LooseDM.DataManagementService.getService(tc.connection)
    ci = LooseDM.CreateIn()
    ci.ClientId = "Py-Runtime-Create"
    ci.ObjectType = type_name
    # Map string→string[]
    from System.Collections.Generic import Dictionary
    from System import String as NetString
    from System import Array as NetArray
    ci.StringProps = Dictionary[NetString, NetArray[NetString]]()
    for k, vlist in props.items():
        ci.StringProps[NetString(k)] = NetArray[NetString](list(map(NetString, vlist)))

    inputs = LooseDM.CreateInput()
    inputs.Data = Array[LooseDM.CreateIn]([ci])
    resp = svc.CreateObjects(Array[LooseDM.CreateInput]([inputs]))
    if resp.ServiceData.sizeOfPartialErrors() > 0:
        raise ServiceException("CreateObjects returned partial errors")
    # Pull created object back generically
    try:
        out0 = resp.Output[0]
        created = out0.Objects[0]
    except Exception:
        # Fallback path (older variants)
        created = resp.Output[0].Object
    return created


def delete_objects(tc: TcSession, objs: List[ModelObject]):
    sd = tc.dm.DeleteObjects(Array[ModelObject](objs))
    if sd.sizeOfPartialErrors() > 0:
        print(f"DeleteObjects had {sd.sizeOfPartialErrors()} partial errors")

# --- CLI ----------------------------------------------------------------------

def parse_args():
    p = argparse.ArgumentParser(description="Runtime Business Object demo (Python port)")
    p.add_argument('-host', default='http://localhost:7001/tc', help='Teamcenter server URL')
    p.add_argument('-user', help='Username (prompt if omitted)')
    p.add_argument('-password', help='Password (prompt if omitted)')

    # Target selection
    group = p.add_mutually_exclusive_group()
    group.add_argument('-item', help='Lookup an Item by Item ID (recommended)')
    group.add_argument('-uid', help='Load an object directly by UID')

    # Read-time property list
    p.add_argument('-props', nargs='*', default=['object_type','object_name','object_desc','owning_user','owning_group','last_mod_date'], help='Property names to read')

    # Update a single property by name
    p.add_argument('-update-prop', nargs=2, metavar=('NAME','VALUE'), help='Update NAME to VALUE on the target object')

    # Generic create/delete path
    p.add_argument('-create-type', help='Create an object of this type using Loose DM (e.g., Folder, Item)')
    p.add_argument('-set', nargs=2, action='append', metavar=('NAME','VALUE'), help='For -create-type: set property NAME to VALUE (repeatable)')
    p.add_argument('--no-delete', action='store_true', help='Keep created object (skip delete)')

    return p.parse_args()


def main():
    args = parse_args()
    user = args.user or input('User name: ')
    pwd  = args.password if args.password is not None else getpass.getpass('Password: ')

    tc = TcSession(args.host)
    created = None
    try:
        tc.login(user, pwd)

        target: Optional[ModelObject] = None
        if args.item:
            target = find_item_by_id(tc, args.item)
        elif args.uid:
            target = load_by_uid(tc, args.uid)

        if target is not None:
            print("Loaded target:")
            try:
                tc.ensure_properties([target], ["object_string"]) 
                print("  ", target.GetPropertyDisplayableValue("object_string"))
            except Exception:
                print("  ", getattr(target, 'Uid', '<object>'))

            # Read runtime properties
            print_runtime_properties(tc, target, args.props)

            # Optional update
            if args.update_prop:
                name, value = args.update_prop
                try_set_string_properties(tc, target, {name: value})
                # Reload the property to reflect change
                tc.ensure_properties([target], [name])
                try:
                    print(f"  After update {name}:", target.GetPropertyDisplayableValue(name))
                except Exception:
                    pass

            # Try listing contents for folders or home folders
            # If target is an Item, list its revisions relation as a demo
            try:
                if isinstance(target, Item):
                    tc.ensure_properties([target], ["revision_list"]) 
                    revs = list(target.Revision_list)
                    print(f"\nRevisions: {len(revs)}")
                    for r in revs[:10]:
                        try:
                            tc.ensure_properties([r], ["object_string"]) 
                            print("  •", r.GetPropertyDisplayableValue("object_string"))
                        except Exception:
                            print("  •", getattr(r, 'Uid', '<rev>'))
                else:
                    list_children(tc, target, relation='contents')
            except Exception:
                pass

        # Optional generic create/delete flow
        if args.create_type:
            props: Dict[str, List[str]] = {}
            if args.set:
                for name, value in args.set:
                    props.setdefault(name, []).append(value)
            else:
                props = { 'object_name': [f"Py {args.create_type} (runtime)"] }
            created = create_runtime_object(tc, args.create_type, props)
            print("\nCreated:")
            try:
                tc.ensure_properties([created], ["object_string","object_type"]) 
                print("  ", created.GetPropertyDisplayableValue("object_string"), f"[{created.GetPropertyDisplayableValue('object_type')}]")
            except Exception:
                print("  ", getattr(created, 'Uid', '<created>'))

            if not args.no_delete:
                delete_objects(tc, [created])
                print("Deleted the created object.")

    except ServiceException as e:
        try:
            print("ServiceException:", e.Message)
        except Exception:
            print("ServiceException:", str(e))
    finally:
        tc.logout()


if __name__ == '__main__':
    main()
