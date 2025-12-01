"""Data management helpers mirroring the Siemens sample."""

from __future__ import annotations

import logging

import tc_utils  # noqa: F401

import clr  # type: ignore

clr.AddReference("TcSoaCoreStrong")  # type: ignore

from System import Array, String, Int32  # type: ignore
from System.Collections import Hashtable  # type: ignore

from Teamcenter.Services.Strong.Core import DataManagementService  # type: ignore
from Teamcenter.Services.Strong.Core._2006_03.DataManagement import (  # type: ignore
    CreateItemsOutput,
    ExtendedAttributes,
    GenerateRevisionIdsProperties,
    GenerateItemIdsAndInitialRevisionIdsProperties,
    ItemIdsAndInitialRevisionIds,
    ItemProperties,
)  # type: ignore
from Teamcenter.Services.Strong.Core._2007_01.DataManagement import FormInfo  # type: ignore
from Teamcenter.Services.Strong.Core._2008_06.DataManagement import ReviseInfo  # type: ignore
from Teamcenter.Soa.Client.Model import ModelObject  # type: ignore
from Teamcenter.Soa.Exceptions import NotLoadedException  # type: ignore
from Teamcenter.Schemas.Soa._2006_03.Exceptions import ServiceException  # type: ignore

LOGGER = logging.getLogger(__name__)


class DataManagementExample:
    """
    Encapsulates the create/revise/delete workflow from the sample.

    This class demonstrates the usage of the `DataManagementService` to perform
    lifecycle operations on Items and ItemRevisions. It mirrors the functionality
    of the `DataManagement` class in the C# HelloTeamcenter sample.
    """

    def __init__(self, connection) -> None:
        self._connection = connection
        self._service = DataManagementService.getService(connection)

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def create_revise_and_delete(self) -> None:
        """
        Perform the sample's end-to-end item lifecycle operations.

        Sequence:
        1.  **Generate IDs**: Reserves Item and Revision IDs for new objects.
        2.  **Create Items**: Creates `Item` objects using the reserved IDs.
        3.  **Generate Revision IDs**: Reserves new Revision IDs for the created items.
        4.  **Revise**: Creates new `ItemRevision`s from the existing ones.
        5.  **Delete**: Deletes the created Items to clean up.
        """
        LOGGER.info("Generating item IDs...")
        item_ids = self.generate_item_ids(3, "Item")
        LOGGER.info("Creating %s items...", len(item_ids))
        created = self.create_items(item_ids, "Item")

        items = [entry.Item for entry in created]
        item_revs = [entry.ItemRev for entry in created]

        LOGGER.info("Reserving revision IDs...")
        revision_ids = self.generate_revision_ids(items)
        LOGGER.info("Revising items...")
        self.revise_items(revision_ids, item_revs)
        LOGGER.info("Deleting items...")
        self.delete_items(items)
        LOGGER.info("Data management sequence completed.")

    # ------------------------------------------------------------------ #
    # Implementation helpers
    # ------------------------------------------------------------------ #
    def generate_item_ids(
        self, number_of_ids: int, item_type: str
    ) -> list[ItemIdsAndInitialRevisionIds]:
        """
        Request a batch of new item and initial revision IDs from Teamcenter.

        Wraps `DataManagementService.GenerateItemIdsAndInitialRevisionIds`.

        Args:
            number_of_ids: The number of IDs to generate.
            item_type: The type of Item (e.g., "Item").

        Returns:
            A list of `ItemIdsAndInitialRevisionIds` structures containing the new IDs.
        """
        props = GenerateItemIdsAndInitialRevisionIdsProperties()
        props.Count = number_of_ids
        props.ItemType = item_type
        props.Item = None

        response = self._service.GenerateItemIdsAndInitialRevisionIds(
            Array[GenerateItemIdsAndInitialRevisionIdsProperties]([props])
        )
        _check_service_data(response.ServiceData, "GenerateItemIdsAndInitialRevisionIds")

        mapping = response.OutputItemIdsAndInitialRevisionIds
        ids: list[ItemIdsAndInitialRevisionIds] = []
        for key in mapping.Keys:
            values = mapping[key]
            if values is None:
                LOGGER.warning("GenerateItemIds returned no values for key %s.", key)
                continue
            try:
                for val in values:
                    ids.append(val)
            except TypeError:
                LOGGER.warning("Unexpected ID container type for key %s: %r", key, values)
        return ids

    def create_items(
        self, ids: list[ItemIdsAndInitialRevisionIds], item_type: str
    ) -> list[CreateItemsOutput]:
        """
        Create items using the provided ID/revision pairs.

        Wraps `DataManagementService.CreateItems`.
        Also uses `GetItemCreationRelatedInfo` to determine form types and
        `CreateOrUpdateForms` to create the Master and Revision forms if required.

        Args:
            ids: List of ID structures generated by `generate_item_ids`.
            item_type: The type of Item to create.

        Returns:
            A list of `CreateItemsOutput` structures containing the created objects.
        """
        related = self._service.GetItemCreationRelatedInfo(item_type, None)
        _check_service_data(related.ServiceData, "GetItemCreationRelatedInfo")

        form_types = [info.FormType for info in getattr(related, "FormAttrs", [])]

        item_props = []
        for entry in ids:
            forms = []
            if len(form_types) >= 2:
                # The sample mirrors ClientX by creating form instances for master/revision.
                forms = self.create_forms(
                    entry.NewItemId,
                    form_types[0],
                    entry.NewRevId,
                    form_types[1],
                    None,
                    False,
                )

            props = ItemProperties()
            props.ClientId = "AppX-Test"
            props.ItemId = entry.NewItemId
            props.RevId = entry.NewRevId
            props.Name = "AppX-Test"
            props.Type = item_type
            props.Description = "Test Item for the SOA AppX sample application."
            props.Uom = ""

            if forms:
                try:
                    self._service.GetProperties(
                        Array[ModelObject](forms),
                        Array[String](["project_id"]),
                    )
                    project_prop = forms[0].GetProperty("project_id")
                except NotLoadedException:
                    project_prop = None
                except Exception:
                    project_prop = None

                if not project_prop or not getattr(project_prop, "StringValue", None):
                    # Inject a default project_id extended attribute to satisfy the sample's schema.
                    ext = ExtendedAttributes()
                    ext.Attributes = Hashtable()
                    ext.ObjectType = form_types[0]
                    ext.Attributes["project_id"] = "project_id"
                    props.ExtendedAttributes = Array[ExtendedAttributes]([ext])
            item_props.append(props)

        response = self._service.CreateItems(
            Array[ItemProperties](item_props),
            None,
            "",
        )
        _check_service_data(response.ServiceData, "CreateItems")
        return list(getattr(response, "Output", []))

    def generate_revision_ids(self, items) -> list:
        """
        Reserve new revision IDs for the supplied items.

        Wraps `DataManagementService.GenerateRevisionIds`.

        Args:
            items: A list of `Item` objects to generate next revision IDs for.

        Returns:
            A list of revision ID structures.
        """
        properties = []
        for item in items:
            prop = GenerateRevisionIdsProperties()
            prop.Item = item
            prop.ItemType = ""
            properties.append(prop)

        response = self._service.GenerateRevisionIds(Array[GenerateRevisionIdsProperties](properties))
        _check_service_data(response.ServiceData, "GenerateRevisionIds")

        revision_map = response.OutputRevisionIds
        revisions = []
        for idx in range(len(items)):
            revisions.append(revision_map[Int32(idx)])
        return revisions

    def revise_items(self, revision_ids, item_revisions) -> None:
        """
        Revise the supplied item revisions to the next IDs.

        Wraps `DataManagementService.Revise2`.

        Args:
            revision_ids: List of revision ID structures from `generate_revision_ids`.
            item_revisions: List of `ItemRevision` objects to be revised.
        """
        revise_info = []
        for index, item_rev in enumerate(item_revisions):
            rev_ids = revision_ids[index]
            info = ReviseInfo()
            info.BaseItemRevision = item_rev
            info.ClientId = f"{item_rev.Uid}--{index}"
            info.Description = "describe testRevise"
            info.Name = "testRevise"
            info.NewRevId = rev_ids.NewRevId
            revise_info.append(info)

        response = self._service.Revise2(Array[ReviseInfo](revise_info))
        _check_service_data(response.ServiceData, "Revise2")

    def delete_items(self, items) -> None:
        """
        Delete the given items.

        Wraps `DataManagementService.DeleteObjects`.

        Args:
            items: A list of `Item` objects to delete.
        """
        service_data = self._service.DeleteObjects(Array[ModelObject](items))
        _check_service_data(service_data, "DeleteObjects")

    def create_forms(
        self,
        master_name: str,
        master_type: str,
        rev_name: str,
        rev_type: str,
        parent,
        save_db: bool,
    ) -> list[ModelObject]:
        """
        Helper to create the form pair used when instantiating new items.

        Wraps `DataManagementService.CreateOrUpdateForms`.
        """
        form_a = FormInfo()
        form_a.ClientId = "1"
        form_a.Name = master_name
        form_a.FormType = master_type
        form_a.Description = ""
        form_a.ParentObject = parent
        form_a.SaveDB = save_db

        form_b = FormInfo()
        form_b.ClientId = "2"
        form_b.Name = rev_name
        form_b.FormType = rev_type
        form_b.Description = ""
        form_b.ParentObject = parent
        form_b.SaveDB = save_db

        response = self._service.CreateOrUpdateForms(Array[FormInfo]([form_a, form_b]))
        _check_service_data(response.ServiceData, "CreateOrUpdateForms")
        outputs = getattr(response, "Outputs", [])
        return [entry.Form for entry in outputs]


def _check_service_data(service_data, context: str) -> None:
    """Raise if any partial errors were returned in the service data."""
    if service_data is None:
        return
    count = getattr(service_data, "SizeOfPartialErrors", 0)
    if callable(count):
        count = count()
    if count:
        raise ServiceException(f"{context} returned {count} partial error(s).")
