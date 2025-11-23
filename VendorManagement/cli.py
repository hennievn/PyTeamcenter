"""CLI entry point for the Python VendorManagement sample."""

from __future__ import annotations

import argparse
import logging
import os

from ClientX.Session import Session

from .vendor_management import VendorManagementExample


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Python reproduction of the Siemens VendorManagement ClientX sample. "
            "Provides a simple interactive menu to run the service operations."
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
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


def main() -> int:
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

        example = VendorManagementExample(connection)
        _menu_loop(example)
        logging.info("Exiting VendorManagement sample.")
        return 0
    finally:
        session.logout()


def _menu_loop(example: VendorManagementExample) -> None:
    actions = {
        "1": ("Create or update vendors", example.create_vendors),
        "2": ("Create or update bid packages", example.create_bid_packages),
        "3": ("Create or update line items", example.create_line_items),
        "4": ("Delete vendor roles", example.delete_vendor_roles),
        "5": ("Delete vendors", example.delete_vendors),
        "6": ("Create vendor parts", example.create_parts),
        "7": ("Exit", None),
    }

    choice = ""
    while choice != "7":
        print("\nVendorManagement sample services:")
        for key, (title, _) in actions.items():
            print(f" {key}. {title}")
        choice = input("\nSelect a service (1-7): ").strip()

        action = actions.get(choice)
        if action is None:
            print("Invalid selection. Please choose a valid option.")
            continue
        if choice == "7":
            break

        _, func = action
        try:
            func()
        except Exception as exc:  # pragma: no cover - interactive safeguard
            logging.exception("Service invocation failed: %s", exc)


if __name__ == "__main__":
    raise SystemExit(main())
