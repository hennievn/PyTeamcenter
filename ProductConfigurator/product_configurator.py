"""CLI entry point for the Python ProductConfigurator sample."""

from __future__ import annotations

import argparse
import logging
import os

from ClientX.Session import Session

from . import configurator_management as cfg_util


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Python reproduction of the Siemens ProductConfigurator VB sample. "
            "Finds a product item, resolves its configurator perspective, "
            "and calls ConfiguratorManagementService.GetVariability."
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
        "item_id",
        nargs="?",
        default=os.getenv("TC_ITEM_ID", "030989"),
        help="Item ID of the product to inspect (defaults to 030989 or $TC_ITEM_ID).",
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
    """
    Main entry point for the Python ProductConfigurator sample.

    Process:
    1.  **Login**: Authenticates with Teamcenter.
    2.  **Initialize**: Sets up strong types and policies via `cfg_util.initialize`.
    3.  **Find Item**: Locates the product item by ID (`cfg_util.find_item`).
    4.  **Get Perspective**: Retrieves the configurator perspective (`cfg_util.get_config_perspective`).
    5.  **Get Variability**: Calls `cfg_util.get_variability` to fetch configuration data.
    6.  **Logout**: Terminates the session.
    """
    args = _parse_args()
    _configure_logging(args.verbose)

    # Mirror the VB sample CLI knobs for SSO scenarios.
    if args.sso_login_url:
        os.environ["TC_SSO_LOGIN_URL"] = args.sso_login_url
        os.environ.setdefault("TC_AUTH", "SSO")
    if args.sso_app_id:
        os.environ["TC_SSO_APP_ID"] = args.sso_app_id

    session = Session(args.host)
    try:
        user = session.login()
        if user is None:
            logging.error("Login failed or cancelled; cannot continue.")
            return 1

        cfg_util.initialize(session)

        product_item = cfg_util.find_item(session, args.item_id)
        if product_item is None:
            logging.error("Item %s not found.", args.item_id)
            return 2

        perspective = cfg_util.get_config_perspective(product_item, session)
        if perspective is None:
            logging.error(
                "Product item %s does not have an associated configurator perspective.", args.item_id
            )
            return 3

        response = cfg_util.get_variability(perspective, session)
        if response is None:
            logging.error("GetVariability returned no data.")
            return 4

        logging.info(
            "GetVariability returned ServiceData with %s partial errors.",
            cfg_util.partial_error_count(getattr(response, "ServiceData", None)),
        )
        logging.info("Sample complete. Ending.")
        return 0
    finally:
        session.logout()


if __name__ == "__main__":
    raise SystemExit(main())
