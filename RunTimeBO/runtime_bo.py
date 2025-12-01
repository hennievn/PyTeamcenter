"""Helper that mirrors the RuntimeBO C# example using pythonnet."""

from __future__ import annotations

import logging

import tc_utils  # noqa: F401  # Ensure Teamcenter assemblies are loaded

from System import Array  # type: ignore

from Teamcenter.Services.Strong.Core import DataManagementService  # type: ignore
from Teamcenter.Services.Strong.Core._2008_06.DataManagement import (  # type: ignore
    CreateIn,
    CreateInput,
)

LOGGER = logging.getLogger(__name__)


class RuntimeBOExample:
    """
    Encapsulates the runtime business-object creation flow.

    Mirrors the `DataManagement` class in the C# RuntimeBO sample.
    """

    def __init__(self, connection) -> None:
        self._connection = connection
        self._service = DataManagementService.getService(connection)

    def create_runtime_bo(self, *, bo_name: str, string_value: str, int_value: int) -> None:
        """
        Create a runtime business object and report the response.

        Wraps `DataManagementService.CreateObjects`.
        Constructs a `CreateIn` container specifying the Business Object name (`BoName`)
        and initial property values (`StringProps`, `IntProps`) for the Runtime BO.

        Args:
            bo_name: The name of the Runtime Business Object type (e.g., "SRB9runtimebo1").
            string_value: Value for the 'srb9StringProp' property.
            int_value: Value for the 'srb9IntegerProperty' property.
        """
        create_payload = CreateIn()
        create_payload.ClientId = "SampleRuntimeBOclient"
        create_payload.Data = CreateInput()
        create_payload.Data.BoName = bo_name
        create_payload.Data.StringProps["srb9StringProp"] = string_value
        create_payload.Data.IntProps["srb9IntegerProperty"] = int_value

        LOGGER.info(
            "Creating runtime business object '%s' (%s=%s, %s=%s).",
            bo_name,
            "srb9StringProp",
            string_value,
            "srb9IntegerProperty",
            int_value,
        )

        response = self._service.CreateObjects(Array[CreateIn]([create_payload]))
        _log_partial_errors(response.ServiceData)
        outputs = getattr(response, "Output", None)
        if outputs:
            created = outputs[0]
            LOGGER.info(
                "Runtime BO created with UID=%s, type=%s.",
                getattr(created, "Uid", "<unknown>"),
                getattr(created, "Type", "<unknown>"),
            )
        else:
            LOGGER.warning("CreateObjects returned no output records.")


def _log_partial_errors(service_data) -> None:
    if service_data is None:
        return
    size = getattr(service_data, "SizeOfPartialErrors", 0)
    if callable(size):
        size = size()
    if size:
        LOGGER.warning("Service returned %s partial error(s).", size)
