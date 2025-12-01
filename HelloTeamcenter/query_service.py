"""Saved query helper mirroring the Siemens sample."""

from __future__ import annotations

import logging

import tc_utils  # noqa: F401

import clr  # type: ignore

clr.AddReference("TcSoaQueryStrong")  # type: ignore

from System import Array, String  # type: ignore

from Teamcenter.Services.Strong.Query import SavedQueryService  # type: ignore
from Teamcenter.Services.Strong.Core import DataManagementService  # type: ignore
from Teamcenter.Services.Strong.Query._2008_06.SavedQuery import QueryInput  # type: ignore
from Teamcenter.Soa.Client.Model import ModelObject  # type: ignore

LOGGER = logging.getLogger(__name__)

_DISPLAY_PROPS = [
    "object_string",
    "object_desc",
    "object_name",
    "creation_date",
]


def query_items(connection) -> None:
    """
    Execute the 'Item Name' saved query and print results.

    Mirrors the `Query` class in the C# sample.
    Steps:
    1.  **SavedQueryService.GetSavedQueries**: Retrieves available saved queries to find
        one named 'Item Name'.
    2.  **SavedQueryService.ExecuteSavedQueries**: Runs the query with a wildcard ('*')
        input.
    3.  **DataManagementService.LoadObjects**: Loads the objects returned by the query
        (paginated) to ensure properties are available.
    4.  **DataManagementService.GetProperties**: Loads display properties for result logging.

    Args:
        connection: The active Teamcenter connection.
    """
    query_service = SavedQueryService.getService(connection)
    dm_service = DataManagementService.getService(connection)

    try:
        saved_queries = query_service.GetSavedQueries()
    except Exception as exc:
        LOGGER.error("GetSavedQueries failed: %s", exc)
        return

    iman_query = None
    for entry in getattr(saved_queries, "Queries", []):
        if entry.Name == "Item Name":
            iman_query = entry.Query
            break

    if iman_query is None:
        LOGGER.warning("Saved query 'Item Name' not found.")
        return

    query_input = QueryInput()
    query_input.Query = iman_query
    query_input.MaxNumToReturn = 25
    query_input.LimitList = Array[ModelObject]([])
    query_input.Entries = Array[String](["Item Name"])
    query_input.Values = Array[String](["*"])

    try:
        response = query_service.ExecuteSavedQueries(Array[QueryInput]([query_input]))
    except Exception as exc:
        LOGGER.error("ExecuteSavedQueries failed: %s", exc)
        return

    results_array = getattr(response, "ArrayOfResults", [])
    if not results_array:
        LOGGER.info("Saved query returned no results.")
        return

    results = results_array[0]
    uids = list(getattr(results, "ObjectUIDS", []))
    if not uids:
        LOGGER.info("Saved query returned no object UIDs.")
        return

    LOGGER.info("Found Items:")
    for start in range(0, len(uids), 10):
        page_uids = uids[start : start + 10]
        try:
            service_data = dm_service.LoadObjects(Array[String](page_uids))
        except Exception as exc:
            LOGGER.error("LoadObjects failed for page starting %s: %s", start, exc)
            continue

        count = service_data.sizeOfPlainObjects()
        objects = [service_data.GetPlainObject(i) for i in range(count)]

        if objects:
            # Populate the common display properties so we can render a readable summary.
            try:
                dm_service.GetProperties(
                    Array[ModelObject](objects),
                    Array[String](_DISPLAY_PROPS),
                )
            except Exception as exc:
                LOGGER.warning("Failed to load display properties: %s", exc)

        for obj in objects:
            LOGGER.info(" - %s", _describe_object(obj))


def _describe_object(obj) -> str:
    """Return a friendly string for a loaded model object."""

    def _display(prop: str):
        try:
            return obj.GetPropertyDisplayableValue(prop)
        except Exception:
            return None

    uid = getattr(obj, "Uid", "<unknown>")
    display = _display("object_string") or getattr(obj, "Object_string", None)
    desc = _display("object_desc") or getattr(obj, "Object_desc", None)
    name = _display("object_name") or getattr(obj, "Object_name", None)
    creation_date = _display("creation_date") or getattr(obj, "Creation_date", None)

    if display:
        # Build a compact detail string that mirrors the managed sample output.
        parts = [f"UID: {uid}"]
        parts.extend(str(part) for part in [desc, name, creation_date] if part)
        details = " | ".join(parts)
        if details:
            return f"{display} ({details})"
        return str(display)
    return uid
