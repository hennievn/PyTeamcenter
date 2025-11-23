"""High-level helpers that mirror the Siemens VendorManagement sample."""

from __future__ import annotations

import logging

import tc_utils  # noqa: F401  # ensure Teamcenter assemblies are registered

import clr  # type: ignore
from System import Array  # type: ignore

clr.AddReference("TcSoaVendorManagementStrong")  # type: ignore
clr.AddReference("TcSoaStrongModelVendorManagement")  # type: ignore

import Teamcenter.Soa.Client.Model as TcModel  # type: ignore
from Teamcenter.Services.Strong.Vendormanagement import VendorManagementService  # type: ignore
import Teamcenter.Services.Strong.Vendormanagement._2007_06.VendorManagement as VMTypes  # type: ignore

LOGGER = logging.getLogger(__name__)


class VendorManagementExample:
    """Python port of the Siemens VendorManagement sample operations."""

    def __init__(self, connection) -> None:
        self._connection = connection
        self._init_strong_types()
        self._service = VendorManagementService.getService(connection)

    def _init_strong_types(self) -> None:
        try:
            TcModel.StrongObjectFactoryVendormanagement.Init()
        except Exception:
            LOGGER.debug("StrongObjectFactoryVendormanagement.Init() failed", exc_info=True)

    # ------------------------------------------------------------------ #
    # API mirroring the VB sample
    # ------------------------------------------------------------------ #
    def create_vendors(self) -> VMTypes.CreateVendorsResponse | None:
        """Create or update a vendor, prompting for the core attributes."""
        LOGGER.info("Running createVendors sample.")
        vendor = VMTypes.VendorProperties()
        vendor.ClientId = "AppX-Test"
        vendor.ItemId = input("Vendor ID: ").strip()
        vendor.Name = input("Vendor Name: ").strip()
        vendor.Type = "Vendor"
        vendor.RevId = input("Vendor Revision ID: ").strip()
        vendor.Description = input("Description: ").strip() or "This is net vendor"
        vendor.RoleType = input("Vendor Role Type (Supplier/Distributor/...): ").strip()
        vendor.CertifiStatus = input("Certification Status (e.g., Gold): ").strip()
        vendor.VendorStatus = input("Vendor Status (Approved/Rejected/...): ").strip()

        response = self._service.CreateOrUpdateVendors(Array[VMTypes.VendorProperties]([vendor]), None, "")
        _log_partial_errors("createOrUpdateVendors", response.ServiceData)
        return response

    def create_bid_packages(self) -> VMTypes.CreateBidPacksResponse | None:
        """Create or update bid packages."""
        LOGGER.info("Running createBidPackages sample.")
        bid = VMTypes.BidPackageProps()
        bid.ClientId = "AppX-Test"
        bid.ItemId = input("Bid Package ID: ").strip()
        bid.Name = input("Bid Package Name: ").strip()
        bid.RevId = input("Bid Package Revision ID: ").strip()
        bid.Type = "BidPackage"

        response = self._service.CreateOrUpdateBidPackages(
            Array[VMTypes.BidPackageProps]([bid]), None, ""
        )
        _log_partial_errors("createOrUpdateBidPackages", response.ServiceData)
        return response

    def create_line_items(self) -> None:
        """Create line items and associate them with a bid package."""
        LOGGER.info("Running createLineItems sample.")
        line = VMTypes.LineItemProps()
        line.Name = input("Line Item Name: ").strip()
        line.Description = input("Line Item Description: ").strip()
        line.Partid = input("Part ID to associate: ").strip()
        qty = input("Quantity (default 2): ").strip()
        line.Quantity = int(qty) if qty else 2
        line.Quote = None
        line.Liccname = input("Line Item Configuration Context Name: ").strip()
        line.Liccdesc = input("LICC Description (optional): ").strip() or ""
        line.ClosureRule = input("Closure Rule (optional): ").strip()
        line.RevRule = input("Revision Rule (optional): ").strip()
        line.VarRule = input("Variant Rule (optional): ").strip()
        line.Viewtype = input("PS View Type (optional): ").strip()

        bid_resp = self.create_bid_packages()
        if not bid_resp or not getattr(bid_resp, "Output", None):
            LOGGER.error("Unable to create bid package required for line items.")
            return
        bid_rev = bid_resp.Output[0].BidPackageRev

        service_data = self._service.CreateOrUpdateLineItems(
            Array[VMTypes.LineItemProps]([line]), bid_rev
        )
        _log_partial_errors("createOrUpdateLineItems", service_data)

    def delete_vendor_roles(self) -> None:
        """Delete vendor roles associated with a vendor revision."""
        LOGGER.info("Running deleteVendorRoles sample.")
        vendor = VMTypes.VendorProperties()
        vendor.ClientId = "AppX-Test"
        vendor.ItemId = input("Vendor ID: ").strip()
        vendor.Type = "Vendor"
        vendor.RevId = input("Vendor Revision ID: ").strip()
        vendor.RoleType = input("Vendor Role Type to delete: ").strip()

        service_data = self._service.DeleteVendorRoles(Array[VMTypes.VendorProperties]([vendor]))
        _log_partial_errors("deleteVendorRoles", service_data)

    def delete_vendors(self) -> None:
        """Delete vendors and their associated revisions/roles."""
        LOGGER.info("Running deleteVendors sample.")
        vendor = VMTypes.VendorProperties()
        vendor.ClientId = "AppX-Test"
        vendor.ItemId = input("Vendor ID: ").strip()
        vendor.Type = "Vendor"
        vendor.RevId = input("Vendor Revision ID: ").strip()

        service_data = self._service.DeleteVendors(Array[VMTypes.VendorProperties]([vendor]))
        _log_partial_errors("deleteVendors", service_data)

    def create_parts(self) -> VMTypes.CreateVendorPartsResponse | None:
        """Create vendor parts (commercial or manufacturer)."""
        LOGGER.info("Running createParts sample.")
        part = VMTypes.VendorPartProperties()
        part.ClientId = "AppX-Test"
        part.PartId = input("Part ID: ").strip()
        part.Name = input("Part Name: ").strip()
        part_type = input("Part Type (CommercialPart/ManufacturerPart) [CommercialPart]: ").strip()
        part.Type = part_type or "CommercialPart"
        part.RevId = input("Part Revision ID: ").strip()
        part.Description = input("Part Description: ").strip()
        part.Vendorid = input("Vendor ID (optional for CommercialPart): ").strip()
        part.Uom = None
        part.Makebuy = 2
        part.IsDesignReq = True

        if part.Type == "ManufacturerPart":
            part.Commercialpartid = input("Commercial Part ID: ").strip()
            part.Commercialpartrevid = input("Commercial Part Revision ID: ").strip()

        response = self._service.CreateOrUpdateVendorParts(
            Array[VMTypes.VendorPartProperties]([part]), None, ""
        )
        _log_partial_errors("createOrUpdateVendorParts", response.ServiceData)
        return response


def _log_partial_errors(operation: str, service_data) -> None:
    """Write partial-error counts (if any) to the log."""
    if service_data is None:
        return
    size = getattr(service_data, "SizeOfPartialErrors", 0)
    if callable(size):
        size = size()
    if size:
        LOGGER.warning("%s returned %s partial error(s).", operation, size)
