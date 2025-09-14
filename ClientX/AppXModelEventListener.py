import clr

# Ensure necessary assemblies are referenced.
# TcSoaStrongModel contains strong types like WorkspaceObject.
# If another part of your application (e.g., Session.py) already ensures this is loaded
# before the listener is instantiated, this might be redundant but adds robustness.
assy_strong_model = clr.AddReference("TcSoaStrongModel")  # type: ignore
assy3 = clr.AddReference("TcSoaClient")  # type: ignore
assy4 = clr.AddReference("TcSoaCommon")  # type: ignore

import Teamcenter.Soa.Exceptions as TcSoaExceptions  # type: ignore
import Teamcenter.Soa.Client.Model as TcSoaClientModel  # type: ignore
from Teamcenter.Soa.Client.Model.Strong import WorkspaceObject  # type: ignore


class AppXModelEventListener(TcSoaClientModel.ModelEventListener):
    __namespace__ = "PyTC_AppXModelEventListener"

    def LocalObjectChange(self, objects: list[TcSoaClientModel.ModelObject]) -> None:
        if not objects:
            return
        print(f"\nModified Objects handled in {self.__class__.__module__}.{self.__class__.__name__}.LocalObjectChange")
        print("The following objects have been updated in the client data model:")
        for obj in objects:
            uid = obj.Uid
            type_name = obj.GetType().Name  # Display name of the type
            name = ""

            # Use isinstance for more Pythonic type checking if WorkspaceObject is the target.
            # This assumes WorkspaceObject is the type (or a parent type) that has "object_string".
            if isinstance(obj, WorkspaceObject):
                try:
                    prop = obj.GetProperty("object_string")
                    if prop is not None:  # Ensure the property object itself exists
                        name = prop.StringValue
                except TcSoaExceptions.NotLoadedException:
                    # Property is not loaded, 'name' remains ""
                    pass
                except Exception as e_generic:
                    # Catch any other unexpected error during property access
                    print(f"    Error accessing 'object_string' for {uid} ({type_name}): {e_generic}")
                    pass  # 'name' remains ""
            print(f"    {uid} {type_name} {name}")

    def LocalObjectDelete(self, uids: list[str]) -> None:
        if not uids:
            return
        print(f"\nDeleted Objects handled in {self.__class__.__module__}.{self.__class__.__name__}.LocalObjectDelete")
        print("The following objects have been deleted from the server and removed from the client data model:")
        for u in uids:
            print(f"    {u}")
