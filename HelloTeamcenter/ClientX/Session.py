"""
Manages Teamcenter SOA session, connection, login (classic first, SSO fallback), and logout.

This version is updated for Teamcenter 2406. It tries **classic/password** login first
for maximum compatibility and then, if appropriate, falls back to SSO via
Teamcenter Security Services (TcSS).
"""

import os
import clr
import logging

# Find and load Teamcenter assemblies. This executes the setup logic in tc_utils
# to find TC_LIBS, add it to the path, set up resolvers, and load all necessary
# .NET assembly references.
# from teamcenter_get_drawings import tc_utils
import tc_utils

# .NET imports can now succeed because tc_utils has prepared the environment
import System  # type: ignore
import System.Net  # type: ignore
import Teamcenter.Schemas.Soa._2006_03.Exceptions as Exceptions2006  # type: ignore
import Teamcenter.Soa as TcSoa  # type: ignore
import Teamcenter.Soa.Client as TcSoaClient  # type: ignore
import Teamcenter.Soa.Exceptions as TcSoaExceptions  # type: ignore
import Teamcenter.Services.Strong.Core as TcServCore  # type: ignore
from Teamcenter.Services.Strong.Core._2011_06 import Session as Session2011  # type: ignore
from Teamcenter.Soa.Client.Model.Strong import User  # type: ignore

# Local helpers
from .AppXCredentialManager import AppXCredentialManager
from .AppXExceptionHandler import AppXExceptionHandler
from .AppXRequestListener import AppXRequestListener
from .AppXPartialErrorListener import AppXPartialErrorListener
from .AppXModelEventListener import AppXModelEventListener

logger = logging.getLogger("ClientX.Session")


class Session:
    """
    Singleton-style holder for the Teamcenter SOA Connection and login logic.
    This class ensures that only one connection is established and reused.
    """
    __namespace__ = "PyTC_Session"

    # Class-level attributes to maintain a single session state
    current_user: User | None = None
    _logged_in: bool = False
    connection: TcSoaClient.Connection | None = None
    credentialManager: AppXCredentialManager = AppXCredentialManager()

    def __init__(self, host: str) -> None:
        """
        Initialize the Teamcenter connection if not already established.

        Args:
            host: The Teamcenter server URL, either HTTP (e.g., "http://server:port/tc")
                  or TCCS (e.g., "tccs[/EnvironmentName]").
        """
        if Session.connection is not None:
            # If already initialized, log a warning if the host differs but reuse the existing connection.
            if Session.connection.HostPath != host:
                logger.warning(
                    "Session already initialized for host '%s'; ignoring request for new host '%s'.",
                    Session.connection.HostPath,
                    host,
                )
            return

        logger.info("Initializing Teamcenter session with host: %s", host)

        # Determine protocol from host string
        if host.startswith("http"):
            proto = TcSoa.SoaConstants.HTTP
        elif host.startswith("tccs"):
            proto = TcSoa.SoaConstants.TCCS
        else:
            logger.error("Unsupported protocol or invalid host format: %s", host)
            raise ValueError(f"Unsupported host for Teamcenter: {host}")

        # Build the connection object
        try:
            Session.connection = TcSoaClient.Connection(
                host,
                System.Net.CookieCollection(),
                Session.credentialManager,  # Handles credentials on 401/expired session
                TcSoa.SoaConstants.REST,    # Binding
                proto,                      # Protocol
                False,                      # enableCompression
            )

            # Set TCCS environment name if provided in the host string
            if proto == TcSoa.SoaConstants.TCCS and "/" in host:
                env_name = host.split("/", 1)[1]
                if env_name:
                    Session.connection.SetOption(TcSoaClient.Connection.TCCS_ENV_NAME, env_name)  # type: ignore

            # Wire up all the custom handlers and listeners
            Session.connection.ExceptionHandler = AppXExceptionHandler()  # type: ignore
            Session.connection.ModelManager.AddPartialErrorListener(AppXPartialErrorListener())  # type: ignore
            Session.connection.ModelManager.AddModelEventListener(AppXModelEventListener())  # type: ignore
            TcSoaClient.Connection.AddRequestListener(AppXRequestListener())  # type: ignore

            logger.info("Teamcenter session initialized successfully for host: %s", host)
        except Exception as e:
            logger.critical("Failed to initialize Teamcenter connection: %s", e, exc_info=True)
            Session.connection = None  # Ensure connection is None on failure
            raise

    @staticmethod
    def getConnection() -> TcSoaClient.Connection | None:
        """Returns the active Teamcenter SOA connection object."""
        return Session.connection

    @staticmethod
    def is_logged_in() -> bool:
        """Returns True if the session is currently logged in."""
        return Session._logged_in

    def login(self) -> User | None:
        """
        Log in to Teamcenter. Tries classic (user/password) login first, then
        falls back to SSO if appropriate environment indicators are present.

        Returns:
            The logged-in User object, or None if login was cancelled or failed.
        """
        conn = Session.connection
        if conn is None:
            logger.error("No active Teamcenter connection. Call Session(host) first.")
            return None

        session_service = TcServCore.SessionService.getService(conn)
        if session_service is None:
            logger.error("Failed to retrieve SessionService from the connection.")
            return None
        logger.info("SessionService retrieved successfully.")

        # --- 1. Attempt Classic Login ---
        user = self._login_classic(session_service)
        if user:
            return user

        # --- 2. Attempt SSO Fallback if applicable ---
        sso_login_url = os.getenv("TC_SSO_LOGIN_URL", "").strip()
        sso_app_id = os.getenv("TC_SSO_APP_ID", "Teamcenter").strip()
        sso_proxy_url = os.getenv("TC_SSO_PROXY_URL", "").strip()
        tc_auth_mode = (os.getenv("TC_AUTH") or "").strip().upper()

        # Heuristic to detect misconfigured SSO URL (pointing to /tc is wrong)
        host_url = getattr(conn, "HostPath", "")
        if sso_login_url and host_url and sso_login_url.rstrip("/") == host_url.rstrip("/"):
            logger.warning("TC_SSO_LOGIN_URL is set to the Teamcenter web URL, which is incorrect. Ignoring it to allow auto-discovery.")
            sso_login_url = ""

        # Determine if SSO should be attempted
        try_sso = bool(sso_login_url) or tc_auth_mode == "SSO" or (conn.Protocol == TcSoa.SoaConstants.TCCS)

        if try_sso:
            user = self._login_sso(session_service, sso_app_id, sso_login_url, sso_proxy_url)
            if user:
                return user

        logger.error("All login methods (Classic and SSO) failed.")
        return None

    def _login_sso(self, session_service, app_id: str, login_url: str, proxy_url: str) -> User | None:
        """Internal helper to perform SSO login via SessionService.LoginSSO."""
        self.credentialManager.use_sso()
        discriminator = os.getenv("TC_SESSION_DISCRIMINATOR") or self.credentialManager.discriminator

        # Resolve an SSO user-id hint from environment or system
        user_hint = os.getenv("TC_SSO_USER") or os.getenv("TC_USER")
        if not user_hint:
            try:
                # On Windows, get username from identity (e.g., DOMAIN\user -> user)
                win_identity = System.Security.Principal.WindowsIdentity.GetCurrent().Name
                user_hint = win_identity.split("\\")[-1]
            except Exception:
                try:
                    user_hint = os.getlogin()
                except Exception:
                    pass

        sso_token = os.getenv("TC_SSO_TOKEN", "").strip()
        sso_group = os.getenv("TCGROUP", "").strip()
        sso_role = os.getenv("TCROLE", "").strip()
        locale = os.getenv("TC_LOCALE", "").strip()

        if not sso_token:
            logger.error("SSO token (TC_SSO_TOKEN) is not set; cannot attempt SSO login.")
            self.credentialManager.use_standard()
            return None

        creds = Session2011.Credentials()
        creds.User = user_hint or ""
        creds.Password = sso_token
        creds.Group = sso_group
        creds.Role = sso_role
        creds.Locale = locale
        creds.Descrimator = discriminator

        logger.info(
            "Attempting SSO login with credential manager token (user_hint=%s, locale=%s)...",
            user_hint or "<none>",
            locale or "<server default>",
        )

        try:
            resp = session_service.LoginSSO(creds)
            Session.credentialManager.SetUserPassword(creds.User, creds.Password, discriminator)
            logger.info("SSO login succeeded.")
            Session.current_user = resp.User
            Session._logged_in = True
            return resp.User
        except Exceptions2006.InvalidCredentialsException as e:
            logger.warning("SSO failed with invalid credentials: %s", e.Message)
        except (TypeError, System.MissingMethodException):
            logger.error("SSO LoginSSO(Credentials) overload not supported by this kit/server.")
        except Exception as e:
            logger.error("SSO attempt failed: %s", e, exc_info=True)
        finally:
            if not Session._logged_in:
                self.credentialManager.use_standard()

        return None

    def _login_classic(self, session_service) -> User | None:
        """Internal helper for password-based login, with interactive credential prompts."""
        self.credentialManager.use_standard()
        locale = os.getenv("TC_LOCALE", "").strip()
        try:
            # Loop to allow retries on invalid credentials
            while True:
                credentials = Session.credentialManager.PromptForCredentials()
                if not (isinstance(credentials, list) and len(credentials) == 5):
                    logger.error("Credential manager returned invalid token set; aborting login.")
                    return None

                username, password, group, role, discriminator = credentials
                if not username or not password:
                    raise TcSoaExceptions.CanceledOperationException("User cancelled login or missing fields.")

                try:
                    creds = Session2011.Credentials()
                    creds.User = username
                    creds.Password = password
                    creds.Group = group
                    creds.Role = role
                    creds.Locale = locale
                    creds.Descrimator = discriminator

                    resp = session_service.Login(creds)
                    Session.credentialManager.SetUserPassword(username, password, discriminator)
                    logger.info("Classic login succeeded for user '%s'.", username)
                    Session.current_user = resp.User
                    Session._logged_in = True
                    return resp.User
                except Exceptions2006.InvalidCredentialsException as e:
                    logger.warning("Invalid credentials for user '%s'.", username)
                    # GetCredentials will re-prompt
                    Session.credentialManager.GetCredentials(e)
        except TcSoaExceptions.CanceledOperationException:
            logger.info("Login cancelled by user.")
            return None
        except Exception as e:
            logger.error("An unexpected error occurred during classic login: %s", e, exc_info=True)
            return None

    def logout(self) -> None:
        """Terminates the Teamcenter session if it is active."""
        if not Session.connection or not Session._logged_in:
            return

        logger.info("Logging out from Teamcenter...")
        try:
            session_service = TcServCore.SessionService.getService(Session.connection)
            if session_service:
                session_service.Logout()
        except Exceptions2006.ServiceException as e:
            logger.warning("ServiceException during logout (session may have already expired): %s", e.Message)
        except Exception as e:
            logger.error("An unexpected error occurred during logout: %s", e, exc_info=True)
        finally:
            # Clean up resources regardless of logout success
            try:
                # This is a static listener, so removing it might affect other connections if any
                # TcSoaClient.Connection.RemoveRequestListener(AppXRequestListener())
                pass
            except Exception:
                pass  # Ignore errors on cleanup
            Session._logged_in = False
            Session.current_user = None
            Session.connection = None
            logger.info("Session terminated and connection closed.")
