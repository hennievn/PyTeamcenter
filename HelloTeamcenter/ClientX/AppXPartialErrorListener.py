import clr

clr.AddReference("TcSoaClient")  # type: ignore
import Teamcenter.Soa.Client.Model as TcSoaClientModel  # type: ignore


class AppXPartialErrorListener(TcSoaClientModel.PartialErrorListener):
    """
    Listens for and prints partial errors returned in a service response.

    This class implements the `Teamcenter.Soa.Client.Model.PartialErrorListener` interface.
    It is registered with the `ModelManager`.

    **Partial Errors**:
    In Teamcenter SOA, a service operation (like "Delete Objects") can succeed for some
    inputs but fail for others. The service returns a "Success" status but includes
    `PartialErrors` in the `ServiceData`. This listener intercepts those errors globally.
    """
    __namespace__ = "PyTC_AppXPartialErrorListener"

    def HandlePartialError(self, stacks: list[TcSoaClientModel.ErrorStack]) -> None:
        """
        Processes a list of error stacks from a service response.

        This method is called by the Model Manager whenever `ServiceData` contains partial errors.

        Args:
            stacks: A list of `ErrorStack` objects. Each `ErrorStack` represents a failure
                    associated with a specific input object or client ID.
                    - `ErrorStack` contains:
                        - `AssociatedObject` (ModelObject) OR `ClientId` (str)
                        - `ErrorValues` (Array of `ErrorValue`)
                    - `ErrorValue` contains:
                        - `Code` (int): The Teamcenter error code (e.g., 515001).
                        - `Level` (int): Severity (1=Info, 2=Warning, 3=Error).
                        - `Message` (str): The localized error message.
        """
        if not stacks:
            return

        print(f"***** Partial Errors caught in {self.__class__.__name__} *****")

        for i, stk in enumerate(stacks):
            errors = stk.ErrorValues
            source_info = f"Error Stack {i+1}"

            # Identify the source of the error (e.g., a specific ModelObject or client ID)
            if stk.HasAssociatedObject():
                source_info += f" (for object {stk.AssociatedObject.Uid})"
            elif stk.HasClientId():
                source_info += f" (for client id '{stk.ClientId}')"
            elif stk.HasClientIndex():
                source_info += f" (for client index {stk.ClientIndex})"
            print(source_info)

            # Print each contributing error message in the stack
            if not errors:
                print("    (No detailed error values provided)")
                continue

            for er in errors:
                print(f"    - Code: {er.Code}\tLevel: {er.Level}\tMessage: {er.Message}")
