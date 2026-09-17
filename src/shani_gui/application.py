"""Shanios GTK Application."""

import logging
from typing import override

from gi.repository import Gio, Gtk  # type: ignore

from shani_gui.auth import AuthManager
from shani_gui.state import AppState
from shani_gui.main_window import ShaniosMainWindow


logger = logging.getLogger(__name__)


class ShaniosApplication(Gtk.Application):
    """Main Shanios GUI application."""

    def __init__(self) -> None:
        """Initialize the application."""
        super().__init__(
            application_id="dev.shani8.gui",
            flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE,
        )
        self._state: AppState | None = None
        self._auth_manager: AuthManager | None = None
        self._main_window: ShaniosMainWindow | None = None
        self._status_icon: StatusIcon | None = None

        logger.info("ShaniosApplication initialized")

    @override
    def do_startup(self) -> None:
        """Handle application startup."""
        logger.info("Starting up ShaniosApplication")
        super().do_startup()

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
        
        # Create system tray icon after main window is available
        if not self._status_icon:
            self._status_icon = StatusIcon(
                state=self._state,
                auth_manager=self._auth_manager,
                main_window=self._main_window
            )
        
        logger.info("ShaniosApplication activated")

    @override
    def do_command_line(self, command_line: Gio.ApplicationCommandLine) -> int:
        """Handle command line arguments."""
        logger.info("Processing command line arguments")
        # Handle any command line arguments here
        self.activate()
        return 0

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

        logger.debug("Application actions created")

    def _on_about(self, _action: Gio.SimpleAction, _parameter: object | None) -> None:
        """Show about dialog."""
        logger.info("Showing about dialog")
        from shani_gui.about_dialog import ShaniosAboutDialog

        dialog = ShaniosAboutDialog(self._main_window)
        dialog.present()

    @override
    def do_shutdown(self) -> None:
        """Handle application shutdown."""
        logger.info("Shutting down ShaniosApplication")
        # Clean up status icon
        if self._status_icon:
            self._status_icon.cleanup()
            self._status_icon = None
        super().do_shutdown()