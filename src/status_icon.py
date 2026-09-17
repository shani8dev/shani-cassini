"""System tray icon implementation for Shanios GUI."""

import logging
import threading
import time
from typing import Optional

from gi.repository import Gtk  # type: ignore

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
    ) -> None:
        """Initialize the system tray icon.
        
        Args:
            state: Application state object
            auth_manager: Authentication manager
            main_window: Reference to main window (for show/hide)
        """
        self._state = state
        self._auth_manager = auth_manager
        self._main_window = main_window
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
            
            # Create the menu
            self._menu = Gtk.Menu()
            
            # Add menu items
            self._add_menu_items()
            
            # Set the menu
            self._indicator.set_menu(self._menu)
            
            logger.debug("System tray indicator created")
        except Exception as e:
            logger.error(f"Failed to create system tray indicator: {e}")
            self._indicator = None

    def _add_menu_items(self) -> None:
        """Add menu items to the indicator menu."""
        if not self._menu:
            return
            
        # Clear existing items
        for child in self._menu.get_children():
            self._menu.remove(child)
            
        # Show/Hide main window
        if self._main_window:
            show_item = Gtk.MenuItem(label="Show Shanios GUI")
            show_item.connect("activate", self._on_show_window)
            self._menu.append(show_item)
            
            hide_item = Gtk.MenuItem(label="Hide Shanios GUI")
            hide_item.connect("activate", self._on_hide_window)
            self._menu.append(hide_item)
            
            self._menu.append(Gtk.SeparatorMenuItem())
        
        # Quick actions
        check_update_item = Gtk.MenuItem(label="Check for Updates")
        check_update_item.connect("activate", self._on_check_updates)
        self._menu.append(check_update_item)
        
        health_check_item = Gtk.MenuItem(label="Run Health Check")
        health_check_item.connect("activate", self._on_health_check)
        self._menu.append(health_check_item)
        
        self._menu.append(Gtk.SeparatorMenuItem())
        
        # Authentication items
        if self._auth_manager.is_authenticated():
            logout_item = Gtk.MenuItem(label="Logout")
            logout_item.connect("activate", self._on_logout)
            self._menu.append(logout_item)
        else:
            login_item = Gtk.MenuItem(label="Login")
            login_item.connect("activate", self._on_login)
            self._menu.append(login_item)
            
        self._menu.append(Gtk.SeparatorMenuItem())
        
        # About and Quit
        about_item = Gtk.MenuItem(label="About Shanios")
        about_item.connect("activate", self._on_about)
        self._menu.append(about_item)
        
        quit_item = Gtk.MenuItem(label="Quit")
        quit_item.connect("activate", self._on_quit)
        self._menu.append(quit_item)
        
        # Show all items
        self._menu.show_all()

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
                Gtk.idle_add(self._add_menu_items)
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

    # Menu item callbacks
    def _on_show_window(self, item: Gtk.MenuItem) -> None:
        """Handle show window menu item."""
        if self._main_window:
            self._main_window.present()
            self._main_window.unminimize()

    def _on_hide_window(self, item: Gtk.MenuItem) -> None:
        """Handle hide window menu item."""
        if self._main_window:
            self._main_window.minimize()

    def _on_check_updates(self, item: Gtk.MenuItem) -> None:
        """Handle check for updates menu item."""
        logger.info("Check for updates requested from system tray")
        # Trigger update check through state or main window
        if hasattr(self._state, 'trigger_update_check'):
            self._state.trigger_update_check()
        elif self._main_window and hasattr(self._main_window, 'check_for_updates'):
            self._main_window.check_for_updates()

    def _on_health_check(self, item: Gtk.MenuItem) -> None:
        """Handle health check menu item."""
        logger.info("Health check requested from system tray")
        # Could open health tab or run health check
        if self._main_window and hasattr(self._main_window, 'switch_to_health_tab'):
            self._main_window.switch_to_health_tab()

    def _on_login(self, item: Gtk.MenuItem) -> None:
        """Handle login menu item."""
        logger.info("Login requested from system tray")
        if self._main_window and hasattr(self._main_window, 'show_login_dialog'):
            self._main_window.show_login_dialog()

    def _on_logout(self, item: Gtk.MenuItem) -> None:
        """Handle logout menu item."""
        logger.info("Logout requested from system tray")
        self._auth_manager.logout()
        # Update menu immediately
        Gtk.idle_add(self._add_menu_items)

    def _on_about(self, item: Gtk.MenuItem) -> None:
        """Handle about menu item."""
        logger.info("About requested from system tray")
        # Could show about dialog
        dialog = Gtk.AboutDialog()
        dialog.set_program_name("Shanios GUI")
        dialog.set_version("1.0.0")
        dialog.set_comments("Native GUI client for Shanios operating system")
        dialog.set_website("https://shani.dev")
        dialog.connect("response", lambda d, r: d.destroy())
        dialog.present()

    def _on_quit(self, item: Gtk.MenuItem) -> None:
        """Handle quit menu item."""
        logger.info("Quit requested from system tray")
        self._stop_periodic_updates()
        Gtk.main_quit()

    def cleanup(self) -> None:
        """Clean up resources."""
        logger.info("Cleaning up StatusIcon")
        self._stop_periodic_updates()
        if self._indicator:
            self._indicator.set_status(AppIndicator3.IndicatorStatus.PASSIVE)