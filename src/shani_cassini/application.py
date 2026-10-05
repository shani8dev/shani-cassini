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

        # A tray icon when the binding is there; no-op and logged when it is not.
        # Kept after the window/auth wiring so a failure here cannot uninitialise
        # what the app needs to run.
        from shani_cassini.tray import make_tray
        from shani_cassini.update_state import POLL_INTERVAL_MS
        self._tray = make_tray(self)
        if self._tray is not None:
            # one tray, one updater: the tray's first row is the deploy check,
            # refreshed on the same 10-minute cadence the detached updater used
            try:
                from gi.repository import GLib

                def _tick():
                    self._tray.refresh()
                    return True  # GLib expects the source to, literally, keep on

                GLib.timeout_add(POLL_INTERVAL_MS, _tick)
                self._tray.refresh()
            except Exception as exc:
                logger.warning("no GLib main loop for the tray refresh: %s", exc)

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
        from shani_cassini.notebook import ALIASES, PAGES, resolve
        if not self._main_window:
            return
        # a retired id is not unknown - it names the page that absorbed it
        if section in ALIASES:
            logger.info("Section %r was merged into %r", section, resolve(section))
            section = resolve(section)
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

        # Reaching a page by id, for a caller that is not this process.
        #
        # The name carries a hyphen and that is FINE, which cost an afternoon to
        # establish the hard way. A GApplication exports its actions on the
        # `org.gtk.Actions` interface, where the action name is the first
        # *argument* of `Activate(s action_name, av parameter, a{sv})` - not part
        # of a D-Bus method name, so the usual `[A-Za-z_][A-Za-z0-9_]*` rule does
        # not apply to it.
        #
        # A version of this comment claimed the opposite ("a D-Bus method name
        # may not contain a hyphen, so this is unreachable") and registered a
        # second `show_section` action to work around it. That was wrong, the
        # duplicate is gone, and `tests/test_show_section_action.py` now holds
        # the measurement instead of the folklore:
        #
        #   gdbus call --session --dest dev.shani.cassini \
        #     --object-path /dev/shani/cassini \
        #     --method org.gtk.Actions.Activate show-section '<"btrfs">' '{}'
        #
        # What made the wrong version so convincing: `gapplication action
        # dev.shani.cassini show-section btrfs` reports `error parsing action
        # parameter: unknown keyword: btrfs`, which reads like it failed to find
        # the action. It found it - it is the *parameter* that tool wants in
        # `key=value` form. The error names the wrong thing.
        show = Gio.SimpleAction.new("show-section", GLib.VariantType.new("s"))
        show.connect("activate", lambda _a, v: self._show_section(v.get_string()))
        self.add_action(show)

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