"""Shanios Main Window."""

import logging
from typing import override

from gi.repository import Adw, Gtk  # type: ignore

from shani_cassini.state import AppState
from shani_cassini.auth import AuthManager
from shani_cassini.notebook import ShaniosNotebook


logger = logging.getLogger(__name__)


class ShaniosMainWindow(Adw.ApplicationWindow):
    """Main window: sidebar of sections + the selected page."""

    def __init__(self, application: "ShaniosApplication") -> None:
        """Initialize the main window.
        
        Args:
            application: The parent GTK application
        """
        super().__init__(application=application)
        self._app = application
        self._state: AppState | None = (
            application._state if hasattr(application, "_state") else None
        )
        self._auth_manager: AuthManager | None = (
            application._auth_manager if hasattr(application, "_auth_manager") else None
        )

        self._setup_window()
        self._setup_ui()
        logger.info("ShaniosMainWindow initialized")

    def _setup_window(self) -> None:
        """Configure window properties."""
        self.set_title("Shani Cassini")
        self.set_default_size(1100, 760)
        self.set_size_request(360, 480)
        self.set_icon_name("dev.shani.cassini")

        logger.debug("Window properties configured")

    # GTK4 removed Gtk.Window.get_default_width/get_default_height (they
    # were GTK3 aliases of get_default_size). Provide thin accessors so
    # callers/tests can query the configured default size.
    def get_default_width(self) -> int:
        """Return the configured default window width."""
        width, _height = self.get_default_size()
        return width

    def get_default_height(self) -> int:
        """Return the configured default window height."""
        _width, height = self.get_default_size()
        return height

    def _setup_ui(self) -> None:
        """Sidebar navigation; collapses to one pane on a narrow window."""
        self._notebook = ShaniosNotebook(
            state=self._state, auth_manager=self._auth_manager,
            header_end=self._create_status_box(),
        )
        self.set_content(self._notebook)
        bp = Adw.Breakpoint.new(Adw.BreakpointCondition.parse("max-width: 640sp"))
        bp.add_setter(self._notebook.split_view, "collapsed", True)
        self.add_breakpoint(bp)
        logger.info("UI components created")

    def _create_status_box(self) -> Gtk.Box:
        """Create the status indicators box.
        
        Returns:
            Status indicators widget container
        """
        status_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        status_box.set_valign(Gtk.Align.CENTER)
        # update state first (what users act on), then connectivity; the
        # user label only appears once someone is signed in
        self._update_status = Gtk.Label()
        self._update_status.add_css_class("caption")
        status_box.append(self._update_status)
        self._connection_status = Gtk.Label()
        self._connection_status.add_css_class("caption")
        self._connection_status.add_css_class("dim-label")
        status_box.append(self._connection_status)
        self._user_info = Gtk.Label(visible=False)
        self._user_info.add_css_class("caption")
        self._user_info.add_css_class("dim-label")
        status_box.append(self._user_info)

        logger.debug("Status box created")
        return status_box

    def update_status_indicators(self) -> None:
        """Update the status indicators in the header bar."""
        if not self._state:
            return

        # Update connection status
        if hasattr(self._state, "is_connected"):
            status = "● Online" if self._state.is_connected else "○ Offline"
            self._connection_status.set_label(status)

        # Update user info
        if hasattr(self._state, "username") and self._state.username:
            self._user_info.set_label(self._state.username)
            self._user_info.set_visible(True)

        # Update update status
        if hasattr(self._state, "update_available"):
            if self._state.update_available:
                self._update_status.set_label("Update available")
                self._update_status.add_css_class("accent")
            else:
                self._update_status.set_label("Up to date")
                self._update_status.remove_css_class("accent")

        logger.debug("Status indicators updated")