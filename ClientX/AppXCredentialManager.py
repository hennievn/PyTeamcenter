import clr
import System  # type: ignore

# from System import Reflection  # type: ignore # Not used
import System.IO  # type: ignore - For System.IO.IOException
import os
import getpass

assy1 = clr.AddReference("TcSoaCoreStrong")  # type: ignore
assy2 = clr.AddReference("TcSoaStrongModel")  # type: ignore
assy3 = clr.AddReference("TcSoaClient")  # type: ignore
assy4 = clr.AddReference("TcSoaCommon")  # type: ignore

import Teamcenter.Schemas.Soa._2006_03.Exceptions as Exceptions2006  # type: ignore
import Teamcenter.Soa as TcSoa  # type: ignore
import Teamcenter.Soa.Client as TcSoaClient  # type: ignore
import Teamcenter.Soa.Exceptions as TcSoaExceptions  # type: ignore

# Setup logger for this module
import logging
logger = logging.getLogger(__name__)
# The CredentialManager is used by the Teamcenter Services framework to get the
# user's credentials when challanged by the server. This can occur after a period
# of inactivity and the server has timed-out the user's session, at which time
# the client application will need to re-authenitcate. The framework will
# call one of the getCredentials methods (depending on circumstances) and will
# send the SessionService.login service request. Upon successfull completion of
# the login service request. The last service request (one that cuased the challange)
# will be resent.


# The framework will also call the setUserPassword setGroupRole methods when ever
# these credentials change, thus allowing this implementation of the CredentialManager
# to cache these values so prompting of the user is not requried for  re-authentication.
class AppXCredentialManager(TcSoaClient.CredentialManager):
    __namespace__ = "PythonCredentialManager"

    def __init__(self):
        self.name: str | None = None
        self.password: str | None = None
        self.group: str | None = ""  # default group
        self.role: str | None = ""  # default role
        self.discriminator: str = "SoaAppX"  # always connect same user to same instance of server
        self.serveraddress: str = os.getenv("TC_SERVER_HOST", "http://tce_yourcompany.com/tc")  # Unused in this class
        self._CredentialType: TcSoa.SoaConstants = TcSoa.SoaConstants.CLIENT_CREDENTIAL_TYPE_STD

    # Cache the group and role
    # This is called after the SessionService.setSessionGroupMember service
    # operation is called.
    def SetGroupRole(self, group: str, role: str) -> None:
        self.group = group
        self.role = role

    # Return the type of credentials this implementation provides, standard (user/password)
    # or Single-Sign-On. In this case Standard credentials are returned.
    #
    # using @property decorator a getter function
    # This do not appear to work with the PythonNet infrastuctue - see below
    @property
    def CredentialType(self) -> int:  # Should be int if _CredentialType holds an int constant
        return self._CredentialType

    # a setter function
    @CredentialType.setter
    def CredentialType(self, a: int) -> None:  # Assuming 'a' is one of the int constants
        self._CredentialType = a

    # The .NET infrastructure will not find the property above.  It will look for and use this
    # manually-created function
    def get_CredentialType(self) -> int:
        return self._CredentialType

    def PromptForCredentials(self) -> list[str]:
        env_name = os.getenv("TCUSER")
        env_password = os.getenv("TCPASSWORD")

        # Priority 1: Use environment variables if both are fully provided
        if env_name and env_password:
            self.name = env_name
            self.password = env_password
        # Priority 2: If env vars are not sufficient, check cached credentials (self.name, self.password).
        # If they are also not sufficient (e.g. still None or empty), then prompt.
        elif not self.name or not self.password:
            try:
                print("Please enter user credentials (empty User Name to quit):", flush=True)

                # Prompt for name. If user enters nothing, it's a cancellation.
                temp_name = input(f"User Name [{self.name or ''}]: ")
                if not temp_name:
                    # If user pressed enter and self.name was already populated (e.g. from partial env),
                    # and they didn't provide a new one, we might want to keep self.name.
                    # However, for simplicity, if they don't provide a new name here, we treat as cancel if self.name isn't already valid.
                    if not self.name:  # If self.name is also empty/None, then it's a clear cancel.
                        raise TcSoaExceptions.CanceledOperationException(
                            "User cancelled login: User Name not provided."
                        )
                    # If self.name had a value, and user entered blank, we keep existing self.name.
                else:
                    self.name = temp_name  # User provided a new name

                # If after input, self.name is still not set, raise cancel.
                if not self.name:
                    raise TcSoaExceptions.CanceledOperationException("User cancelled login: User Name not provided.")

                self.password = getpass.getpass("Password:  ")

            except (EOFError, KeyboardInterrupt):
                message = "Login cancelled by user during credential input."
                print(message)
                raise TcSoaExceptions.CanceledOperationException(message)
            except System.IO.IOException as e_io:  # If .NET IOException is possible for console
                message = "Failed to read user credentials due to IO error.\n" + e_io.Message
                print(message)
                raise TcSoaExceptions.CanceledOperationException(message)

        tokens = [self.name or "", self.password or "", self.group or "", self.role or "", self.discriminator]
        return tokens

    # Prompt's the user for credentials.
    # This method will only be called by the framework when a login attempt has
    # failed.
    # Return the cached credentials.
    # This method will be called when a service request is sent without a valid
    # session ( session has expired on the server).
    def GetCredentials(
        self, e: Exceptions2006.InvalidUserException | Exceptions2006.InvalidCredentialsException
    ) -> list[str]:
        # throws CanceledOperationException
        # Have not logged in yet, should not happen but just in case
        if isinstance(e, Exceptions2006.InvalidUserException):
            logger.warning(
                f"Server reported user '{self.name or 'unknown'}' as invalid. Please re-enter credentials."
            )
            # Always re-prompt if the user is invalid, regardless of cached credentials.
            return self.PromptForCredentials()
        elif isinstance(e, Exceptions2006.InvalidCredentialsException):
            logger.warning(f"Invalid credentials provided: {e.Message}")
            return self.PromptForCredentials()
        else:
            # Fallback for unexpected exception types, though type hint restricts it.
            logger.error(f"Unexpected exception type {type(e)} in GetCredentials. Prompting for credentials.")
            return self.PromptForCredentials()

    # Cache the User and Password
    # This is called after the SessionService.login service operation is called.
    def SetUserPassword(self, user: str, password: str, discriminator: str):
        self.name = user
        self.password = password
        self.discriminator = discriminator
