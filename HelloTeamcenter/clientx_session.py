# clientx_session.py
# A faithful Pythonnet translation of the HelloTeamcenter "clientx" layer.
from __future__ import annotations

import os
import sys
from typing import Dict, List, Optional, Sequence

# --- pythonnet bootstrap ------------------------------------------------------
try:
    import clr  # type: ignore
except Exception as e:
    raise RuntimeError("pythonnet (clr) is required. Install with: pip install pythonnet") from e

# Optional: point pythonnet at your Teamcenter client bin
TC_BIN = os.environ.get("TC_BIN")
if TC_BIN and TC_BIN not in sys.path:
    sys.path.append(TC_BIN)

# Load the core client assemblies by *name*. If you already preload via full paths,
# these calls will simply no-op.
for asm_name in ("TcSoaCommon", "TcSoaClient", "TcServicesStrongCore", "TcServicesCore"):
    try:
        clr.AddReference(asm_name)
    except Exception:
        pass

# --- .NET imports (use *exact* .NET casing) ----------------------------------
from Teamcenter.Soa.Client import (  # type: ignore
    Connection,
    RequestListener,
    ExceptionHandler,
    DefaultExceptionHandler,
    PartialErrorListener,
    TccsEnvInfo,
)
from Teamcenter.Soa.Client.Model import ModelObject  # type: ignore

# Strong session service preferred; weak is a fallback
try:
    from Teamcenter.Services.Strong.Core import SessionService  # type: ignore
    _SESSION_WEAK = False
except Exception:
    from Teamcenter.Services.Core import SessionService  # type: ignore
    _SESSION_WEAK = True

from Teamcenter.Soa.Common import SsoCredentials  # type: ignore
from Teamcenter.Schemas.Soa._2006_03.Exceptions import (  # type: ignore
    InvalidCredentialsException,
    InvalidUserException,
    NotLoadedException,
    CanceledOperationException,
    InternalServerException,
)

# ------------------------------------------------------------------------------
# Request / PartialError / ModelEvent listeners (ClientX style)
# ------------------------------------------------------------------------------

class AppXRequestListener(RequestListener):
    """Logs each SOA operation after it completes, like the C# sample."""
    def ServiceRequest(self, info):  # pre-request (quiet)
        return
    def ServiceResponse(self, info):  # post-response
        try:
            print(f"{info.Id}: {info.Service}.{info.Operation}")
        except Exception:
            pass


class AppXPartialErrorListener(PartialErrorListener):
    """Mirrors sample behavior: print partial errors attached to model objects."""
    def HandlePartialError(self, objects: Sequence[ModelObject]) -> None:
        if not objects:
            return
        for mo in objects:
            try:
                errs = mo.GetPartialErrors()
            except Exception:
                errs = None
            if not errs:
                continue
            target = getattr(mo, "Uid", "<unknown>")
            print(f"Partial errors on: {target}")
            for pe in errs:
                try:
                    print(f"    Code: {pe.Code}\tSeverity: {pe.Level}\t{pe.Message}")
                except Exception:
                    pass


# The model event API signature varies slightly between kits.
# The C# sample overrides LocalObjectChange / LocalObjectDelete.
try:
    from Teamcenter.Soa.Client.Model import ModelEventListener  # type: ignore

    class AppXModelEventListener(ModelEventListener):  # type: ignore
        def LocalObjectChange(self, objects: Sequence[ModelObject]) -> None:
            if not objects:
                return
            print("Model changes (LocalObjectChange):")
            for mo in objects:
                uid = getattr(mo, "Uid", None)
                if uid:
                    print(f"  changed: {uid}")

        def LocalObjectDelete(self, uids: Sequence[str]) -> None:
            if not uids:
                return
            print("Model deletes (LocalObjectDelete):")
            for u in uids:
                print(f"  deleted: {u}")

except Exception:
    # If your kit exposes no ModelEventListener base, keep a no-op so the rest still works.
    class AppXModelEventListener(object):  # type: ignore
        def LocalObjectChange(self, objects: Sequence[ModelObject]) -> None:  # no-op
            return
        def LocalObjectDelete(self, uids: Sequence[str]) -> None:             # no-op
            return


class AppXExceptionHandler(ExceptionHandler):
    """
    Consolidated override that handles both InternalServerException and
    CanceledOperationException. We don't import any non-existent handler types.
    """
    def HandleException(self, e) -> None:
        try:
            if isinstance(e, CanceledOperationException):
                # This matches the ClientX "fatal on cancel" behavior.
                msg = getattr(e, "Message", "Operation canceled")
                raise SystemError(msg)
            # InternalServerException and others: log and continue
            print("")
            print("*****")
            print("Exception caught in ExceptionHandler.HandleException")
            print(getattr(e, "Message", str(e)))
            sid = getattr(e, "ServiceId", None)
            if sid:
                print(f"Service ID: {sid}")
        except Exception:
            pass


# ------------------------------------------------------------------------------
# Credential Manager (interactive + SSO), faithful to ClientX/AppXCredentialManager
# ------------------------------------------------------------------------------

class AppXCredentialManager(object):
    """
    The Connection will call:
      - GetUserPasswordCredentialClientType()
      - GetCredentials(InvalidCredentialsException)
      - PromptForCredentials()
    We support both standard login and SSO via TcSS (SsoCredentials).
    """
    def __init__(self, sso_url: str = "", app_id: str = "") -> None:
        # Optional defaults via environment, mirroring typical TC setups.
        self._name: Optional[str] = os.getenv("TC_USER")
        self._password: Optional[str] = os.getenv("TC_PASSWORD")
        self._group: str = os.getenv("TC_GROUP", "")
        self._role: str = os.getenv("TC_ROLE", "")
        self._discriminator: str = os.getenv("TC_SESSION", "SoaAppX")
        self._type: int = 0  # SoaConstants.CLIENT_CREDENTIAL_TYPE_STD (0)
        self._sso: Optional[SsoCredentials] = None

        if sso_url:
            try:
                self._sso = SsoCredentials(sso_url, app_id)
                from Teamcenter.Soa import SoaConstants  # type: ignore
                self._type = getattr(SoaConstants, "CLIENT_CREDENTIAL_TYPE_SSO", 1)
            except Exception as e:
                print(f"[warn] Failed to initialize SSO credentials: {e}. Falling back to standard login.")
                self._sso = None
                self._type = 0

    def GetUserPasswordCredentialClientType(self) -> int:
        return self._type

    def GetCredentials(self, exc: InvalidCredentialsException):
        # C# sample prints server message then re-prompts or re-asks TcSS
        print(getattr(exc, "Message", "Invalid credentials."))
        if self._type == 0 or self._sso is None:
            return self.PromptForCredentials()
        return self._sso.GetCredentials(exc)

    def PromptForCredentials(self):
        # For SSO, delegate to TcSS like the C# sample does when no session exists
        if self._type != 0 and self._sso is not None:
            return self.GetCredentials(InvalidUserException("User does not have a session."))

        # Console prompts (only for what we don't have via env vars)
        try:
            if not self._name:
                self._name = input("User name: ").strip()
            if self._password is None:
                self._password = input("Password: ")
            if not self._group:
                self._group = input("Group (blank=default): ").strip()
            if not self._role:
                self._role = input("Role (blank=default): ").strip()
        except (KeyboardInterrupt, EOFError):
            msg = "Login canceled by user."
            print(msg)
            raise CanceledOperationException(msg)

        return [self._name or "", self._password or "", self._group, self._role, self._discriminator]


# ------------------------------------------------------------------------------
# Session: faithful translation of HelloTeamcenter/clientx/Session.cs
# ------------------------------------------------------------------------------

class Session:
    """
    Mirrors the C# ClientX Session class:
      - Builds Connection(host, credentialManager)
      - Attaches Exception, PartialError, Request and ModelEvent listeners
      - Provides login() / logout()
      - Exposes getConnection()
      - Includes TCCS helpers (GetConfigurationFromTCCS, GetOptionalArg)
    """
    _connection: Optional[Connection] = None

    def __init__(self, host: str, sso_url: str = "", app_id: str = "") -> None:
        # 1) Create CredentialManager
        self._cred = AppXCredentialManager(sso_url, app_id)

        # 2) Create Connection(host, credentialManager) — exact C# signature
        conn = Connection(host, self._cred)

        # 3) Add Exception handler (we do not use any non-existent ResponseExceptionHandler)
        try:
            conn.SetExceptionHandler(AppXExceptionHandler())
        except Exception:
            conn.SetExceptionHandler(DefaultExceptionHandler())

        # 4) Add listeners (optional but matches the sample)
        try:
            conn.ModelManager.AddPartialErrorListener(AppXPartialErrorListener())
        except Exception:
            pass
        try:
            conn.ModelManager.AddModelEventListener(AppXModelEventListener())
        except Exception:
            pass
        try:
            conn.AddRequestListener(AppXRequestListener())
        except Exception:
            pass

        Session._connection = conn

    @staticmethod
    def getConnection() -> Connection:
        if Session._connection is None:
            raise RuntimeError("Session has not been initialized yet.")
        return Session._connection

    # --- Login / Logout -------------------------------------------------------
    def login(self):
        # SessionService.getService(connection) — same as C# sample
        sess = SessionService.getService(Session.getConnection())  # type: ignore[attr-defined]
        creds = self._cred.PromptForCredentials()
        locale = os.getenv("TC_LOCALE", "")
        while True:
            try:
                # login(user, password, group, role, locale, discriminator)
                resp = sess.Login(creds[0], creds[1], creds[2], creds[3], locale, creds[4])
                return resp.User
            except InvalidCredentialsException as e:
                creds = self._cred.GetCredentials(e)

    def logout(self) -> None:
        sess = SessionService.getService(Session.getConnection())
        sess.Logout()

    # --- Utility methods copied from ClientX.Session --------------------------
    @staticmethod
    def printObjects(objects: Sequence[ModelObject]) -> None:
        if not objects:
            return
        Session.getUsers(objects)
        try:
            from Teamcenter.Soa.Client.Model.Strong import WorkspaceObject  # type: ignore
        except Exception:
            WorkspaceObject = None

        print("Name\t\tOwner\t\tLast Modified")
        print("====\t\t=====\t\t=============")
        for obj in objects:
            try:
                if WorkspaceObject and not isinstance(obj, WorkspaceObject):
                    continue
            except Exception:
                pass
            try:
                name = obj.Object_string
                owner = obj.Owning_user
                last_mod = obj.Last_mod_date
                owner_name = getattr(owner, "User_name", "<unknown>")
                print(f"{name}\t{owner_name}\t{last_mod}")
            except NotLoadedException as e:
                print(e.Message)
                print("The Object Property Policy is not configured with this property.")

    @staticmethod
    def getUsers(objects: Sequence[ModelObject]) -> None:
        """Ensure referenced User objects are loaded (GetProperties on 'user_name')."""
        if not objects:
            return

        users: List[ModelObject] = []
        seen: set = set()

        try:
            from Teamcenter.Soa.Client.Model.Strong import WorkspaceObject  # type: ignore
        except Exception:
            WorkspaceObject = None

        for mo in objects:
            try:
                if WorkspaceObject and not isinstance(mo, WorkspaceObject):
                    continue
            except Exception:
                pass
            try:
                usr = mo.Owning_user
                uid = usr.Uid
                if uid not in seen:
                    seen.add(uid)
                    users.append(usr)
            except Exception:
                continue

        if not users:
            return

        try:
            from Teamcenter.Services.Strong.Core import DataManagementService as DMS  # type: ignore
        except Exception:
            from Teamcenter.Services.Core import DataManagementService as DMS  # type: ignore

        dm = DMS.getService(Session.getConnection())
        dm.GetProperties(users, ["user_name"])

    # --- TCCS helpers (one-to-one with the C# sample) -------------------------
    @staticmethod
    def GetConfigurationFromTCCS(argv: Sequence[str]) -> Dict[str, str]:
        """
        Parse args and, if -host starts with 'tccs', resolve host/SSO/appid from TcSS.
        Returns a dict like {'-host': ..., '-sso-url': ..., '-appid': ...}.
        """
        args: Dict[str, str] = {}
        a = list(argv)
        for i in range(len(a) - 1):
            if a[i].startswith("-"):
                args[a[i]] = a[i + 1]

        if "-host" not in args:
            return args

        server_address = args["-host"]
        if not server_address.lower().startswith("tccs"):
            return args

        try:
            env: Optional[TccsEnvInfo] = None
            if server_address.lower().startswith("tccs://"):
                env = TccsEnvInfo.GetEnvironment(server_address[7:])
                print(f"Using the environment {env}")
            else:
                print("Query TCCS for available Teamcenter environments to connect to...")
                envs = TccsEnvInfo.GetAllEnvironments()
                env = Session._choose_environment(envs)

            if env is None:
                raise RuntimeError("TCCS did not return an environment.")

            args["-host"] = env.GetTcServerUrl()
            # Not all kits expose these methods; probe safely
            sso = getattr(env, "GetSsoServerUrl", None)
            if callable(sso):
                args["-sso-url"] = sso()
            appid = getattr(env, "GetAppId", None)
            if callable(appid):
                args["-appid"] = appid()
            return args
        except Exception as e:
            print(f"Failed to get a TCCS environment. {e}")
            return args

    @staticmethod
    def _choose_environment(envs) -> Optional[TccsEnvInfo]:
        """Prompt the user if multiple TCCS environments exist."""
        try:
            count = len(envs)
        except Exception:
            count = 0

        if count == 0:
            raise Exception("TCCS does not have any configured Teamcenter environments.")
        if count == 1:
            env = envs[0]
            print(f"Using the default environment {env}")
            return env

        try:
            print("Available Teamcenter environments:")
            print(TccsEnvInfo.ListEnvironments(envs))
        except Exception:
            for idx, e in enumerate(envs, start=1):
                print(f"  {idx}) {e}")

        sel = input(f"Select Teamcenter environment to connect to (1-{count}): ").strip()
        try:
            i = int(sel)
        except Exception:
            raise SystemExit(0)
        if i < 1 or i > count:
            raise SystemExit(0)
        return envs[i - 1]

    @staticmethod
    def GetOptionalArg(arguments: Dict[str, str], name: str, default_value: str) -> str:
        return arguments.get(name, default_value)


# --- Optional CLI demo for parity with the C# sample --------------------------
if __name__ == "__main__":
    import argparse

    p = argparse.ArgumentParser(description="ClientX-style Teamcenter login (pythonnet).")
    p.add_argument("-host", required=True, help="TC server URL, or tccs://<envName>")
    p.add_argument("-sso-url", default="", help="SSO URL (optional; usually supplied by TCCS)")
    p.add_argument("-appid", default="", help="SSO App ID (optional; usually supplied by TCCS)")
    args_ns = p.parse_args()

    arg_map = Session.GetConfigurationFromTCCS(
        ["-host", args_ns.host, "-sso-url", args_ns.sso_url, "-appid", args_ns.appid]
    )
    host = arg_map.get("-host", args_ns.host)
    sso_url = arg_map.get("-sso-url", args_ns.sso_url)
    appid = arg_map.get("-appid", args_ns.appid)

    sess = Session(host, sso_url, appid)
    user = sess.login()
    try:
        uname = getattr(user, "User_name", None) or getattr(user, "Object_string", "<user>")
        print(f"Logged in as: {uname}")
    finally:
        sess.logout()
        print("Logged out.")
