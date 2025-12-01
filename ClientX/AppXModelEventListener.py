import clr

# Ensure necessary assemblies are referenced.
# TcSoaStrongModel contains strong types like WorkspaceObject.
clr.AddReference("TcSoaStrongModel")  # type: ignore
clr.AddReference("TcSoaClient")  # type: ignore

import Teamcenter.Soa.Exceptions as TcSoaExceptions  # type: ignore
import Teamcenter.Soa.Client.Model as TcSoaClientModel  # type: ignore
from Teamcenter.Soa.Client.Model.Strong import WorkspaceObject  # type: ignore


class AppXModelEventListener(TcSoaClientModel.ModelEventListener):
    """
    Listens for changes to the client-side data model.

    This class implements `Teamcenter.Soa.Client.Model.ModelEventListener`.
    The Model Manager notifies this listener when objects in the local Cache are created,
    updated, or deleted as a result of service calls.

    **Events Handled:**
    - `LocalObjectChange`: Called when **this** client's action caused an object update
      (e.g., checking out an item, modifying a property).
    - `LocalObjectDelete`: Called when **this** client's action deleted an object.

    **Note on Shared Events:**
    This implementation does not currently override `SharedObjectChange` or `SharedObjectDelete`,
    which are triggered by changes from **other** clients (if session sharing/events are enabled).
    """
    __namespace__ = "PyTC_AppXModelEventListener"

    def LocalObjectChange(self, objects: list[TcSoaClientModel.ModelObject]) -> None:
        """
        Handles notifications when ModelObjects are modified in the local cache.

        This is called by the ModelManager when the `ServiceData` returned by a service
        contains updated objects that are already tracked in the client's Data Model.

        Args:
            objects: A list of `ModelObject` instances that have been changed.
        """
        # Output suppressed per user request
        pass

    def LocalObjectDelete(self, uids: list[str]) -> None:
        """
        Handles notifications when ModelObjects are deleted from the server and
        removed from the local cache.

        This is called by the ModelManager when the `ServiceData` indicates objects
        have been deleted.

        Args:
            uids: A list of UIDs (strings) of the objects that have been deleted.
        """
        # Output suppressed per user request
        pass
