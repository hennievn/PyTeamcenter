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
        if not objects:
            return
        print(f"\nModified Objects handled in {self.__class__.__name__}:")
        print("The following objects have been updated in the client data model:")
        for obj in objects:
            uid = obj.Uid
            type_name = obj.GetType().Name
            name = ""

            # If the object is a WorkspaceObject, try to get its 'object_string' property for a display name.
            if isinstance(obj, WorkspaceObject):
                try:
                    prop = obj.GetProperty("object_string")
                    if prop is not None:
                        name = prop.StringValue
                except TcSoaExceptions.NotLoadedException:
                    # This is expected if the property wasn't loaded; 'name' remains empty.
                    pass
                except Exception as e_generic:
                    # Catch any other unexpected error during property access.
                    print(f"    Error accessing 'object_string' for {uid} ({type_name}): {e_generic}")
                    pass
            print(f"    - UID: {uid}, Type: {type_name}, Name: {name or 'N/A'}")

    def LocalObjectDelete(self, uids: list[str]) -> None:
        """
        Handles notifications when ModelObjects are deleted from the server and
        removed from the local cache.

        Args:
            uids: A list of UIDs of the objects that have been deleted.
        """
        if not uids:
            return
        print(f"\nDeleted Objects handled in {self.__class__.__name__}:")
        print("The following objects have been deleted from the server and removed from the client data model:")
        for u in uids:
            print(f"    - UID: {u}")
