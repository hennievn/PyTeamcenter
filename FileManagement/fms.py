"""CLI entry point for the Python FileManagement sample."""

from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path

from ClientX.Session import Session

from .file_management import FileManagementExample


def _parse_args() -> argparse.Namespace:
    """Build the command-line parser for the FileManagement sample."""
    parser = argparse.ArgumentParser(
        description=(
            "Python reproduction of the Siemens FileManagement ClientX sample. "
            "Uploads example files using the FileManagementUtility."
        )
    )
    parser.add_argument(
        "--host",
        default=os.getenv("TC_HOST", "http://localhost:7001/tc"),
        help="Teamcenter SOA endpoint. Defaults to %(default)s or $TC_HOST when set.",
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
        "--work-dir",
        type=Path,
        default=None,
        help="Optional directory to stage sample files before upload. Defaults to examples/file_management_py/work.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable debug logging for troubleshooting.",
    )
    return parser.parse_args()


def _configure_logging(verbose: bool) -> None:
    """Configure a simple logging formatter that mirrors ClientX defaults."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


def main() -> int:
    args = _parse_args()
    _configure_logging(args.verbose)

    # Keep parity with the ClientX C# sample CLI flags for SSO scenarios.
    if args.sso_login_url:
        os.environ["TC_SSO_LOGIN_URL"] = args.sso_login_url
        os.environ.setdefault("TC_AUTH", "SSO")
    if args.sso_app_id:
        os.environ["TC_SSO_APP_ID"] = args.sso_app_id

    session = Session(args.host)
    try:
        user = session.login()
        if user is None:
            logging.error("Login cancelled or failed; aborting FileManagement demo.")
            return 1

        connection = Session.getConnection()
        if connection is None:
            logging.error("Session connection not available after login.")
            return 1

        work_dir = args.work_dir.resolve() if args.work_dir else None

        with FileManagementExample(connection, working_dir=work_dir) as example:
            example.run_demo()

        logging.info("FileManagement sample completed successfully.")
        return 0
    finally:
        session.logout()


if __name__ == "__main__":
    raise SystemExit(main())
