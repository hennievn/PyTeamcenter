import clr

# Add references to Teamcenter SOA assemblies
clr.AddReference("TcSoaCoreStrong")  # type: ignore
clr.AddReference("TcSoaStrongModel")  # type: ignore
clr.AddReference("TcSoaClient")  # type: ignore
clr.AddReference("TcSoaCommon")  # type: ignore

import System  # type: ignore
import System.IO  # type: ignore

import Teamcenter.Schemas.Soa._2006_03.Exceptions as Exceptions2006  # type: ignore
import Teamcenter.Soa.Client as TcSoaClient  # type: ignore
import Teamcenter.Soa.Exceptions as TcSoaExceptions  # type: ignore


def _is_internal_server_exception(ex: System.Exception) -> bool:
    """
    Robustly checks if an exception is an `InternalServerException`.

    This is necessary to handle different exception types across Teamcenter
    versions and bindings (runtime vs. schema).

    Args:
        ex: The exception object to check.

    Returns:
        True if the exception is identified as an `InternalServerException`.
    """
    # 1) Check for the runtime type if it exists in the current kit
    try:
        ISE = getattr(TcSoaExceptions, "InternalServerException")
        if isinstance(ex, ISE):
            return True
    except AttributeError:
        pass  # ISE not defined in this version of TcSoaExceptions

    # 2) Check for the schema type (always present in bindings)
    if isinstance(ex, Exceptions2006.InternalServerException):
        return True

    # 3) Fallback: match by the full type name string for cross-version compatibility
    try:
        tname = ex.GetType().FullName or ""
        if tname.endswith(".InternalServerException"):
            return True
    except Exception:
        pass  # Could fail if GetType() is not available

    return False


class AppXExceptionHandler(TcSoaClient.ExceptionHandler):
    """
    Handles exceptions from the SOA client framework.

    This class implements the `Teamcenter.Soa.Client.ExceptionHandler` interface.
    It intercepts exceptions thrown during service requests, allowing for custom
    logging, user interaction, and potential recovery logic.

    Key behaviors:
    - **Connection Errors**: Prompts the user to retry if the server is unreachable.
    - **Protocol Errors**: Logs the error as likely non-recoverable.
    - **Cancellations**: Re-throws to let the application handle the stop.
    """
    __namespace__ = "PythonAppXExceptionHandler"

    def HandleException(
        self,
        ise: Exceptions2006.InternalServerException | TcSoaExceptions.CanceledOperationException,
    ) -> None:
        """
        Processes exceptions caught by the SOA framework.

        - For `InternalServerException` types (e.g., 500 errors, connection refused),
          it prints details and offers a retry prompt (if it's a `ConnectionException`).
        - For `CanceledOperationException`, it re-throws as a `SystemException` to abort
          the current operation.

        Args:
            ise: The exception to handle.

        Raises:
            System.SystemException: If the error is unrecoverable or the user
                                    chooses not to retry.
        """
        if _is_internal_server_exception(ise):
            print("\n***** Exception caught in AppXExceptionHandler for InternalServerException *****")

            if isinstance(ise, Exceptions2006.ConnectionException):
                # ConnectionExceptions are typically due to a network error and can be recovered from.
                print(f"\nThe server returned a connection error.\n{ise.Message}")
            elif isinstance(ise, Exceptions2006.ProtocolException):
                # ProtocolExceptions are typically due to programming errors (e.g., incorrect HTTP request content).
                print(f"\nThe server returned a protocol error.\n{ise.Message}")
                print("This is most likely the result of a programming error.")
            else:
                # Handle other generic InternalServerExceptions.
                print(f"\nThe server returned an internal server error.\n{ise.Message}")
                print("This is most likely the result of a programming error.")
                print("A RuntimeException will be thrown.")
                raise System.SystemException(ise.Message)

            # For ConnectionException or ProtocolException, offer to retry.
            try:
                retry_input = input("Do you wish to retry the last service request? [y/n]: ")
                if retry_input.strip().lower() in ["y", "yes"]:
                    return  # Return to the framework to resend the request.
                raise System.SystemException("The user has opted not to retry the last request.")
            except System.IO.IOException as e:
                print("Failed to read user response. A RuntimeException will be thrown.")
                raise System.SystemException(e.Message)
        else:
            # Handle CanceledOperationException
            print("\n***** Exception caught in AppXExceptionHandler for CanceledOperationException *****")
            raise System.SystemException(ise.Message)


class DebugExceptionHandler(TcSoaClient.ExceptionHandler):
    """
    A drop-in debug handler that prints detailed exception information but
    never re-throws the exception, allowing the application to continue.
    """
    __namespace__ = "PythonAppXDebugExceptionHandler"

    def HandleException(self, ex: System.Exception) -> None:
        """
        Prints diagnostic information from the exception and its service data,
        then swallows the exception.

        Args:
            ex: The exception to debug.
        """
        try:
            print("\n[DEBUG] Exception Type:", type(ex))
            print("[DEBUG] Message:", getattr(ex, "Message", "N/A"))
            print("[DEBUG] StackTrace:", getattr(ex, "StackTrace", "N/A"))

            # If ServiceData exists (on ServiceException), dump partial errors
            sd = getattr(ex, "ServiceData", None)
            if sd:
                try:
                    num_errors = sd.SizeOfPartialErrors
                    print(f"[DEBUG] ServiceData contains {num_errors} partial error(s).")
                    for i in range(num_errors):
                        stack = sd.GetPartialError(i)
                        print(f"[DEBUG] ErrorStack {i}:")
                        for j in range(stack.SizeOfErrorValues):
                            err_val = stack.GetErrorValue(j)
                            print(f"    - Code: {err_val.Code}, Level: {err_val.Level}, Message: {err_val.Message}")
                except Exception as e_sd:
                    print(f"[DEBUG] Failed to dump ServiceData: {e_sd}")
        except Exception as e_outer:
            print(f"[DEBUG] Error in DebugExceptionHandler itself: {e_outer}")
        finally:
            # IMPORTANT: Do not raise here. The purpose of this handler is to
            # observe and swallow the exception.
            return
