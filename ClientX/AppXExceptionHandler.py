import clr

assy1 = clr.AddReference("TcSoaCoreStrong")  # type: ignore
assy2 = clr.AddReference("TcSoaStrongModel")  # type: ignore
assy3 = clr.AddReference("TcSoaClient")  # type: ignore
assy4 = clr.AddReference("TcSoaCommon")  # type: ignore

import System  # type: ignore
import System.IO  # type: ignore

import Teamcenter.Schemas.Soa._2006_03.Exceptions as Exceptions2006  # type: ignore
import Teamcenter.Soa.Client as TcSoaClient  # type: ignore
import Teamcenter.Soa.Exceptions as TcSoaExceptions  # type: ignore


# Implementation of the ExceptionHandler. For ConnectionExceptions (server
# temporarily down .etc) prompts the user to retry the last request. For other
# exceptions convert to a RunTime exception.
class AppXExceptionHandler(TcSoaClient.ExceptionHandler):
    __namespace__ = "PythonAppXExceptionHandler"

    # com.teamcenter.soa.client.ExceptionHandler#handleException(com.teamcenter.schemas.soa._2006_03.exceptions.InternalServerException)
    def HandleException(
        self, ise: Exceptions2006.InternalServerException | TcSoaExceptions.CanceledOperationException
    ) -> None:
        # This check correctly handles Exceptions2006.InternalServerException and its subtypes
        # if they inherit from TcSoaExceptions.InternalServerException.
        if isinstance(ise, TcSoaExceptions.InternalServerException):  # Covers schema-defined ISEs too
            print(
                "\n*****Exception caught in com.teamcenter.clientx.AppXExceptionHandler.handleException(InternalServerException)."
            )

            if isinstance(ise, Exceptions2006.ConnectionException):
                # ConnectionException are typically due to a network error (server
                # down .etc) and can be recovered from (the last request can be sent again,
                # after the problem is corrected).
                print(f"\nThe server returned an connection error.\n{ise.Message}")
            elif isinstance(ise, Exceptions2006.ProtocolException):
                # ProtocolException are typically due to programming errors (content of HTTP request is incorrect).
                # These generally can not be recovered from.
                print(f"\nThe server returned an protocol error.\n{ise.Message}")
                print(f"This is most likely the result of a programming error.")
            else:  # Handles other TcSoaExceptions.InternalServerException or Exceptions2006.InternalServerException
                print(f"\nThe server returned an internal server error.\n{ise.Message}")
                print("This is most likely the result of a programming error.")
                print("A RuntimeException will be thrown.")
                raise System.SystemException(ise.Message)

            # Retry logic is only reached for ConnectionException and ProtocolException
            # as the 'else' block above raises an exception.
            try:
                retry_input = input("Do you wish to retry the last service request? [y/n]: ")
                # If yes, return to the calling SOA client framework, where the
                # last service request will be resent.
                if retry_input.strip().lower() in ["y", "yes"]:
                    return
                raise System.SystemException("The user has opted not to retry the last request")
            except System.IO.IOException as e:
                print("Failed to read user response.\nA RuntimeException will be thrown.")
                raise System.SystemException(e.Message)
        else:  # see com.teamcenter.soa.client.ExceptionHandler#handleException(com.teamcenter.soa.exceptions.CanceledOperationException)
            print(
                "\n*****Exception caught in com.teamcenter.clientx.AppXExceptionHandler.handleException(CanceledOperationException)."
            )
            # Expecting this from the login tests with bad credentials, and the
            # AnyUserCredentials class not prompting for different credentials
            raise System.SystemException(ise.Message)
