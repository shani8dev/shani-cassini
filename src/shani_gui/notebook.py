"""Shanios Notebook (Tabbed Interface)."""

import logging
from typing import override

from gi.repository import Gtk  # type: ignore

from shani_gui.state import AppState
from shani_gui.auth import AuthManager
from shani_gui.tabs.overview import OverviewTab
from shani_gui.tabs.system import SystemTab
from shani_gui.tabs.settings import SettingsTab
from shani_gui.tabs.updates import UpdatesTab
from shani_gui.tabs.services import ServicesTab
from shani_gui.tabs.fleet import FleetTab
from shani_gui.tabs.health import HealthTab
from shani_gui.tabs.deploy import DeployTab
from shani_gui.tabs.skills import SkillsTab
from shani_gui.tabs.backup import BackupTab
from shani_gui.tabs.chronoa import ChronoaTab


logger = logging.getLogger(__name__)


class ShaniosNotebook(Gtk.Notebook):
    """Tabbed interface for the Shanios GUI."""

    def __init__(
        self,
        state: AppState | None = None,
        auth_manager: AuthManager | None = None,
    ) -> None:
        """Initialize the notebook.
        
        Args:
            state: Application state object
            auth_manager: Authentication manager
        """
        super().__init__()
        self._state = state
        self._auth_manager = auth_manager

        self._setup_notebook()
        self._create_tabs()
        logger.info("ShaniosNotebook initialized")

    def _setup_notebook(self) -> None:
        """Configure notebook properties."""
        self.set_tab_pos(Gtk.PositionType.TOP)
        self.set_show_tabs(True)
        self.set_show_border(True)
        self.set_scrollable(True)
        # Enable swipe gestures on touchscreens
        self.set_enable_popup(True)

        logger.debug("Notebook properties configured")

    def _create_tabs(self) -> None:
        """Create all application tabs."""
        logger.debug("Creating application tabs")

        # Define tab configurations: (TabClass, tab_label, icon_name, tooltip)
        tab_configs = [
            (OverviewTab, "Overview", "view-overview", "System overview and status"),
            (SystemTab, "System", "desktop", "Detailed system information"),
            (SettingsTab, "Settings", "preferences-system", "System settings configuration"),
            (UpdatesTab, "Updates", "system-software-update", "System updates and channels"),
            (ServicesTab, "Services", "applications-system", "System services management"),
            (FleetTab, "Fleet", "network-server", "Fleet management and enrollment"),
            (HealthTab, "Health", "emergency", "System health diagnostics"),
            (DeployTab, "Deploy", "system-run", "System deployment and rollback"),
            (SkillsTab, "Skills", "applications-system", "Pulsar OS Sayri skills and plugin management"),
            (BackupTab, "Backup", "backup", "Backup management and restoration"),
            (ChronoaTab, "Chronoa", "audio-input-microphone", "Chronoa AI assistant configuration"),
        ]

        for tab_class, label, icon_name, tooltip in tab_configs:
            try:
                # Create tab instance
                tab_instance = tab_class(state=self._state, auth_manager=self._auth_manager)
                
                # Create tab label with icon
                tab_label_box = self._create_tab_label(label, icon_name)
                
                # Append tab to notebook
                self.append_page(tab_instance, tab_label_box)
                self.set_tab_tooltip(self.get_nth_page(self.get_n_pages() - 1), tooltip)
                
                logger.debug(f"Created tab: {label}")
            except Exception as e:
                logger.error(f"Failed to create tab {label}: {e}")
                # Create error tab as fallback
                error_label = Gtk.Label(label=f"Error loading {label} tab")
                error_tab = Gtk.Box()
                error_tab.append(error_label)
                tab_label_box = self._create_tab_label(label, "error")
                self.append_page(error_tab, tab_label_box)
                self.set_tab_tooltip(self.get_nth_page(self.get_n_pages() - 1), 
                                   f"Failed to load {label} tab")

        logger.info(f"Created {self.get_n_pages()} tabs")

    def _create_tab_label(self, text: str, icon_name: str) -> Gtk.Box:
        """Create a tab label with optional icon.
        
        Args:
            text: Tab label text
            icon_name: Icon name for the tab
            
        Returns:
            Box containing icon and label
        """
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=4)
        box.set_valign(Gtk.Align.CENTER)
        box.set_halign(Gtk.Align.CENTER)

        # Add icon if provided
        if icon_name and icon_name != "":
            try:
                icon = Gtk.Image.new_from_icon_name(icon_name)
                icon.set_pixel_size(16)
                box.append(icon)
            except Exception as e:
                logger.warning(f"Failed to load icon '{icon_name}': {e}")

        # Add text label
        label = Gtk.Label(label=text)
        box.append(label)

        return box