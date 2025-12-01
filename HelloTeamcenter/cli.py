"""CLI entry point for the Python HelloTeamcenter sample."""

from __future__ import annotations

import argparse
import logging
import os

from ClientX.Session import Session

from .data_management import DataManagementExample
from .home_folder import list_home_folder
from .query_service import query_items


def _parse_args() -> argparse.Namespace:
    """Build the CLI argument parser used by the sample entry point."""
    parser = argparse.ArgumentParser(
        description=(
            "Python reproduction of the Siemens HelloTeamcenter ClientX sample. "
            "Lists the home folder, executes the 'Item Name' saved query, and "
            "performs basic create/revise/delete data management operations."
        )
    )
    parser.add_argument(
        "--host",
        default=os.getenv("TC_HOST", "http://localhost:7001/tc"),
        help="Teamcenter SOA host URL. Defaults to %(default)s or $TC_HOST if set.",
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
        "--verbose",
        action="store_true",
        help="Enable debug logging for troubleshooting.",
    )
    return parser.parse_args()


def _configure_logging(verbose: bool) -> None:
    """Configure logging to mirror the standard ClientX samples."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


def main() -> int:
    """
    Main entry point for the HelloTeamcenter Python sample.

    Orchestrates the following:
    1.  **Configuration**: Parses command-line arguments for host and SSO settings.
    2.  **Session**: Initializes the `ClientX.Session` helper.
    3.  **Login**: Authenticates with the Teamcenter server.
    4.  **Examples**: Runs the Home Folder, Query, and Data Management examples.
    5.  **Logout**: Terminates the session.
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
        # Authenticate with Teamcenter using the ClientX infrastructure.
        user = session.login()
        if user is None:
            logging.error("Login failed or was cancelled.")
            return 1

        connection = Session.getConnection()
        if connection is None:
            logging.error("Session connection unavailable after login.")
            return 2

        # Demonstrate the three sample flows in sequence.
        logging.info("Listing home folder contents...")
        list_home_folder(connection, user)

        logging.info("Executing saved query 'Item Name'...")
        query_items(connection)

        logging.info("Running data management create/revise/delete sequence...")
        DataManagementExample(connection).create_revise_and_delete()

        logging.info("HelloTeamcenter sample complete.")
        return 0
    finally:
        session.logout()


if __name__ == "__main__":
    raise SystemExit(main())
