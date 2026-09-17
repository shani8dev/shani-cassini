#!/usr/bin/env python3
"""Main entry point for the Shanios GUI Client."""

import sys
import logging
from typing import NoReturn

import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk  # type: ignore

from shani_gui.application import ShaniosApplication


def setup_logging() -> None:
    """Configure application logging."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def main() -> NoReturn:
    """Main application entry point."""
    setup_logging()
    logger = logging.getLogger(__name__)
    logger.info("Starting Shanios GUI Client")

    app = ShaniosApplication()
    exit_status = app.run(sys.argv)
    logger.info(f"Shanios GUI Client exited with status {exit_status}")
    sys.exit(exit_status)


if __name__ == "__main__":
    main()