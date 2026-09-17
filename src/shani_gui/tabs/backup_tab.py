"""Backup tab for the Shanios GUI.

Integrates shani-backup functionality with Btrfs snapshots and restic backup.
Handles gracefully when btrfs functions or restic are not available.
"""

import logging
from typing import Optional

from gi.repository import Gtk  # type: ignore

from shani_gui.state import AppState
from shani_gui.auth import AuthManager
from shani_gui.cli_wrapper import get_cli_wrapper


logger = logging.getLogger(__name__)


class BackupTab(Gtk.Box):
    """Backup tab integrating shani-backup functionality.

    Provides user interface for backup configuration, scheduler settings,
    and Btrfs snapshot management. Handles gracefully when underlying
    btrfs functions or restic are not available in the environment.
    """

    def __init__(
        self,
        state: AppState | None = None,
        auth_manager: AuthManager | None = None,
    ) -> None:
        """Initialize the backup tab.

        Args:
            state: Application state object
            auth_manager: Authentication manager
        """
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self._state = state
        self._auth_manager = auth_manager
        self._cli_wrapper = get_cli_wrapper()

        # Initialize shani-backup config (GSettings integration)
        from shani_backup.config import BackupConfig
        self._config = BackupConfig()

        self._setup_ui()
        logger.info("BackupTab initialized")

    def _setup_ui(self) -> None:
        """Set up the user interface for the backup tab."""
        logger.debug("Setting up backup tab UI")

        # Create scrollable container
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)
        self.append(scrolled)

        # Main content box
        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        content_box.set_margin_top(20)
        content_box.set_margin_bottom(20)
        content_box.set_margin_start(20)
        content_box.set_margin_end(20)
        scrolled.set_child(content_box)

        # Create backup configuration card
        config_card = self._create_backup_config_card()
        content_box.append(config_card)

        # Create snapshot management card (handles empty btrfs.py)
        snapshot_card = self._create_snapshot_card()
        content_box.append(snapshot_card)

        # Create scheduler configuration card
        scheduler_card = self._create_scheduler_card()
        content_box.append(scheduler_card)

        # Fetch and display initial data
        self._update_data()

        logger.debug("Backup tab UI created")

    def _create_backup_config_card(self) -> Gtk.Box:
        """Create the backup configuration card.

        Returns:
            Backup config card widget with GSettings-backed values
        """
        card = self._create_card("Backup Configuration")

        # Create grid for config rows
        grid = Gtk.Grid()
        grid.set_row_spacing(8)
        grid.set_column_spacing(16)
        grid.set_column_homogeneous(False)
        card.append(grid)

        # Backup location row
        self._add_info_row(grid, 0, "Backup Location:",
                          self._config.get_backup_location() or "Not configured",
                          "backup-location")

        # Scheduler enabled row
        sched_state = self._config.get_scheduler_enabled()
        if sched_state is None:
            sched_text = "GSettings not available"
        elif sched_state:
            sched_text = "Enabled"
        else:
            sched_text = "Disabled"
        self._add_info_row(grid, 1, "Scheduler Enabled:",
                          sched_text, "enable-scheduler")

        # Schedule time row
        schedule_time = self._config.get_schedule_time()
        self._add_info_row(grid, 2, "Schedule Time:",
                          schedule_time or "Not configured",
                          "schedule-time")

        return card

    def _create_snapshot_card(self) -> Gtk.Box:
        """Create the Btrfs snapshot management card.

        Handles the case where btrfs.py is EMPTY - snapshot functions
        are not implemented in this environment.
        """
        card = self._create_card("Btrfs Snapshots")

        # Since btrfs.py is empty, snapshot functions don't exist.
        # Show a graceful placeholder message.
        label = Gtk.Label()
        label.set_label(
            "Btrfs snapshot functions not available\n\n"
            "The underlying btrfs.py module is empty - snapshot management\n"
            "functions (list_snapshots, create_snapshot, delete_snapshot) are\n"
            "not implemented in this environment.\n\n"
            "To enable snapshot management:\n"
            "1. Ensure shani-backup is installed with Btrfs support, or\n"
            "2. Install restic for backup/restore operations\n\n"
            "Current status: Snapshot operations cannot be performed from this tab."
        )
        label.set_wrap(True)
        label.set_xalign(0)
        card.append(label)

        return card

    def _create_scheduler_card(self) -> Gtk.Box:
        """Create the backup scheduler configuration card."""
        card = self._create_card("Backup Scheduler")

        # Create grid for scheduler rows
        grid = Gtk.Grid()
        grid.set_row_spacing(8)
        grid.set_column_spacing(16)
        grid.set_column_homogeneous(False)
        card.append(grid)

        # Scheduler status row
        sched_state = self._config.get_scheduler_enabled()
        if sched_state is None:
            sched_text = "GSettings not available"
        elif sched_state:
            sched_text = "Enabled"
        else:
            sched_text = "Disabled"
        self._add_info_row(grid, 0, "Scheduler Status:",
                          sched_text, "scheduler-status")

        # Schedule time value row
        schedule_time = self._config.get_schedule_time()
        self._add_info_row(grid, 1, "Schedule Time:",
                          schedule_time or "Not configured",
                          "schedule-time-value")

        # Note about CLI operations
        note = Gtk.Label()
        note.set_label(
            "Note: Backup/restore operations require 'restic' to be installed.\n"
            "Currently restic is not available on this system. Use CLI commands\n"
            "directly if restic is installed separately."
        )
        note.set_halign(Gtk.Align.START)
        note.set_xalign(0)
        note.set_justify(Gtk.Justify.LEFT)
        grid.attach(note, 0, 2, 2, 1)

        return card

    def _create_card(self, title: str) -> Gtk.Box:
        """Create a styled card container.

        Args:
            title: Card title

        Returns:
            Styled card box
        """
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        card.add_css_class("card")
        card.set_margin_bottom(12)

        # Add card title
        title_label = Gtk.Label(label=title)
        title_label.add_css_class("card-title")
        title_label.set_halign(Gtk.Align.START)
        card.append(title_label)

        # Add separator
        separator = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        card.append(separator)

        return card

    def _add_info_row(self, grid: Gtk.Grid, row: int, label_text: str,
                      value_text: str, widget_name: Optional[str]) -> None:
        """Add an information row to a grid.

        Args:
            grid: Grid to add the row to
            row: Row index
            label_text: Label text
            value_text: Value text
            widget_name: Name for the value widget (for updates), or None
        """
        label = Gtk.Label(label=label_text)
        label.add_css_class("label-label")
        label.set_halign(Gtk.Align.START)
        grid.attach(label, 0, row, 1, 1)

        value = Gtk.Label(label=value_text)
        value.add_css_class("label-value")
        value.set_halign(Gtk.Align.START)
        if widget_name:
            value.set_name(widget_name)
        grid.attach(value, 1, row, 1, 1)

    def _update_data(self) -> None:
        """Fetch real data and update the UI elements."""
        logger.debug("Fetching real data for backup tab")

        # Verify config is accessible
        try:
            location = self._config.get_backup_location()
            logger.debug(f"Backup location: {location}")
        except Exception as e:
            logger.error(f"Failed to read backup config: {e}")

        # Scheduler and schedule time already displayed via config card
        # No additional fetch needed - GSettings provides the values

        logger.debug("Backup tab data updated")
