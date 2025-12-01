"""CLI entry point for the Python RuntimeBO sample."""

from __future__ import annotations

import argparse
import logging
import os

from ClientX.Session import Session

from .runtime_bo import RuntimeBOExample


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Python reproduction of the RuntimeBO ClientX sample. "
            "Creates a runtime business object and lets you set a couple of properties."
        )
    )
    parser.add_argument(
        "--host",
        default=os.getenv("TC_HOST", "http://localhost:7001/tc"),
        help="Teamcenter SOA host URL. Defaults to %(default)s or $TC_HOST.",
    )
    parser.add_argument(
        "--sso-login-url",
        default=os.getenv("TC_SSO_LOGIN_URL", ""),
        help="Optional SSO login URL (sets TC_SSO_LOGIN_URL and TC_AUTH=SSO).",
    )
    parser.add_argument(
        "--sso-app-id",
        default=os.getenv("TC_SSO_APP_ID", "Teamcenter"),
        help="SSO application ID (sets TC_SSO_APP_ID).",
    )
    parser.add_argument(
        "--bo-name",
        default=os.getenv("TC_RUNTIME_BO_NAME", "SRB9runtimebo1"),
        help="Runtime BO name to create (defaults to SRB9runtimebo1 or $TC_RUNTIME_BO_NAME).",
    )
    parser.add_argument(
        "--string-prop",
        default=os.getenv("TC_RUNTIME_BO_STRING", "MySampleRuntimeBO"),
        help="Value for srb9StringProp (defaults to MySampleRuntimeBO or $TC_RUNTIME_BO_STRING).",
    )
    parser.add_argument(
        "--int-prop",
        type=int,
        default=int(os.getenv("TC_RUNTIME_BO_INT", "42")),
        help="Value for srb9IntegerProperty (defaults to 42 or $TC_RUNTIME_BO_INT).",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug logging.",
    )
    return parser.parse_args()


def _configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


def main() -> int:
    """
    Main entry point for the Python RuntimeBO sample.

    Orchestrates the following:
    1.  **Configuration**: Parses CLI args for connection details and RBO parameters.
    2.  **Login**: Establishes a session via `ClientX.Session`.
    3.  **Creation**: Calls `RuntimeBOExample.create_runtime_bo` to generate the object.
    4.  **Logout**: Cleans up the session.
    """
    args = _parse_args()
    _configure_logging(args.verbose)

    # Mirror the C# sample CLI knobs for SSO scenarios.
    if args.sso_login_url:
        os.environ["TC_SSO_LOGIN_URL"] = args.sso_login_url
        os.environ.setdefault("TC_AUTH", "SSO")
    if args.sso_app_id:
        os.environ["TC_SSO_APP_ID"] = args.sso_app_id

    session = Session(args.host)
    try:
        user = session.login()
        if user is None:
            logging.error("Login failed or was cancelled.")
            return 1

        connection = Session.getConnection()
        if connection is None:
            logging.error("Session connection unavailable after login.")
            return 2

        RuntimeBOExample(connection).create_runtime_bo(
            bo_name=args.bo_name,
            string_value=args.string_prop,
            int_value=args.int_prop,
        )
        logging.info("RuntimeBO sample complete. Ending.")
        return 0
    finally:
        session.logout()


if __name__ == "__main__":
    raise SystemExit(main())
