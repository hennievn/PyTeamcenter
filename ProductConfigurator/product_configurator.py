#!/usr/bin/env python3
"""
Python port of Siemens Teamcenter sample "ProductConfigurator" (.NET / VB)

Feature parity with the VB sample (as shipped in ProductConfigurator.zip):
  1) Login via SOA .NET client
  2) Resolve a Product Item by item_id
  3) Obtain a Cfg0ConfiguratorPerspective for that product
  4) Call ConfiguratorManagementService.GetVariability(perspective, keyValuePairs)
  5) Print a compact dump of families & values from the perspective

This port is defensive about Teamcenter release namespaces (e.g., _2022_06 vs _2024_06)
by dynamically resolving the correct Cfg0 service module at runtime.

Prereqs
  • Python 3.9+
  • pythonnet → pip install pythonnet
  • Teamcenter SOA .NET client assemblies installed locally
      set TC_SOA_NET_DIR to the folder with the netstandard2.0 DLLs
  • Teamcenter web tier & FMS running (default host http://localhost:7001/tc)

Usage
  set TC_SOA_NET_DIR=<path-to-\soa_client\bin\netstandard2.0>
  python product_configurator_demo.py -host http://localhost:7001/tc -item 030989

Notes
  • This example sticks to username/password login to match the VB sample. Wire in SSO
    if your site requires it.
  • The code attempts multiple well-known operation names for retrieving the perspective
    because these names can differ slightly across TC versions. If none match, the script
    reports available methods on the service type to help you adjust one line.
"""

import os
import sys
import getpass
import argparse
from typing import List, Optional
from importlib import import_module

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

# Load all DLLs in the folder to catch core + cfg0 assemblies regardless of exact names
for fname in os.listdir(DLL_DIR):
    if fname.lower().endswith('.dll'):
        try:
            clr.AddReference(os.path.join(DLL_DIR, fname))
        except Exception:
            # benign if not a .NET assembly
            pass

# --- .NET imports -------------------------------------------------------------
from System import Array, String

from Teamcenter.Soa.Client import Connection
from Teamcenter.Schemas.Soa._2006_03.Exceptions import ServiceException, NotLoadedException

from Teamcenter.Services.Strong.Core import SessionService, DataManagementService
from Teamcenter.Services.Strong.Query import SavedQueryService, QueryInput

from Teamcenter.Soa.Client.Model import ModelObject
from Teamcenter.Soa.Client.Model.Strong import (
    Item,
    WorkspaceObject,
)

# Try to ensure Strong object factories (core + cfg0) are initialized
try:
    import Teamcenter.Soa.Client.Model.StrongObjectFactory as StrongFactory  # type: ignore
    StrongFactory.Init()
except Exception:
    pass
try:
    # Some TC versions generate a factory module for cfg0 types
    import Teamcenter.Soa.Client.Model.StrongObjectFactoryCfg0configurator as StrongFactoryCfg  # type: ignore
    StrongFactoryCfg.Init()
except Exception:
    pass

# --- Utility: find the configurator service module for the active TC version --

def _find_cfg0_module() -> Optional[object]:
    """Return the versioned python module providing ConfiguratorManagement symbols."""
    bases = [
        "Cfg0.Services.Strong.Configurator",
        "Cfg0.Services.Internal.Strong.Configurator",
    ]
    versions = [
        "_2025_06", "_2025_03", "_2024_12", "_2024_06", "_2024_03",
        "_2023_12", "_2023_06", "_2023_03", "_2022_12", "_2022_06",
        "",  # non-versioned fallback
    ]
    for base in bases:
        # Try bare base first for types like ConfiguratorManagementService
        try:
            return import_module(base)
        except Exception:
            pass
        for v in versions:
            modname = f"{base}.{v.strip('.')}.ConfiguratorManagement" if v else f"{base}.ConfiguratorManagement"
            try:
                return import_module(modname)
            except Exception:
                continue
    return None

CFG0_MOD = _find_cfg0_module()
if CFG0_MOD is None:
    print("Could not import a Cfg0 ConfiguratorManagement module. Ensure cfg0 strong assemblies are present in TC_SOA_NET_DIR.")
    sys.exit(2)

# Pull service class if available at top-level module
ConfiguratorManagementService = getattr(CFG0_MOD, 'ConfiguratorManagementService', None)
if ConfiguratorManagementService is None:
    # Some versions expose the service class on the parent namespace
    try:
        parent = import_module("Cfg0.Services.Strong.Configurator")
        ConfiguratorManagementService = getattr(parent, 'ConfiguratorManagementService')
    except Exception:
        pass
if ConfiguratorManagementService is None:
    print("Could not resolve ConfiguratorManagementService in cfg0 module.")
    sys.exit(2)

# Attempt to locate a KeyValuePair type for GetVariability signature (versioned)
KeyValuePair = getattr(CFG0_MOD, 'KeyValuePair', None)
if KeyValuePair is None:
    # Try a nested versioned namespace
    # e.g., Cfg0.Services.Strong.Configurator._2022_06.ConfiguratorManagement.KeyValuePair
    candidates = [
        'Cfg0.Services.Strong.Configurator._2025_06.ConfiguratorManagement',
        'Cfg0.Services.Strong.Configurator._2024_06.ConfiguratorManagement',
        'Cfg0.Services.Strong.Configurator._2023_12.ConfiguratorManagement',
        'Cfg0.Services.Strong.Configurator._2022_06.ConfiguratorManagement',
    ]
    for c in candidates:
        try:
            m = import_module(c)
            KeyValuePair = getattr(m, 'KeyValuePair')
            break
        except Exception:
            continue

# --- Session wrapper ----------------------------------------------------------
class TcSession:
    def __init__(self, host: str):
        self.connection = Connection(host)
        self.session = SessionService.getService(self.connection)
        self.dm = DataManagementService.getService(self.connection)
        self.sq = SavedQueryService.getService(self.connection)

    def login(self, user: str, password: str, group: str = 'dba', role: str = 'dba'):
        self.session.Login(user, password, group, role, '', 'Python-Configurator')

    def logout(self):
        try:
            self.session.Logout()
        except Exception:
            pass

    # Convenience to load properties
    def ensure_properties(self, objs: List[ModelObject], prop_names: List[str]):
        if not objs:
            return
        self.dm.GetProperties(Array[ModelObject](objs), Array[String](prop_names))

# --- Core steps mirroring the VB sample --------------------------------------

def find_item_by_id(tc: TcSession, item_id: str) -> Item:
    """Find an Item by ID.
    Uses Saved Query 'Item ID' as a robust cross-version approach.
    """
    # Locate the 'Item ID' saved query
    g = tc.sq.GetSavedQueries()
    target = None
    for q in list(g.Queries):
        if q.Name in ("Item ID", "General\n.. Item ID", "General... Item ID") or q.Name.endswith("Item ID"):
            target = q
            break
    if target is None:
        raise RuntimeError("Saved Query 'Item ID' not found on server")

    qi = QueryInput()
    qi.Query = target
    qi.MaxNumToReturn = 25
    qi.LimitList = Array[ModelObject]([])
    qi.Entries = Array[String](["Item ID"])
    qi.Values = Array[String]([item_id])
    sresp = tc.sq.ExecuteSavedQueries(Array[QueryInput]([qi]))
    res = sresp.ArrayOfResults[0]
    if res.ObjectUIDS is None or res.ObjectUIDS.Length == 0:
        raise RuntimeError(f"No item found with ID '{item_id}'")

    sd = tc.dm.LoadObjects(Array[String](list(res.ObjectUIDS)))
    objs = [sd.GetPlainObject(i) for i in range(sd.sizeOfPlainObjects())]
    # Return the first Item
    for o in objs:
        if isinstance(o, Item):
            return o
    # If not strictly typed, try to cast by type name
    for o in objs:
        try:
            if o.TypeObject and o.TypeObject.Name and 'Item' in o.TypeObject.Name:
                return o
        except Exception:
            pass
    raise RuntimeError("Item not found in loaded objects")


def get_configurator_perspective(tc: TcSession, product_item: Item):
    """Obtain a Cfg0ConfiguratorPerspective for the given product item.
    Tries several common operation names across TC releases.
    """
    svc = ConfiguratorManagementService.getService(tc.connection)
    candidates = [
        'GetConfiguratorPerspective',
        'GetPerspective',
        'GetOrCreatePerspective',
        'CreatePerspectiveForProduct',
        'GetPerspectiveForProduct',
    ]
    for name in candidates:
        fn = getattr(svc, name, None)
        if fn is None:
            continue
        try:
            return fn(product_item)
        except TypeError:
            # Some variants have additional optional arguments; try with None placeholders
            try:
                return fn(product_item, None)
            except Exception:
                pass
        except ServiceException as e:
            raise
        except Exception:
            continue
    # If we got here, dump available methods to help the user map the correct one
    avail = [m for m in dir(svc) if not m.startswith('_')]
    raise RuntimeError(f"Could not locate a perspective method on ConfiguratorManagementService. Available methods: {avail}")


def get_variability(tc: TcSession, perspective) -> object:
    """Call GetVariability(perspective, keyValuePairs[]) and return the response."""
    svc = ConfiguratorManagementService.getService(tc.connection)
    kv_array = Array[KeyValuePair]([]) if KeyValuePair is not None else Array[object]([])
    # Some releases expose GetVariability on a versioned sub-namespace; try direct first
    try:
        return svc.GetVariability(perspective, kv_array)
    except AttributeError:
        # Walk methods to find a likely candidate
        for name in dir(svc):
            if name.lower() == 'getvariability':
                return getattr(svc, name)(perspective, kv_array)
        raise


def dump_perspective(tc: TcSession, perspective) -> None:
    """Load and print families and values from the perspective object."""
    # Load the interesting properties
    wanted = ["cfg0PublicFamilies", "cfg0PublicValues", "cfg0PrivateValues"]
    try:
        tc.ensure_properties([perspective], wanted)
    except ServiceException:
        pass

    print("\nConfigurator Perspective:")
    try:
        if isinstance(perspective, WorkspaceObject):
            tc.ensure_properties([perspective], ["object_string"])  # best-effort label
            print("  ", perspective.GetPropertyDisplayableValue("object_string"))
    except Exception:
        pass

    # Families
    try:
        fams = list(perspective.Cfg0PublicFamilies)
    except Exception:
        fams = []
    print(f"\nPublic Families: {len(fams)}")
    for f in fams:
        try:
            tc.ensure_properties([f], ["object_string", "cfg0ValueDataType", "cfg0IsMultiselect", "cfg0HasFreeFormValues"])  
        except Exception:
            pass
        try:
            name = f.GetPropertyDisplayableValue("object_string")
        except Exception:
            name = getattr(f, 'Uid', '<unknown>')
        try:
            dt = f.GetPropertyDisplayableValue("cfg0ValueDataType")
        except Exception:
            dt = "?"
        try:
            multi = f.GetPropertyDisplayableValue("cfg0IsMultiselect")
        except Exception:
            multi = "?"
        try:
            free = f.GetPropertyDisplayableValue("cfg0HasFreeFormValues")
        except Exception:
            free = "?"
        print(f"  - {name}  (datatype={dt}, multiselect={multi}, freeform={free})")

    # Values (public)
    try:
        vals = list(perspective.Cfg0PublicValues)
    except Exception:
        vals = []
    print(f"\nPublic Values: {len(vals)}")
    for v in vals[:100]:
        try:
            tc.ensure_properties([v], ["object_string"])  
            print("  •", v.GetPropertyDisplayableValue("object_string"))
        except Exception:
            print("  •", getattr(v, 'Uid', '<value>'))

    # Private values (if any)
    try:
        priv = list(perspective.Cfg0PrivateValues)
    except Exception:
        priv = []
    if priv:
        print(f"\nPrivate Values: {len(priv)}")
        for v in priv[:50]:
            try:
                tc.ensure_properties([v], ["object_string"])  
                print("  •", v.GetPropertyDisplayableValue("object_string"))
            except Exception:
                print("  •", getattr(v, 'Uid', '<priv>'))

# --- CLI ----------------------------------------------------------------------

def parse_args():
    p = argparse.ArgumentParser(description="ProductConfigurator sample (Python port)")
    p.add_argument('-host', default='http://localhost:7001/tc', help='Teamcenter server URL')
    p.add_argument('-user', help='Username (prompt if omitted)')
    p.add_argument('-password', help='Password (prompt if omitted)')
    p.add_argument('-item', default='030989', help='Product Item ID to load')
    return p.parse_args()


def main():
    args = parse_args()
    user = args.user or input('User name: ')
    pwd = args.password if args.password is not None else getpass.getpass('Password: ')

    tc = TcSession(args.host)
    try:
        tc.login(user, pwd)
        item = find_item_by_id(tc, args.item)
        print("Found Item:")
        try:
            tc.ensure_properties([item], ["object_string", "item_id"])  
            print("  ", item.GetPropertyDisplayableValue("object_string"))
        except Exception:
            print("  ", getattr(item, 'Uid', '<item>'))

        perspective = get_configurator_perspective(tc, item)
        dump_perspective(tc, perspective)

        resp = get_variability(tc, perspective)
        print("\nGetVariability() call completed.")
        # Optionally, reflect key fields from the response object if present
        try:
            # Many versions return a type with a 'ServiceData' property and maybe 'Families'/'Values'
            sd = getattr(resp, 'ServiceData', None)
            if sd is not None:
                pe = sd.sizeOfPartialErrors()
                if pe:
                    print(f"  Response had partial errors: {pe}")
        except Exception:
            pass

    except ServiceException as e:
        try:
            print("ServiceException:", e.Message)
        except Exception:
            print("ServiceException:", str(e))
    finally:
        tc.logout()


if __name__ == '__main__':
    main()
