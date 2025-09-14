#!/usr/bin/env python3
"""
Python port of Siemens Teamcenter sample "VendorManagement" (.NET)

Implements the same operations as the C# sample:
  1) createVendors → CreateOrUpdateVendors
  2) createBidPackages → CreateOrUpdateBidPackages
  3) createLineItems → CreateOrUpdateLineItems (creates/ensures BidPackage first)
  4) deleteVendorRoles → DeleteVendorRoles
  5) deleteVendors → DeleteVendors
  6) createParts → CreateOrUpdateVendorParts (CommercialPart or ManufacturerPart)

Prereqs
  • Python 3.9+
  • pythonnet → pip install pythonnet
  • Teamcenter SOA .NET client assemblies installed locally
      set TC_SOA_NET_DIR to the netstandard2.0 DLL folder
  • Teamcenter web tier & Pool Manager running (default host http://localhost:7001/tc)

Usage examples
  set TC_SOA_NET_DIR=C:\Siemens\Teamcenter\soa_client\bin\netstandard2.0
  # Login & create a vendor
  python vendor_management_demo.py -host http://localhost:7001/tc -user infodba -op create-vendor \
      --vendor-id V0001 --vendor-name "Acme Corp" --vendor-rev A \
      --role-type Preferred --cert-status Gold --vendor-status Approved

  # Create a bid package
  python vendor_management_demo.py -host http://localhost:7001/tc -user infodba -op create-bid \
      --bid-id BP0001 --bid-name "Q4 Fasteners" --bid-rev A

  # Create a line item under a bid package (creates/updates the bid package first)
  python vendor_management_demo.py -host http://localhost:7001/tc -user infodba -op create-line \
      --bid-id BP0001 --bid-name "Q4 Fasteners" --bid-rev A \
      --line-name "M6 Screw" --line-desc "Stainless" --part-id 000123 \
      --licc-name "M6 Config" --quantity 2

  # Delete a vendor role
  python vendor_management_demo.py -host http://localhost:7001/tc -user infodba -op delete-role \
      --vendor-id V0001 --vendor-rev A --role-type Preferred

  # Delete a vendor
  python vendor_management_demo.py -host http://localhost:7001/tc -user infodba -op delete-vendor \
      --vendor-id V0001 --vendor-rev A

  # Create a commercial part
  python vendor_management_demo.py -host http://localhost:7001/tc -user infodba -op create-part \
      --part-id CP-100 --part-name "Bolt M6x20" --part-type CommercialPart --part-rev A \
      --description "DIN 933" --makebuy 2

  # Create a manufacturer part (requires a vendor & a commercial part linkage)
  python vendor_management_demo.py -host http://localhost:7001/tc -user infodba -op create-part \
      --part-id MP-200 --part-name "Bolt M6x20 - MakerX" --part-type ManufacturerPart --part-rev A \
      --description "MakerX variant" --vendor-id V0001 \
      --commercial-part-id CP-100 --commercial-part-rev A
"""

import os
import sys
import argparse
import getpass

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

# Load all DLLs in the folder to pick up Strong Vendormanagement assemblies
for fname in os.listdir(DLL_DIR):
    if fname.lower().endswith('.dll'):
        try:
            clr.AddReference(os.path.join(DLL_DIR, fname))
        except Exception:
            pass

# --- .NET imports -------------------------------------------------------------
from System import Array, String

from Teamcenter.Soa.Client import Connection
from Teamcenter.Schemas.Soa._2006_03.Exceptions import ServiceException

from Teamcenter.Services.Strong.Core import SessionService

# Vendor management strong service & DTOs
from Teamcenter.Services.Strong.Vendormanagement import (
    VendorManagementService,
    VendorProperties,
    CreateVendorsResponse,
    BidPackageProps,
    CreateBidPacksResponse,
    LineItemProps,
    CreateVendorPartsResponse,
    VendorPartProperties,
)

# The vendor strong object factory (register cfg types)
try:
    import Teamcenter.Soa.Client.Model.StrongObjectFactoryVendormanagement as VMStrongFactory  # type: ignore
    VMStrongFactory.Init()
except Exception:
    pass

# --- Session helper -----------------------------------------------------------
class TcSession:
    def __init__(self, host: str):
        self.connection = Connection(host)
        self.session = SessionService.getService(self.connection)

    def login(self, user: str, password: str, group: str = 'dba', role: str = 'dba'):
        self.session.Login(user, password, group, role, '', 'Python-VendorMgmt')

    def logout(self):
        try:
            self.session.Logout()
        except Exception:
            pass

# --- Operations (1:1 with the C# sample) -------------------------------------

def op_create_vendor(tc: TcSession, vendor_id: str, vendor_name: str, vendor_rev: str,
                     role_type: str = '', cert_status: str = '', vendor_status: str = ''):
    svc = VendorManagementService.getService(tc.connection)
    vp = VendorProperties()
    vp.ClientId = 'Py-VM'
    vp.ItemId = vendor_id
    vp.Name = vendor_name
    vp.Type = 'Vendor'
    vp.RevId = vendor_rev
    vp.Description = 'Vendor created via Python port of VendorManagement sample'
    if role_type:
        vp.RoleType = role_type
    if cert_status:
        vp.CertifiStatus = cert_status
    if vendor_status:
        vp.VendorStatus = vendor_status
    resp: CreateVendorsResponse = svc.CreateOrUpdateVendors(Array[VendorProperties]([vp]), None, '')
    if resp.ServiceData.sizeOfPartialErrors() > 0:
        print(f"CreateOrUpdateVendors returned {resp.ServiceData.sizeOfPartialErrors()} partial error(s)")


def op_create_bid(tc: TcSession, bid_id: str, bid_name: str, bid_rev: str):
    svc = VendorManagementService.getService(tc.connection)
    bp = BidPackageProps()
    bp.ClientId = 'Py-VM'
    bp.ItemId = bid_id
    bp.Name = bid_name
    bp.RevId = bid_rev
    bp.Type = 'BidPackage'
    resp: CreateBidPacksResponse = svc.CreateOrUpdateBidPackages(Array[BidPackageProps]([bp]), None, '')
    if resp.ServiceData.sizeOfPartialErrors() > 0:
        print(f"CreateOrUpdateBidPackages returned {resp.ServiceData.sizeOfPartialErrors()} partial error(s)")
    return resp


def op_create_line(tc: TcSession,
                   bid_id: str, bid_name: str, bid_rev: str,
                   line_name: str, line_desc: str = '',
                   part_id: str = '', quantity: int = 1,
                   licc_name: str = '', licc_desc: str = '',
                   view_type: str = '', rev_rule: str = '', var_rule: str = '', closure_rule: str = ''):
    svc = VendorManagementService.getService(tc.connection)

    # Ensure/create the bid package first (as in the C# sample)
    bresp = op_create_bid(tc, bid_id, bid_name, bid_rev)
    try:
        bid_rev_obj = bresp.Output[0].BidPackageRev
    except Exception:
        bid_rev_obj = None

    li = LineItemProps()
    li.ClientId = 'Py-VM'
    li.Name = line_name
    if line_desc:
        li.Description = line_desc
    if part_id:
        li.Partid = part_id
    # Defaults to match sample behaviour
    li.Quantity = quantity
    li.Quote = None
    if licc_name:
        li.Liccname = licc_name
    if licc_desc:
        li.Liccdesc = licc_desc
    li.Viewtype = view_type or ''
    li.RevRule = rev_rule or ''
    li.VarRule = var_rule or ''
    li.ClosureRule = closure_rule or ''

    sd = svc.CreateOrUpdateLineItems(Array[LineItemProps]([li]), bid_rev_obj)
    if sd.sizeOfPartialErrors() > 0:
        print(f"CreateOrUpdateLineItems returned {sd.sizeOfPartialErrors()} partial error(s)")


def op_delete_role(tc: TcSession, vendor_id: str, vendor_rev: str, role_type: str):
    svc = VendorManagementService.getService(tc.connection)
    vp = VendorProperties()
    vp.ClientId = 'Py-VM'
    vp.ItemId = vendor_id
    vp.RevId = vendor_rev
    vp.RoleType = role_type
    sd = svc.DeleteVendorRoles(Array[VendorProperties]([vp]))
    if sd.sizeOfPartialErrors() > 0:
        print(f"DeleteVendorRoles returned {sd.sizeOfPartialErrors()} partial error(s)")


def op_delete_vendor(tc: TcSession, vendor_id: str, vendor_rev: str):
    svc = VendorManagementService.getService(tc.connection)
    vp = VendorProperties()
    vp.ClientId = 'Py-VM'
    vp.ItemId = vendor_id
    vp.RevId = vendor_rev
    sd = svc.DeleteVendors(Array[VendorProperties]([vp]))
    if sd.sizeOfPartialErrors() > 0:
        print(f"DeleteVendors returned {sd.sizeOfPartialErrors()} partial error(s)")


def op_create_part(tc: TcSession,
                   part_id: str, part_name: str, part_type: str, part_rev: str,
                   description: str = '', vendor_id: str = '',
                   commercial_part_id: str = '', commercial_part_rev: str = '',
                   is_design_req: bool = True, uom: str = '', makebuy: int = 2):
    svc = VendorManagementService.getService(tc.connection)
    pp = VendorPartProperties()
    pp.ClientId = 'Py-VM'
    pp.PartId = part_id
    pp.Name = part_name
    pp.Type = part_type  # "CommercialPart" or "ManufacturerPart"
    pp.RevId = part_rev
    pp.Description = description or ''
    if vendor_id:
        pp.Vendorid = vendor_id
    # Defaults from the sample
    pp.Uom = uom if uom else None
    pp.Makebuy = makebuy
    pp.IsDesignReq = is_design_req
    if part_type == 'ManufacturerPart':
        pp.Commercialpartid = commercial_part_id
        pp.Commercialpartrevid = commercial_part_rev
    resp: CreateVendorPartsResponse = svc.CreateOrUpdateVendorParts(Array[VendorPartProperties]([pp]), None, '')
    if resp.ServiceData.sizeOfPartialErrors() > 0:
        print(f"CreateOrUpdateVendorParts returned {resp.ServiceData.sizeOfPartialErrors()} partial error(s)")

# --- CLI ----------------------------------------------------------------------

def build_parser():
    p = argparse.ArgumentParser(description='Teamcenter VendorManagement sample (Python port)')
    p.add_argument('-host', default='http://localhost:7001/tc', help='Teamcenter server URL')
    p.add_argument('-user', help='Username (prompt if omitted)')
    p.add_argument('-password', help='Password (prompt if omitted)')

    sub = p.add_subparsers(dest='op', required=True, help='Operation to perform')

    s = sub.add_parser('create-vendor', help='Create or update a Vendor')
    s.add_argument('--vendor-id', required=True)
    s.add_argument('--vendor-name', required=True)
    s.add_argument('--vendor-rev', required=True)
    s.add_argument('--role-type', default='')
    s.add_argument('--cert-status', default='')
    s.add_argument('--vendor-status', default='')

    s = sub.add_parser('create-bid', help='Create or update a BidPackage')
    s.add_argument('--bid-id', required=True)
    s.add_argument('--bid-name', required=True)
    s.add_argument('--bid-rev', required=True)

    s = sub.add_parser('create-line', help='Create or update LineItems under a BidPackage')
    s.add_argument('--bid-id', required=True)
    s.add_argument('--bid-name', required=True)
    s.add_argument('--bid-rev', required=True)
    s.add_argument('--line-name', required=True)
    s.add_argument('--line-desc', default='')
    s.add_argument('--part-id', default='')
    s.add_argument('--quantity', type=int, default=1)
    s.add_argument('--licc-name', default='')
    s.add_argument('--licc-desc', default='')
    s.add_argument('--view-type', default='')
    s.add_argument('--rev-rule', default='')
    s.add_argument('--var-rule', default='')
    s.add_argument('--closure-rule', default='')

    s = sub.add_parser('delete-role', help='Delete a VendorRole from a VendorRevision')
    s.add_argument('--vendor-id', required=True)
    s.add_argument('--vendor-rev', required=True)
    s.add_argument('--role-type', required=True)

    s = sub.add_parser('delete-vendor', help='Delete a Vendor and associated Revisions/Roles')
    s.add_argument('--vendor-id', required=True)
    s.add_argument('--vendor-rev', required=True)

    s = sub.add_parser('create-part', help='Create a CommercialPart or ManufacturerPart')
    s.add_argument('--part-id', required=True)
    s.add_argument('--part-name', required=True)
    s.add_argument('--part-type', choices=['CommercialPart','ManufacturerPart'], required=True)
    s.add_argument('--part-rev', required=True)
    s.add_argument('--description', default='')
    s.add_argument('--vendor-id', default='')
    s.add_argument('--commercial-part-id', default='')
    s.add_argument('--commercial-part-rev', default='')
    s.add_argument('--is-design-req', action='store_true', default=True)
    s.add_argument('--no-design-req', dest='is_design_req', action='store_false')
    s.add_argument('--uom', default='')
    s.add_argument('--makebuy', type=int, default=2)

    return p


def main():
    parser = build_parser()
    args = parser.parse_args()
    user = args.user or input('User name: ')
    pwd = args.password if args.password is not None else getpass.getpass('Password: ')

    tc = TcSession(args.host)
    try:
        tc.login(user, pwd)
        if args.op == 'create-vendor':
            op_create_vendor(tc, args.vendor_id, args.vendor_name, args.vendor_rev,
                             args.role_type, args.cert_status, args.vendor_status)
        elif args.op == 'create-bid':
            op_create_bid(tc, args.bid_id, args.bid_name, args.bid_rev)
        elif args.op == 'create-line':
            op_create_line(tc, args.bid_id, args.bid_name, args.bid_rev,
                           args.line_name, args.line_desc, args.part_id, args.quantity,
                           args.licc_name, args.licc_desc, args.view_type, args.rev_rule,
                           args.var_rule, args.closure_rule)
        elif args.op == 'delete-role':
            op_delete_role(tc, args.vendor_id, args.vendor_rev, args.role_type)
        elif args.op == 'delete-vendor':
            op_delete_vendor(tc, args.vendor_id, args.vendor_rev)
        elif args.op == 'create-part':
            op_create_part(tc, args.part_id, args.part_name, args.part_type,
                           args.part_rev, args.description, args.vendor_id,
                           args.commercial_part_id, args.commercial_part_rev,
                           args.is_design_req, args.uom, args.makebuy)
        else:
            parser.error('Unknown operation')
    except ServiceException as e:
        try:
            print('ServiceException:', e.Message)
        except Exception:
            print('ServiceException:', str(e))
    finally:
        tc.logout()


if __name__ == '__main__':
    main()
