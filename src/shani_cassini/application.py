"""Shanios GTK Application."""

import logging
from typing import override

import gi
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, GLib, Gtk  # type: ignore

from shani_cassini.auth import AuthManager
from shani_cassini.state import AppState
from shani_cassini.main_window import ShaniosMainWindow


logger = logging.getLogger(__name__)


class ShaniosApplication(Adw.Application):
    """Main Shani Cassini application."""

    def __init__(self) -> None:
        """Initialize the application."""
        super().__init__(
            application_id="dev.shani.cassini",
            flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE,
        )
        self._state: AppState | None = None
        self._auth_manager: AuthManager | None = None
        self._main_window: ShaniosMainWindow | None = None

        logger.info("ShaniosApplication initialized")

    @override
    def do_startup(self) -> None:
        """Handle application startup."""
        logger.info("Starting up ShaniosApplication")
        # explicit: on PyGObject 3.56 (Arch) super().do_startup() resolves to
        # Gio.Application.startup() and raises TypeError - the app died here
        Adw.Application.do_startup(self)
        # the Shanios desktops ship Saturn Dark: dark unless the user's
        # system explicitly asks for light
        Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.PREFER_DARK)
        from shani_cassini.widgets import apply_amoled_theme
        apply_amoled_theme()
        # the app icon from data/ too: a run from the source tree (or before
        # the icon cache is refreshed) shows it instead of a placeholder
        from pathlib import Path
        from gi.repository import Gdk
        data = Path(__file__).resolve().parents[2] / "data"
        display = Gdk.Display.get_default()
        if data.is_dir() and display is not None:
            Gtk.IconTheme.get_for_display(display).add_search_path(str(data))

        # Initialize core components
        self._state = AppState()
        self._auth_manager = AuthManager()

        # Create actions
        self._create_actions()

        logger.info("ShaniosApplication startup complete")

    @override
    def do_activate(self) -> None:
        """Handle application activation."""
        logger.info("Activating ShaniosApplication")
        if not self._main_window:
            self._main_window = ShaniosMainWindow(self)
            self._main_window.present()

        logger.info("ShaniosApplication activated")

    @override
    def do_command_line(self, command_line: Gio.ApplicationCommandLine) -> int:
        """Handle command line arguments."""
        logger.info("Processing command line arguments")
        # --section=<id> (e.g. updates): open Cassini on that page - for
        # notifications and other apps; also works on a running instance
        section = None
        for arg in command_line.get_arguments()[1:]:
            if arg.startswith("--section="):
                section = arg.split("=", 1)[1]
        self.activate()
        if section:
            self._show_section(section)
        return 0

    def _show_section(self, section: str) -> None:
        from shani_cassini.notebook import PAGES
        if not self._main_window:
            return
        if section not in {p[1] for p in PAGES}:
            logger.warning("Unknown section %r (known: %s)", section, ", ".join(p[1] for p in PAGES))
            return
        self._main_window._notebook.select(section)
        self._main_window._notebook.split_view.set_show_content(True)

    def _create_actions(self) -> None:
        """Create application-wide actions."""
        # Quit action
        quit_action = Gio.SimpleAction.new("quit", None)
        quit_action.connect("activate", lambda *_: self.quit())
        self.add_action(quit_action)
        self.set_accels_for_action("app.quit", ["<Ctrl>Q"])

        # About action
        about_action = Gio.SimpleAction.new("about", None)
        about_action.connect("activate", self._on_about)
        self.add_action(about_action)

        # app.show-section('<id>'): same as --section, over D-Bus too
        # (gapplication action dev.shani.cassini show-section "'health'")
        show = Gio.SimpleAction.new("show-section", GLib.VariantType.new("s"))
        show.connect("activate", lambda _a, v: self._show_section(v.get_string()))
        self.add_action(show)

        logger.debug("Application actions created")

    def get_action(self, name: str) -> Gio.SimpleAction | None:
        """Look up a registered action by name.

        Gtk.Application does not expose ``get_action`` (a GTK3 API); the
        GTK4 equivalent is ``lookup_action`` on the Gio.ActionMap mixin.
        """
        return self.lookup_action(name)

    def _on_about(self, _action: Gio.SimpleAction, _parameter: object | None) -> None:
        """Show the About dialog."""
        from shani_cassini.about_dialog import about_dialog
        about_dialog().present(self._main_window)

    @override
    def do_shutdown(self) -> None:
        """Handle application shutdown."""
        logger.info("Shutting down ShaniosApplication")
        Adw.Application.do_shutdown(self)