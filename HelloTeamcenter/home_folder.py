"""Home folder listing helper mirroring the Siemens sample."""

from __future__ import annotations

import logging

import tc_utils  # noqa: F401

import clr  # type: ignore

clr.AddReference("TcSoaCoreStrong")  # type: ignore

from System import Array, String  # type: ignore

from Teamcenter.Services.Strong.Core import DataManagementService  # type: ignore
from Teamcenter.Soa.Client.Model import ModelObject  # type: ignore
from Teamcenter.Soa.Exceptions import NotLoadedException  # type: ignore

LOGGER = logging.getLogger(__name__)


def list_home_folder(connection, user) -> None:
    """
    Fetch and print the contents of the user's home folder.

    This function mirrors the `HomeFolder` class in the C# sample.
    It uses the `DataManagementService` to:
    1.  **GetProperties**: Retrieve the `contents` property of the user's `Home_folder`.
    2.  **LoadObjects**: Explicitly load the objects found in the folder to ensure
        attributes are available.
    3.  **GetProperties** (Batch): Retrieve display properties (`object_string`,
        `object_name`, `object_type`) for all loaded objects to support logging.

    Args:
        connection: The active Teamcenter connection.
        user: The `User` object returned from the login process.
    """
    dm_service = DataManagementService.getService(connection)
    try:
        home_folder = user.Home_folder
    except NotLoadedException as exc:
        LOGGER.error("home_folder property not loaded on user: %s", exc.Message)
        return

    try:
        # Load the folder's contents relationship first; this only returns lightweight shells.
        dm_service.GetProperties(
            Array[ModelObject]([home_folder]),
            Array[String](["contents"]),
        )
        contents = list(getattr(home_folder, "Contents", []))
        if contents:
            idx_uid = [(idx, getattr(obj, "Uid", None)) for idx, obj in enumerate(contents)]
            uids = [uid for _, uid in idx_uid if uid]
            loaded_objects: list[ModelObject] = []
            if uids:
                try:
                    # Replace lightweight shells with fully populated model objects.
                    service_data = dm_service.LoadObjects(Array[String](uids))
                    count = service_data.sizeOfPlainObjects()
                    loaded_objects = [service_data.GetPlainObject(i) for i in range(count)]
                    uid_map = {obj.Uid: obj for obj in loaded_objects if getattr(obj, "Uid", None)}
                    for idx, uid in idx_uid:
                        if uid and uid in uid_map:
                            contents[idx] = uid_map[uid]
                except Exception as exc:
                    LOGGER.warning("Failed to load folder objects: %s", exc)
            targets = loaded_objects or contents
            unique_targets = []
            seen = set()
            for obj in targets:
                uid = getattr(obj, "Uid", None)
                key = uid or id(obj)
                if key not in seen:
                    unique_targets.append(obj)
                    seen.add(key)
            # Load the display properties once per unique model object so logging can use them.
            _ensure_properties(
                dm_service,
                unique_targets,
                ["object_string", "object_name", "object_type"],
                "Failed to load folder object display names",
            )
    except Exception as exc:
        LOGGER.error("Failed to load home folder contents: %s", exc)
        return

    LOGGER.info("Home folder contents (%s entries):", len(contents))
    for obj in contents:
        name = _safe_get_string(obj, "object_string")
        obj_type = getattr(obj, "Type", None)
        if not obj_type:
            try:
                obj_type = obj.GetPropertyDisplayableValue("object_type")
            except Exception:
                obj_type = None
        if not obj_type:
            obj_type = getattr(obj, "Object_type", None)
        if not obj_type:
            obj_type = "<unknown>"
        LOGGER.info(" - %s (%s)", name, obj_type)


def _ensure_properties(dm_service, objects, props, warn_message: str) -> None:
    """Load a set of properties for the supplied model objects."""
    objs = list(objects)
    if not objs:
        return
    try:
        dm_service.GetProperties(
            Array[ModelObject](objs),
            Array[String](list(props)),
        )
    except Exception as exc:
        LOGGER.warning("%s: %s", warn_message, exc)


def _safe_get_string(obj, prop_name: str) -> str:
    """Return a string property with fallbacks for unloaded fields."""
    try:
        display = obj.GetPropertyDisplayableValue(prop_name)
        if display:
            return display
    except Exception:
        pass
    try:
        prop = obj.GetProperty(prop_name)
        if prop and getattr(prop, "StringValue", None):
            return prop.StringValue
    except NotLoadedException:
        pass
    except Exception:
        pass
    display = getattr(obj, "Object_string", None)
    if display:
        return display
    return getattr(obj, "Uid", "<unknown>")
