"""Shanios Main Window."""

import logging
from typing import override

from gi.repository import Gdk, Gtk  # type: ignore

from shani_gui.state import AppState
from shani_gui.auth import AuthManager
from shani_gui.notebook import ShaniosNotebook


logger = logging.getLogger(__name__)


class ShaniosMainWindow(Gtk.ApplicationWindow):
    """Main application window with tabbed interface."""

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
        self.set_title("Shanios System Manager")
        self.set_default_size(1024, 768)
        self.set_size_request(800, 600)

        # Set window icon (placeholder for now)
        # self.set_icon_from_file("path/to/icon.png")

        # Apply CSS styling
        self._apply_css()

        logger.debug("Window properties configured")

    def _apply_css(self) -> None:
        """Apply CSS styling to the window."""
        css_provider = Gtk.CssProvider()
        try:
            # Load CSS from resources or file
            css_data = b"""
                window {
                    background-color: @theme_bg_color;
                }
                .header-bar {
                    background-color: @theme_bg_color;
                }
                .notebook tab {
                    padding: 8px 12px;
                }
                .notebook tab:disabled {
                    color: alpha(@fg_color, 0.5);
                }
            """
            css_provider.load_from_data(css_data)
            Gtk.StyleContext.add_provider_for_display(
                Gdk.Display.get_default(),
                css_provider,
                Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
            )
        except Exception as e:
            logger.warning(f"Failed to load CSS: {e}")

        logger.debug("CSS styling applied")

    def _setup_ui(self) -> None:
        """Set up the user interface."""
        logger.debug("Setting up UI components")

        # Create main box
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.set_child(main_box)

        # Create header bar
        header_bar = self._create_header_bar()
        main_box.append(header_bar)

        # Create notebook (tabbed interface)
        self._notebook = ShaniosNotebook(
            state=self._state, auth_manager=self._auth_manager
        )
        main_box.append(self._notebook)

        logger.info("UI components created")

    def _create_header_bar(self) -> Gtk.HeaderBar:
        """Create the application header bar.
        
        Returns:
            Configured header bar widget
        """
        header_bar = Gtk.HeaderBar()
        header_bar.set_show_title_buttons(True)
        header_bar.set_title_widget(self._create_title_widget())

        # Add system status indicators
        status_box = self._create_status_box()
        header_bar.pack_end(status_box)

        logger.debug("Header bar created")
        return header_bar

    def _create_title_widget(self) -> Gtk.Widget:
        """Create the title widget for the header bar.
        
        Returns:
            Title widget container
        """
        title_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        title_box.set_halign(Gtk.Align.CENTER)

        # Application name
        title_label = Gtk.Label(label="Shanios System Manager")
        title_label.add_css_class("title-1")
        title_label.set_halign(Gtk.Align.START)
        title_box.append(title_label)

        # Application icon/logo (placeholder)
        # icon = Gtk.Picture.new_for_filename("path/to/logo.png")
        # icon.set_size_request(24, 24)
        # title_box.prepend(icon)

        return title_box

    def _create_status_box(self) -> Gtk.Box:
        """Create the status indicators box.
        
        Returns:
            Status indicators widget container
        """
        status_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        status_box.set_valign(Gtk.Align.CENTER)
        status_box.set_hexpand(True)
        status_box.set_halign(Gtk.Align.END)

        # Connection status
        self._connection_status = Gtk.Label()
        self._connection_status.add_css_class("dim-label")
        status_box.append(self._connection_status)

        # Separator
        separator = Gtk.Label(label="|")
        separator.add_css_class("dim-label")
        status_box.append(separator)

        # User info
        self._user_info = Gtk.Label()
        self._user_info.add_css_class("dim-label")
        status_box.append(self._user_info)

        # Update status
        self._update_status = Gtk.Label()
        self._update_status.add_css_class("dim-label")
        status_box.append(self._update_status)

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
            self._user_info.set_label(f"User: {self._state.username}")

        # Update update status
        if hasattr(self._state, "update_available"):
            update_text = "● Update Available" if self._state.update_available else "○ Up to Date"
            self._update_status.set_label(update_text)

        logger.debug("Status indicators updated")