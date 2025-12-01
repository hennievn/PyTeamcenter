import clr
import System  # type: ignore
import System.IO  # type: ignore - For System.IO.IOException
import os
import uuid
import getpass
from dotenv import load_dotenv
load_dotenv()  # take environment variables from .env.

# Add references to Teamcenter SOA assemblies
clr.AddReference("TcSoaCoreStrong")  # type: ignore
clr.AddReference("TcSoaStrongModel")  # type: ignore
clr.AddReference("TcSoaClient")  # type: ignore
clr.AddReference("TcSoaCommon")  # type: ignore

import Teamcenter.Schemas.Soa._2006_03.Exceptions as Exceptions2006  # type: ignore
import Teamcenter.Soa as TcSoa  # type: ignore
import Teamcenter.Soa.Client as TcSoaClient  # type: ignore
import Teamcenter.Soa.Exceptions as TcSoaExceptions  # type: ignore

# Setup logger for this module
import logging
logger = logging.getLogger(__name__)

# The CredentialManager is used by the Teamcenter Services framework to get the
# user's credentials when challenged by the server. This can occur after a period
# of inactivity and the server has timed-out the user's session, at which time
# the client application will need to re-authenticate. The framework will
# call one of the getCredentials methods (depending on circumstances) and will
# send the SessionService.login service request. Upon successful completion of
# the login service request, the last service request (one that caused the challenge)
# will be resent.

# The framework will also call the setUserPassword and setGroupRole methods whenever
# these credentials change, thus allowing this implementation of the CredentialManager
# to cache these values so prompting of the user is not required for re-authentication.
class AppXCredentialManager(TcSoaClient.CredentialManager):
    """
    Manages user credentials for Teamcenter SOA services, handling initial login
    prompts and re-authentication challenges.

    This class extends `Teamcenter.Soa.Client.CredentialManager`.
    It is registered with the `Teamcenter.Soa.Client.Connection` object.

    Responsibilities:
    1.  **Initial Login**: Provides credentials when the `SessionService.Login` is called.
    2.  **Session Expiry**: When the server returns a `SessionException` (401), the framework
        calls `GetCredentials` to re-acquire valid credentials transparently.
    3.  **Invalid Credentials**: When a login attempt fails, the framework calls `GetCredentials`
        to allow the user to correct their input.
    4.  **Caching**: Caches successful credentials via `SetUserPassword` and `SetGroupRole` to
        support silent re-authentication.
    """
    __namespace__ = "PythonCredentialManager"

    def __init__(self):
        """Initializes the credential manager with default values."""
        self.name: str | None = None
        self.password: str | None = None
        self.group: str | None = ""  # default group
        self.role: str | None = ""   # default role
        self.discriminator: str = (
            os.getenv("TC_SESSION_DISCRIMINATOR") or f"SoaAppX-{uuid.uuid4().hex}"
        )  # unique default discriminator unless overridden
        self._CredentialType: int = TcSoa.SoaConstants.CLIENT_CREDENTIAL_TYPE_STD

    def SetGroupRole(self, group: str, role: str) -> None:
        """
        Caches the group and role. Called after the `SessionService.setSessionGroupMember`
        service operation is called.

        Args:
            group: The user's current group.
            role: The user's current role.
        """
        self.group = group
        self.role = role

    @property
    def CredentialType(self) -> int:
        """
        Returns the type of credentials this implementation provides.
        
        Values:
        - `TcSoa.SoaConstants.CLIENT_CREDENTIAL_TYPE_STD` (2): Standard User/Password.
        - `TcSoa.SoaConstants.CLIENT_CREDENTIAL_TYPE_SSO` (1): Single Sign-On.

        Note: This property may not be accessible by the .NET infrastructure;
        see get_CredentialType for the compatible getter.
        """
        return self._CredentialType

    @CredentialType.setter
    def CredentialType(self, a: int) -> None:
        """
        Sets the credential type.
        """
        self._CredentialType = a

    def get_CredentialType(self) -> int:
        """
        Provides a .NET-compatible getter for the CredentialType property.
        Used by the internal SOA Framework logic.
        """
        return self._CredentialType

    def use_standard(self) -> None:
        """Mark this credential manager as supplying classic credentials."""
        self._CredentialType = TcSoa.SoaConstants.CLIENT_CREDENTIAL_TYPE_STD

    def use_sso(self) -> None:
        """Mark this credential manager as supplying SSO credentials."""
        self._CredentialType = TcSoa.SoaConstants.CLIENT_CREDENTIAL_TYPE_SSO

    def PromptForCredentials(self) -> list[str]:
        """
        Prompts the user for credentials if not available from environment
        variables or cache.

        The credential priority is:
        1. Environment variables (TCUSER, TCPASSWORD).
        2. Cached credentials from a previous successful login.
        3. Interactive prompt for username and password.

        Returns:
            A list of credential tokens: [user, password, group, role, discriminator].

        Raises:
            TcSoaExceptions.CanceledOperationException: If the user cancels the login prompt.
        """
        env_name = os.getenv("TCUSER")
        env_password = os.getenv("TCPASSWORD")
        env_group = os.getenv("TCGROUP")
        env_role = os.getenv("TCROLE")

        if env_group:
            self.group = env_group
        if env_role:
            self.role = env_role

        # Priority 1: Use environment variables if both are fully provided
        if env_name and env_password:
            self.name = env_name
            self.password = env_password
            logger.info(f"Using credentials from environment - User: {self.name}, Group: {self.group or 'default'}, Role: {self.role or 'default'}")
        # Priority 2: If env vars are not sufficient, check cached credentials.
        # If they are also not sufficient, then prompt.
        elif not self.name or not self.password:
            try:
                print("Please enter user credentials (empty User Name to quit):", flush=True)

                # Prompt for name.
                default_user = self.name or os.getenv("TCUSER", "hvanniekerk")
                temp_name = input(f"User Name [{default_user}]: ")
                if not temp_name and default_user:
                    self.name = default_user
                elif temp_name:
                    self.name = temp_name
                else:
                    raise TcSoaExceptions.CanceledOperationException("User cancelled login: User Name not provided.")

                self.password = getpass.getpass("Password:  ")

            except (EOFError, KeyboardInterrupt):
                message = "Login cancelled by user during credential input."
                print(f"\n{message}")
                raise TcSoaExceptions.CanceledOperationException(message)
            except System.IO.IOException as e_io:
                message = f"Failed to read user credentials due to IO error.\n{e_io.Message}"
                print(message)
                raise TcSoaExceptions.CanceledOperationException(message)

        tokens = [self.name or "", self.password or "", self.group or "", self.role or "", self.discriminator]
        return tokens

    def GetCredentials(
        self,
        e: Exceptions2006.InvalidUserException | Exceptions2006.InvalidCredentialsException
    ) -> list[str]:
        """
        Handles a credential challenge from the server, typically after a session
        timeout or initial login failure.

        This method is called by the SOA framework when a service request fails
        due to an invalid user or credentials. It logs the error and re-prompts
        for credentials.

        Args:
            e: The exception from the server indicating the cause of failure.

        Returns:
            A new list of credential tokens from PromptForCredentials.
        """
        if isinstance(e, Exceptions2006.InvalidUserException):
            logger.warning(
                f"Server reported user '{self.name or 'unknown'}' as invalid. Please re-enter credentials."
            )
            # Invalidate cached name to ensure re-prompt
            self.name = None
            self.password = None
            return self.PromptForCredentials()
        elif isinstance(e, Exceptions2006.InvalidCredentialsException):
            logger.warning(f"Invalid credentials provided: {e.Message}. Please try again.")
            # Invalidate cached password
            self.password = None
            return self.PromptForCredentials()
        else:
            logger.error(f"Unexpected exception type {type(e)} in GetCredentials. Prompting for credentials.")
            self.name = None
            self.password = None
            return self.PromptForCredentials()

    def SetUserPassword(self, user: str, password: str, discriminator: str):
        """
        Caches the user, password, and discriminator after a successful login.
        This method is called by the SOA framework after the `SessionService.Login`
        operation succeeds.

        Args:
            user: The successfully authenticated username.
            password: The password used for authentication.
            discriminator: The session discriminator.
        """
        self.name = user
        self.password = password
        self.discriminator = discriminator or self.discriminator
