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
    Listens for changes to the client-side data model and prints them to the console.
    """
    __namespace__ = "PyTC_AppXModelEventListener"

    def LocalObjectChange(self, objects: list[TcSoaClientModel.ModelObject]) -> None:
        """
        Handles notifications when ModelObjects are modified in the local cache.

        Args:
            objects: A list of ModelObjects that have been changed.
        """
        # Output suppressed per user request
        pass

    def LocalObjectDelete(self, uids: list[str]) -> None:
        """
        Handles notifications when ModelObjects are deleted from the server and
        removed from the local cache.

        Args:
            uids: A list of UIDs of the objects that have been deleted.
        """
        # Output suppressed per user request
        pass
