"""
Manages Teamcenter SOA session, connection, login, logout, and provides utility functions.
"""

import clr

assy1 = clr.AddReference("TcSoaCoreStrong")  # type: ignore
assy2 = clr.AddReference("TcSoaStrongModel")  # type: ignore
assy3 = clr.AddReference("TcSoaClient")  # type: ignore
assy4 = clr.AddReference("TcSoaCommon")  # type: ignore

import System  # type: ignore
import System.Collections  # type: ignore
import System.Net  # type: ignore

import Teamcenter.Schemas.Soa._2006_03.Exceptions as Exceptions2006  # type: ignore
import Teamcenter.Soa as TcSoa  # type: ignore
import Teamcenter.Soa.Client as TcSoaClient  # type: ignore
import Teamcenter.Soa.Client.Model as TcSoaClientModel  # type: ignore
from Teamcenter.Soa.Client.Model import ModelObject  # type: ignore
import Teamcenter.Soa.Exceptions as TcSoaExceptions  # type: ignore
import Teamcenter.Services.Strong.Core as TcServCore  # type: ignore
from Teamcenter.Soa.Client.Model.Strong import WorkspaceObject, User  # type: ignore

from .AppXCredentialManager import AppXCredentialManager
from .AppXExceptionHandler import AppXExceptionHandler
from .AppXRequestListener import AppXRequestListener
from .AppXPartialErrorListener import AppXPartialErrorListener
from .AppXModelEventListener import AppXModelEventListener

# At the top of your Session.py, after other imports
import logging

logger = logging.getLogger(__name__)  # Or a more specific name like "tc_clientx.session"


class Session:
    """
    Manages a singleton Teamcenter SOA session, including connection,
    authentication, and common SOA client configurations.

    Attributes:
        connection (TcSoaClient.Connection | None): The static, shared connection to Teamcenter.
        credentialManager (AppXCredentialManager): The static, shared credential manager.
    """

    __namespace__ = "PyTC_Session"

    connection: TcSoaClient.Connection | None = None
    # The credentialManager is used both by the Session class and the Teamcenter
    # Services Framework to get user credentials.
    credentialManager: AppXCredentialManager = AppXCredentialManager()

    def __init__(self, host: str) -> None:
        """
        Initializes the singleton Teamcenter SOA session and connection.

        If a connection has not already been established, this method creates
        and configures a new TcSoaClient.Connection object. It sets up
        protocol, exception handlers, and various event listeners.

        If a connection already exists, it verifies the host. If the provided
        host differs from the existing connection's host, a warning is issued.

        Args:
            host: The Teamcenter server host URL (e.g., "http://server/tc" or "tccs/EnvironmentName").
        """
        # If connection already exists, handle it
        if Session.connection is not None:
            if Session.connection.ServerHost != host:
                logger.warning(
                    "Session is already initialized with host '%s'. "
                    "Ignoring request to initialize with new host '%s'. "
                    "To connect to a different server, the current session management strategy "
                    "requires explicit reset or application restart.",
                    Session.connection.ServerHost,
                    host,
                )
            # If host is the same, or different but we're ignoring, nothing more to do in __init__.
            return

        # Session.connection is None, so this is the first-time initialization.
        logger.info("Initializing Teamcenter session with host: %s", host)

        proto = None
        envNameTccs = None

        if host.startswith("http"):
            proto = TcSoa.SoaConstants.HTTP
        elif host.startswith("tccs"):
            proto = TcSoa.SoaConstants.TCCS
            parts = host.split("/", 1)
            if len(parts) > 1 and parts[1]:
                envNameTccs = parts[1]
            else:
                # This is a configuration concern if TCCS environment name is expected.
                logger.error(
                    "Could not extract environment name from TCCS host '%s'. Expected format 'tccs/EnvironmentName'.",
                    host,
                )
                # Depending on strictness, could raise ValueError here.
                # For now, allows proceeding; connection might use defaults or fail later.

        if proto is None:
            logger.error("Unsupported protocol or invalid host format: %s", host)
            raise ValueError(f"Unsupported protocol or invalid host format for Teamcenter session: {host}")

        try:
            # Create the Connection object
            Session.connection = TcSoaClient.Connection(
                host,  # For HTTP, full URL. For TCCS, "tccs" or "tccs/EnvName".
                System.Net.CookieCollection(),
                Session.credentialManager,
                TcSoa.SoaConstants.REST,  # binding
                proto,  # protocol
                False,  # enableCompression
            )

            if proto == TcSoa.SoaConstants.TCCS:
                if envNameTccs:
                    Session.connection.SetOption(TcSoaClient.Connection.TCCS_ENV_NAME, envNameTccs)  # type: ignore
                else:
                    # This implies host was "tccs" without "/EnvName" and an error was logged.
                    # Connection might rely on client-side FMS/TCCS environment variables.
                    logger.warning(
                        "TCCS connection initialized for host '%s' without an explicit environment name. "
                        "Ensure FMS_WINDOWS_TCCS_ENABLED and TCCS_ENVS are correctly set on the client, "
                        "or provide host as 'tccs/EnvironmentName'.",
                        host,
                    )

            Session.connection.ExceptionHandler = AppXExceptionHandler()  # type: ignore
            Session.connection.ModelManager.AddPartialErrorListener(AppXPartialErrorListener())  # type: ignore
            Session.connection.ModelManager.AddModelEventListener(AppXModelEventListener())  # type: ignore
            TcSoaClient.Connection.AddRequestListener(AppXRequestListener())
            logger.info("Teamcenter session initialized successfully for host: %s", host)

        except Exception as e:
            logger.critical("Failed to initialize Teamcenter connection: %s", e, exc_info=True)
            Session.connection = None  # Ensure connection is None if initialization failed
            raise  # Re-raise the exception to signal failure to the caller

    # Get the single Connection object for the application
    # return connection
    @staticmethod
    def getConnection() -> TcSoaClient.Connection | None:
        return Session.connection

    # Login to the Teamcenter Server
    def login(self) -> User | None:
        # Get the service stub
        # self.sessionService = TcServCore.SessionService.getService(Session.connection)
        session_service = TcServCore.SessionService.getService(Session.connection)
        credentials: list[str] | None = None
        try:
            # Prompt for credentials until they are right, or until user cancels
            # self.credentials = Session.credentialManager.PromptForCredentials()
            credentials = Session.credentialManager.PromptForCredentials()
            while True:
                if isinstance(credentials, list) and len(credentials) == 5:
                    # Ensure credentials are valid before proceeding
                    if not all(credentials):
                        raise TcSoaExceptions.CanceledOperationException(
                            "User cancelled login: Incomplete credentials."
                        )
                    try:
                        # Execute the service operation resp: Session2006.LoginResponse
                        resp = session_service.Login(
                            credentials[0],  # username
                            credentials[1],  # password
                            credentials[2],  # group
                            credentials[3],  # role
                            credentials[4],  # discriminator
                        )
                        return resp.User
                    except Exceptions2006.InvalidCredentialsException as e:
                        logger.info("Invalid credentials, attempting to get new credentials.")
                        # Credential manager might re-prompt or provide updated credentials
                        credentials = Session.credentialManager.GetCredentials(e)
                        if not credentials:  # If GetCredentials returns None (e.g., user cancelled)
                            logger.info("Credential retrieval cancelled after invalid login attempt.")
                            break
                        # Loop will continue with new credentials

        # User canceled the operation, don't need to tell him again
        except TcSoaExceptions.CanceledOperationException as e:
            pass

        return None

    # Terminate the session with the Teamcenter Server
    def logout(self) -> None:
        if Session.connection:  # Ensure connection exists before trying to logout
            session_service = TcServCore.SessionService.getService(Session.connection)
            try:
                # Execute the service operation
                session_service.Logout()
            except Exceptions2006.ServiceException:
                logger.warning(
                    "ServiceException during logout. Session might not have been active.", exc_info=True
                )  # exc_info=True adds stack trace
                pass

    @staticmethod
    def getUsers(objects: list[TcSoaClientModel.ModelObject]) -> None:
        if not objects:  # Handles None or empty list
            return

        dmService = TcServCore.DataManagementService.getService(Session.getConnection())
        unKnownUsers = []

        for obj in objects:
            if not isinstance(obj, WorkspaceObject):
                continue

            owner_candidate = None  # To hold the User object if successfully retrieved
            try:
                # Attempt to get the owner User object (might be a proxy or None)
                potential_owner = obj.Owning_user
                if potential_owner and isinstance(potential_owner, User):
                    owner_candidate = potential_owner
                    # Access a property to check if it's loaded; this might trigger NotLoadedException
                    _ = owner_candidate.User_name
            except TcSoaExceptions.NotLoadedException:
                # This means Owning_user itself was not loaded, or User_name on a valid User proxy was not.
                # If owner_candidate is a User object, it needs its properties loaded.
                if owner_candidate and owner_candidate not in unKnownUsers:
                    unKnownUsers.append(owner_candidate)
            # Other exceptions are not caught here, allowing them to propagate if critical.

        if unKnownUsers:
            logger.debug("Loading 'user_name' for %d User objects.", len(unKnownUsers))
            dmService.GetProperties(unKnownUsers, ["user_name"])

    @staticmethod
    def printObjects(objects: list[TcSoaClientModel.ModelObject]) -> None:
        if not objects:  # Handles None or empty list
            return

        # Ensure that the referenced User objects that we will use below are loaded
        Session.getUsers(objects)

        print(f"{'Number':<20s}{'Owner':<40s}{'Last Modified':<26s}{'Type':<26s}{'Name':<100s}{'User':<15s}")
        print(f"{'='*18:<20s}{'='*38:<40s}{'='*24:<26s}{'='*24:<26s}{'='*98:<100s}{'='*13:<15s}")
        for obj in objects:
            if not isinstance(obj, WorkspaceObject):
                continue

            try:
                onumber = obj.Object_string
                if "~" in onumber:  # Specific formatting for object_string
                    onumber = onumber.split("~")[0]
                obj_desc = obj.Object_desc
                ouser = obj.Owning_user
                user_id = ""
                user_name = "N/A"
                if ouser:  # Check if owning_user exists
                    user_id = ouser.User_id if ouser.User_id else ""
                    user_name = ouser.User_name if ouser.User_name else "N/A"

                olastModified = obj.Last_mod_date.ToString()
                otype = obj.Object_type

                print(f"{onumber:<20s}{user_name:<40s}{olastModified:<26s}{otype:<26s}{obj_desc:<100s}{user_id:<15s}")

            except TcSoaExceptions.NotLoadedException as e:
                # Print out a message, and skip to the next item in the folder
                logger.warning(
                    f"Could not print all details for object '{obj.Uid if obj else 'N/A'}': {e.Message} "
                    "Properties might not be loaded or not available. "
                    "Check property policy or ensure GetProperties was called for all required attributes."
                )
                # Continue to print what we can, or skip if essential info is missing.
                # For now, we just log and the loop continues to the next object.
