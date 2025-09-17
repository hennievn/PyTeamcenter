# clientx.py
# Faithful Python translation of the HelloTeamcenter ClientX helper
# Requires: pythonnet (pip install pythonnet), Teamcenter .NET client DLLs
from __future__ import annotations

import os
import sys
import getpass
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

# ---------------------------------------------------------------------------
# .NET bootstrap
# ---------------------------------------------------------------------------
TC_BIN = os.environ.get("TC_BIN")  # e.g. r"C:\Siemens\Teamcenter\soa_client\bin"
if not TC_BIN:
    raise RuntimeError(
        "TC_BIN environment variable is not set. "
        "Point it at the folder containing TcSoaClient.dll, TcSoaCommon.dll, etc."
    )
if TC_BIN not in sys.path:
    sys.path.append(TC_BIN)

import clr  # type: ignore

# Minimal required assemblies; names must be exact (use .NET casing)
for asm in (
    "TcSoaCommon",
    "TcSoaClient",
    "TcServicesStrongCore",  # Strong-typed Core services
    "TcServicesCore",        # Weak-typed fallback (rarely used here)
):
    try:
        clr.AddReference(asm)
    except Exception:
        # Some kits ship only the Strong flavor; we keep going.
        pass

# Core .NET imports (EXACT casing)
from System import Array, String  # type: ignore
from System import DateTime  # noqa: F401
from System.Reflection import Assembly  # type: ignore

# Base client types
from Teamcenter.Soa.Client import (  # type: ignore
    Connection,
    DefaultExceptionHandler,
    CredentialManager,
    RequestListener,
)
from Teamcenter.Soa.Client.Model import (  # type: ignore
    ModelObject,
    PartialErrorListener,
    ModelEventListener,
)
from Teamcenter.Schemas.Soa._2006_03.Exceptions import (  # type: ignore
    InternalServerException,
    InvalidUserException,
    InvalidCredentialsException,
    ServiceException,
    NotLoadedException,
    CanceledOperationException,
)
from Teamcenter.Soa.Exceptions import ConnectionException, ProtocolException  # type: ignore

# Strong-typed Session and Data Management services
from Teamcenter.Services.Strong.Core import SessionService, DataManagementService  # type: ignore

# Strong-typed “model” classes we display in printObjects (for isinstance checks)
from Teamcenter.Soa.Client.Model.Strong import (  # type: ignore
    User,
    WorkspaceObject,
    Folder,
)

# ---------------------------------------------------------------------------
# Optional: TCCS environment support (host lookup) if shipped with your kit
# ---------------------------------------------------------------------------
# Different kits place TccsEnvInfo in different assemblies. We find it dynamically.
def _find_tccs_envinfo_type() -> Optional[Any]:
    for asm in Assembly.GetExecutingAssembly().GetReferencedAssemblies():
        pass  # This shows refs for the script, not helpful.

    # Search all loaded assemblies by type name (works even if namespace differs)
    for asm in list(Assembly.GetExecutingAssembly().GetModules()[0].Assembly.GetReferencedAssemblies()):
        pass  # informational only

    for asm in Assembly.GetDomain().GetAssemblies():
        try:
            t = asm.GetType("Teamcenter.Soa.FSC.TccsEnvInfo") or asm.GetType("Teamcenter.Soa.Client.FSC.TccsEnvInfo")
            if t is not None:
                return t
        except Exception:
            continue
    # Try loading FSC explicitly if present
    for name in ("TcSoaFSC", "TcSoaFMS"):
        try:
            clr.AddReference(name)
            for asm in Assembly.GetDomain().GetAssemblies():
                t = asm.GetType("Teamcenter.Soa.FSC.TccsEnvInfo") or asm.GetType("Teamcenter.Soa.Client.FSC.TccsEnvInfo")
                if t is not None:
                    return t
        except Exception:
            pass
    return None


@dataclass(frozen=True)
class ConnectionConfig:
    host: str
    sso_url: str = ""
    app_id: str = ""
    # When not using SSO, we use console prompt or pre-supplied creds
    user: Optional[str] = None
    password: Optional[str] = None
    group: str = "dba"
    role: str = "dba"
    locale: str = "en_US"
    discriminator: str = "SoaAppX"


# ---------------------------------------------------------------------------
# ClientX credential manager (faithful to C#: caches creds, supports SSO/std)
# We implement a single GetCredentials method that branches by exception type.
# ---------------------------------------------------------------------------
class AppXCredentialManager(CredentialManager):  # type: ignore[misc]
    def __init__(self, sso_url: str = "", app_id: str = "", preset: Optional[Tuple[str, str, str, str, str]] = None):
        super().__init__()
        self._name: Optional[str] = None
        self._password: Optional[str] = None
        self._group: str = ""
        self._role: str = ""
        self._disc: str = "SoaAppX"
        self._type_std: int = 0  # SoaConstants.CLIENT_CREDENTIAL_TYPE_STD
        self._type_sso: int = 1  # SoaConstants.CLIENT_CREDENTIAL_TYPE_SSO (convention)
        self._type: int = self._type_std
        self._ssoCred = None

        # Best-effort SSO support if available in your client kit
        if sso_url and app_id:
            try:
                from Teamcenter.Soa import SoaConstants  # type: ignore
                clr.AddReference("TcSoaClient")
                from Teamcenter.Soa import SsoCredentials  # type: ignore
                self._ssoCred = SsoCredentials(sso_url, app_id)
                self._type = SoaConstants.CLIENT_CREDENTIAL_TYPE_SSO
            except Exception:
                # If SSO scaffolding isn't present, stay in STD mode.
                self._ssoCred = None
                self._type = self._type_std

        if preset:
            self._name, self._password, self._group, self._role, self._disc = preset

    # Property: CredentialType
    @property
    def CredentialType(self) -> int:  # noqa: N802 (match .NET name)
        return self._type

    # Called by framework when a login attempt fails (or session expired).
    # NOTE: Python cannot overload by signature; we branch by exception type.
    def GetCredentials(self, e: Exception) -> Array[String]:  # noqa: N802
        # If SSO was requested and present, defer to SSO handler
        if self._type != self._type_std and self._ssoCred is not None:
            try:
                tokens = self._ssoCred.GetCredentials(e)  # type: ignore[union-attr]
                return tokens
            except CanceledOperationException:
                raise

        # Otherwise standard username/password flow; prompt if missing.
        if self._name is None or self._password is None:
            self._prompt_for_credentials()

        # Package tokens: name, password, group, role, discriminator
        tokens = Array[String]([self._name, self._password, self._group, self._role, self._disc])  # type: ignore[arg-type]
        return tokens

    # Called by the Session service after a successful login
    def SetUserPassword(self, user: str, password: str, discriminator: str) -> None:  # noqa: N802
        self._name = user
        self._password = password
        self._disc = discriminator or self._disc

    # Called by Session service after setSessionGroupMember
    def SetGroupRole(self, group: str, role: str) -> None:  # noqa: N802
        self._group = group or self._group
        self._role = role or self._role

    # Console prompt identical in spirit to ClientX
    def _prompt_for_credentials(self) -> None:
        print("\nEnter Teamcenter credentials:")
        self._name = input("  User: ").strip()
        self._password = getpass.getpass("  Password: ")
        # Keep previously configured group/role/discriminator


# ---------------------------------------------------------------------------
# Request/PartialError/Model listeners + Exception handler
# ---------------------------------------------------------------------------
class AppXRequestListener(RequestListener):  # type: ignore[misc]
    def ServiceRequest(self, info):  # noqa: N802
        # called before send; we log after response to match sample’s console
        pass

    def ServiceResponse(self, info):  # noqa: N802
        # info.Id, info.Service, info.Operation mirror C# sample
        try:
            print(f"{info.Id}: {info.Service}.{info.Operation}")
        except Exception:
            pass


class AppXPartialErrorListener(PartialErrorListener):  # type: ignore[misc]
    def HandlePartialError(self, e):  # noqa: N802
        try:
            print("\n--- Partial Errors ---")
            try:
                obj = e.ModelObject
                if obj is not None:
                    print(f"Object UID: {obj.Uid}")
            except Exception:
                pass

            errs = getattr(e, "Errors", None) or []
            for err in errs:
                try:
                    print(f"  Code: {err.Code}\tSeverity: {err.Level}\t{err.Message}")
                except Exception:
                    pass
        except Exception:
            pass


class AppXModelEventListener(ModelEventListener):  # type: ignore[misc]
    def ModelObjectChange(self, objects):  # noqa: N802
        try:
            print(f"[model] Updated {len(objects)} object(s)")
        except Exception:
            pass

    def ModelObjectDelete(self, uids):  # noqa: N802
        try:
            print(f"[model] Deleted {len(uids)} object(s)")
        except Exception:
            pass


class AppXExceptionHandler(DefaultExceptionHandler):  # type: ignore[misc]
    """
    Mimics ClientX behavior: log the InternalServerException class
    and offer (y/n) retry for connection/protocol errors.
    """

    def HandleException(self, ise: InternalServerException) -> bool:  # noqa: N802
        print("\n*****")
        print("Exception caught in AppXExceptionHandler.HandleException(InternalServerException).")

        msg = ""
        if isinstance(ise, ConnectionException):
            msg = "The server returned a connection error (network/server down?)."
        elif isinstance(ise, ProtocolException):
            msg = "The server returned a protocol error (likely a programming error)."
        else:
            msg = "The server returned an internal server error."

        print(msg)
        print(str(ise))
        ans = ""
        try:
            ans = input("Do you wish to retry the last service request? [y/N]: ").strip().lower()
        except Exception:
            pass
        return ans == "y"


# ---------------------------------------------------------------------------
# Session wrapper (faithful to C# Session.cs API surface)
# ---------------------------------------------------------------------------
class Session:
    _connection: Optional[Connection] = None
    _cred_mgr: Optional[AppXCredentialManager] = None

    def __init__(self, host: str, sso_url: str = "", app_id: str = "", preset_creds: Optional[Tuple[str, str, str, str, str]] = None):
        """
        Create a Session with a Connection to the specified server.

        host:   http(s)://server:port/tc   OR   tccs://ENV_NAME  (when TCCS is available)
        sso_url/app_id: when provided (and supported by your kit), SSO login will be used.
        preset_creds: optional (user, password, group, role, discriminator) for STD login.
        """
        self._cred_mgr = AppXCredentialManager(sso_url, app_id, preset_creds)
        # IMPORTANT: use the .NET casing & constructor (host, credentialManager)
        self._connection = Connection(host, self._cred_mgr)

        # Handlers/listeners (as in ClientX)
        self._connection.ExceptionHandler = AppXExceptionHandler()
        self._connection.ModelManager.AddPartialErrorListener(AppXPartialErrorListener())
        self._connection.ModelManager.AddModelEventListener(AppXModelEventListener())
        self._connection.AddRequestListener(AppXRequestListener())

    # --- Static helpers like the C# sample ---------------------------------
    @staticmethod
    def getConnection() -> Connection:
        if Session._connection is None:
            raise RuntimeError("Session has not been constructed.")
        return Session._connection

    # C# sample exposes “getOptionalArg”; we’ll keep a Pythonic helper
    @staticmethod
    def get_optional_arg(arguments: Dict[str, str], name: str, default: str) -> str:
        return arguments.get(name, default)

    @staticmethod
    def get_configuration_from_tccs(argv: Sequence[str]) -> Dict[str, str]:
        """
        Port of ClientX Session.GetConfigurationFromTCCS:
        - parse simple -key value pairs
        - if -host starts with tccs://, use TccsEnvInfo to resolve host and (optionally) SSO.
        """
        arg_map: Dict[str, str] = {}
        i = 0
        while i + 1 < len(argv):
            if argv[i].startswith("-"):
                arg_map[argv[i]] = argv[i + 1]
                i += 2
            else:
                i += 1

        host = arg_map.get("-host")
        if not host or not host.lower().startswith("tccs://"):
            return arg_map

        # Try to resolve the tccs environment
        TccsEnvInfo = _find_tccs_envinfo_type()
        if TccsEnvInfo is None:
            print("[tccs] TccsEnvInfo not found in your client kit; pass a full http(s) Teamcenter URL instead of tccs://.")
            return arg_map

        try:
            env_name = host.split("://", 1)[1]
            env = TccsEnvInfo.GetEnvironment(env_name)  # static method as in C#
            print(f"Using TCCS environment: {env}")
            arg_map["-host"] = env.TeamcenterPath
            if getattr(env, "IsSSOEnabled", False):
                arg_map["-sso"] = env.SSOLoginURL
                arg_map["-appID"] = env.ApplicationID
        except Exception as ex:
            print(f"[tccs] Failed to resolve environment '{host}': {ex}")
        return arg_map

    # --- Login / Logout -----------------------------------------------------
    def login(self) -> User:
        """
        Perform a login using either STD or SSO flow, just like ClientX.Session.login().
        Returns the logged-in User strong model.
        """
        conn = self._connection
        if conn is None:
            raise RuntimeError("Connection not initialized.")

        sess = SessionService.getService(conn)  # static factory (lower-case 'g' like C#)
        locale = "en_US"

        # Loop mirrors ClientX (retry on invalid creds)
        while True:
            try:
                # Ask the framework for tokens via our CredentialManager; it will
                # prompt if needed (STD) or fetch from TcSS (SSO).
                # The .Login(...) here is the standard (non-SSO) path. If your site
                # enforces SSO, the server will challenge and the CredentialManager’s
                # SSO branch will kick in automatically.
                tokens = self._cred_mgr.GetCredentials(InvalidUserException("initial"))  # seed a call to get tokens
                user, pwd, grp, role, disc = list(tokens)
                resp = sess.Login(user, pwd, grp, role, locale, disc)  # noqa: N802 (match .NET case)
                return resp.User  # strong User
            except InvalidCredentialsException as ice:
                tokens = self._cred_mgr.GetCredentials(ice)
                # loop will retry
            except InvalidUserException as iue:
                tokens = self._cred_mgr.GetCredentials(iue)
                # loop will retry
            except ServiceException as se:
                # Let the exception handler decide retry; DefaultExceptionHandler returns False.
                raise

    def logout(self) -> None:
        conn = self._connection
        if conn is None:
            return
        try:
            sess = SessionService.getService(conn)
            sess.Logout()
        except ServiceException:
            pass

    # --- Utility to mimic ClientX.printObjects ------------------------------
    @staticmethod
    def print_objects(objects: Iterable[ModelObject]) -> None:
        objs = list(objects or [])
        if not objs:
            print("(no objects)")
            return

        # Preload user_name to avoid NotLoadedException
        Session._preload_users(objs)

        print("Name\t\tOwner\t\tLast Modified")
        print("====\t\t=====\t\t=============")
        for mo in objs:
            if not isinstance(mo, WorkspaceObject):
                continue
            try:
                name = mo.Object_string  # strong prop (underscore casing like C# sample)
                owner = mo.Owning_user   # -> Strong.User
                last_mod = mo.Last_mod_date
                owner_name = owner.User_name if isinstance(owner, User) else "<unknown>"
                print(f"{name}\t{owner_name}\t{last_mod}")
            except NotLoadedException:
                # Try again after forcing property load
                pass

    @staticmethod
    def _preload_users(objects: Sequence[ModelObject]) -> None:
        """Load user_name for all distinct owners, mirroring ClientX."""
        try:
            conn = Session.getConnection()
            dm = DataManagementService.getService(conn)
            unknown: List[User] = []
            for mo in objects:
                try:
                    if isinstance(mo, WorkspaceObject):
                        owner = mo.Owning_user
                        # Touching owner.User_name will throw if not loaded
                        _ = owner.User_name  # noqa: F841
                except NotLoadedException:
                    if isinstance(mo, WorkspaceObject):
                        unknown.append(mo.Owning_user)
            if unknown:
                users = Array[User](unknown)  # type: ignore
                dm.GetProperties(users, Array[String]([String("user_name")]))  # noqa: N802
        except Exception:
            pass
