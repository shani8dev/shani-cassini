#!/usr/bin/env python3
"""Main entry point for the Shani Cassini."""

import sys
import logging
from typing import NoReturn


def setup_logging() -> None:
    """Configure application logging."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def main() -> NoReturn:
    """Main application entry point."""
    if "--agent" in sys.argv[1:]:
        # the background check (shani-cassini-agent.timer): no window
        from shani_cassini.agent import main as agent_main
        sys.exit(agent_main())
    setup_logging()
    logger = logging.getLogger(__name__)
    logger.info("Starting Shani Cassini")

    import gi
    gi.require_version("Gtk", "4.0")
    gi.require_version("Adw", "1")
    from gi.repository import Gtk  # type: ignore
    from shani_cassini.application import ShaniosApplication

    app = ShaniosApplication()
    exit_status = app.run(sys.argv)
    logger.info(f"Shani Cassini exited with status {exit_status}")
    sys.exit(exit_status)


if __name__ == "__main__":
    main()