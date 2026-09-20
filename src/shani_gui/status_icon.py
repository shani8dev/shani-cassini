"""System tray icon implementation for Shanios GUI."""

import logging
import threading
import time
from typing import Optional

from gi.repository import Gio, GLib, Gtk  # type: ignore

try:
    from gi.repository import AppIndicator3  # type: ignore
    HAS_APPINDICATOR = True
except (ImportError, ValueError):
    HAS_APPINDICATOR = False
    AppIndicator3 = None  # type: ignore

from shani_gui.state import AppState
from shani_gui.auth import AuthManager

logger = logging.getLogger(__name__)


class StatusIcon:
    """System tray icon for Shanios GUI."""

    def __init__(
        self,
        state: AppState,
        auth_manager: AuthManager,
        main_window: Optional[Gtk.Window] = None,
        app: Optional[Gtk.Application] = None,
    ) -> None:
        """Initialize the system tray icon.

        Args:
            state: Application state object
            auth_manager: Authentication manager
            main_window: Reference to main window (for show/hide)
            app: owning application, used to quit from the tray menu
        """
        self._state = state
        self._auth_manager = auth_manager
        self._main_window = main_window
        self._app = app
        self._indicator = None
        self._menu = None
        self._update_thread = None
        self._stop_updates = False

        # Initialize the indicator
        self._setup_indicator()

        # Start periodic updates
        self._start_periodic_updates()

        logger.info("StatusIcon initialized")

    def _setup_indicator(self) -> None:
        """Set up the system tray indicator."""
        if not HAS_APPINDICATOR:
            logger.warning("AppIndicator3 not available, system tray icon disabled")
            return

        try:
            # Create the indicator
            self._indicator = AppIndicator3.Indicator.new(
                "shani-gui",
                "system-run",  # Icon name
                AppIndicator3.IndicatorCategory.SYSTEM_SERVICES
            )
            self._indicator.set_status(AppIndicator3.IndicatorStatus.ACTIVE)
            self._indicator.set_attention_icon("indicator-messages-new")  # For notifications

            # Create the menu (Gio.Menu is the GTK4 replacement for
            # Gtk.Menu + Gtk.MenuItem, both removed in GTK4).
            self._menu = Gio.Menu()

            # Add menu items
            self._add_menu_items()

            # Set the menu
            self._indicator.set_menu(self._menu)

            logger.debug("System tray indicator created")
        except Exception as e:
            logger.error(f"Failed to create system tray indicator: {e}")
            self._indicator = None

    def _add_menu_items(self) -> None:
        """Add menu items to the indicator menu.

        Rebuilds the menu from scratch each time — Gio.Menu has no
        get_children()/remove() in GTK4, so clearing means recreating.
        """
        if not self._menu:
            return

        self._menu = Gio.Menu()

        # Show/Hide main window
        if self._main_window:
            self._menu.append("Show Shanios GUI", "win.show")
            self._menu.append("Hide Shanios GUI", "win.hide")
            self._menu.append(None, None)  # separator

        # Quick actions
        self._menu.append("Check for Updates", "app.check-updates")
        self._menu.append("Run Health Check", "app.run-health-check")
        self._menu.append(None, None)  # separator

        # Authentication items
        if self._auth_manager.is_authenticated():
            self._menu.append("Logout", "app.logout")
        else:
            self._menu.append("Login", "app.login")

        self._menu.append(None, None)  # separator

        # About and Quit
        self._menu.append("About Shanios", "app.about")
        self._menu.append("Quit", "app.quit")

        # Wire the action signals on the owning application.
        if self._app is not None:
            for name in (
                "show", "hide", "check-updates", "run-health-check",
                "login", "logout", "about", "quit",
            ):
                action = self._app.lookup_action(f"app.{name}")
                if action is None:
                    continue
                action.connect("activate", self._make_menu_handler(name))

    def _make_menu_handler(self, name: str):
        """Return an activate handler that dispatches a tray menu action."""
        def _handler(_action, _parameter):
            if name == "show" and self._main_window:
                self._main_window.present()
                self._main_window.unminimize()
            elif name == "hide" and self._main_window:
                self._main_window.minimize()
            elif name == "check-updates":
                logger.info("Check for updates requested from system tray")
                if hasattr(self._state, "trigger_update_check"):
                    self._state.trigger_update_check()
                elif self._main_window and hasattr(self._main_window, "check_for_updates"):
                    self._main_window.check_for_updates()
            elif name == "run-health-check":
                logger.info("Health check requested from system tray")
                if self._main_window and hasattr(self._main_window, "switch_to_health_tab"):
                    self._main_window.switch_to_health_tab()
            elif name == "login":
                logger.info("Login requested from system tray")
                if self._main_window and hasattr(self._main_window, "show_login_dialog"):
                    self._main_window.show_login_dialog()
            elif name == "logout":
                logger.info("Logout requested from system tray")
                self._auth_manager.logout()
                GLib.idle_add(self._add_menu_items)
            elif name == "about":
                logger.info("About requested from system tray")
                dialog = Gtk.AboutDialog()
                dialog.set_program_name("Shanios GUI")
                dialog.set_version("1.0.0")
                dialog.set_comments("Native GUI client for Shanios operating system")
                dialog.set_website("https://shani.dev")
                dialog.connect("response", lambda d, r: d.destroy())
                dialog.present()
            elif name == "quit":
                logger.info("Quit requested from system tray")
                self._stop_periodic_updates()
                if self._app is not None:
                    self._app.quit()
        return _handler

    def _update_indicator_state(self) -> None:
        """Update the indicator icon and tooltip based on current state."""
        if not self._indicator:
            return

        try:
            # Determine icon based on state
            icon_name = "system-run"  # Default

            # Check for updates
            if self._state.update_available:
                icon_name = "system-software-update"
            elif self._state.health_status == "critical":
                icon_name = "dialog-error"
            elif self._state.health_status == "warning":
                icon_name = "dialog-warning"
            elif self._state.health_status == "healthy":
                icon_name = "emblem-default"

            self._indicator.set_icon(icon_name)

            # Update tooltip
            tooltip_parts = ["Shanios System"]

            if self._auth_manager.is_authenticated():
                username = self._auth_manager.get_username()
                if username:
                    tooltip_parts.append(f"User: {username}")

            if self._state.update_available:
                tooltip_parts.append("Updates available")

            if self._state.health_status:
                tooltip_parts.append(f"Health: {self._state.health_status}")

            tooltip = " | ".join(tooltip_parts)
            self._indicator.set_label(tooltip, "Shanios")

        except Exception as e:
            logger.error(f"Error updating indicator state: {e}")

    def _update_loop(self) -> None:
        """Update loop for refreshing indicator state."""
        while not self._stop_updates:
            try:
                self._update_indicator_state()
                # Update menu items (authentication state might change)
                GLib.idle_add(self._add_menu_items)
                # Update every 15 seconds
                time.sleep(15)
            except Exception as e:
                logger.error(f"Error in status icon update loop: {e}")
                time.sleep(5)  # Shorter delay on error

    def _start_periodic_updates(self) -> None:
        """Start periodic updates for the indicator."""
        self._stop_updates = False
        self._update_thread = threading.Thread(target=self._update_loop)
        self._update_thread.daemon = True
        self._update_thread.start()

    def _stop_periodic_updates(self) -> None:
        """Stop periodic updates."""
        self._stop_updates = True
        if self._update_thread:
            self._update_thread.join(timeout=1.0)

    def cleanup(self) -> None:
        """Clean up resources."""
        logger.info("Cleaning up StatusIcon")
        self._stop_periodic_updates()
        if self._indicator:
            self._indicator.set_status(AppIndicator3.IndicatorStatus.PASSIVE)