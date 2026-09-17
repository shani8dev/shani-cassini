"""Backup tab for the Shanios GUI — integrates shani-backup."""

import logging
import subprocess
import threading
import time
import os
from typing import override

from gi.repository import Gtk  # type: ignore

from shani_gui.state import AppState
from shani_gui.auth import AuthManager
from shani_gui.cli_wrapper import get_cli_wrapper


logger = logging.getLogger(__name__)


class BackupTab(Gtk.Box):
    """Backup tab showing Btrfs snapshots, backup status, and scheduler."""

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
        self._update_thread = None
        self._stop_updates = False

        self._setup_ui()
        logger.info("BackupTab initialized")
        
        self._start_periodic_updates()

    def _setup_ui(self) -> None:
        """Set up the user interface for the backup tab."""
        logger.debug("Setting up backup tab UI")

        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)
        self.append(scrolled)

        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        content_box.set_margin_top(20)
        content_box.set_margin_bottom(20)
        content_box.set_margin_start(20)
        content_box.set_margin_end(20)
        scrolled.set_child(content_box)

        status_card = self._create_status_card()
        content_box.append(status_card)

        snapshot_card = self._create_snapshot_card()
        content_box.append(snapshot_card)

        scheduler_card = self._create_scheduler_card()
        content_box.append(scheduler_card)

        logger.debug("Backup tab UI created")

    def _create_status_card(self) -> Gtk.Box:
        """Create the backup status card.
        
        Returns:
            Backup status card widget
        """
        card = self._create_card("Backup Status")

        grid = Gtk.Grid()
        grid.set_row_spacing(8)
        grid.set_column_spacing(16)
        grid.set_column_homogeneous(False)
        card.append(grid)

        self._add_info_row(grid, 0, "Backup Location:", "Checking...", "backup-location")
        self._add_info_row(grid, 1, "Scheduler:", "Checking...", "backup-scheduler")
        self._add_info_row(grid, 2, "Last Backup:", "Never", "backup-last")
        self._add_info_row(grid, 3, "Tool Status:", "Checking...", "backup-tool-status")

        return card

    def _create_snapshot_card(self) -> Gtk.Box:
        """Create the snapshot management card.
        
        Returns:
            Snapshot card widget
        """
        card = self._create_card("Btrfs Snapshots")

        grid = Gtk.Grid()
        grid.set_row_spacing(8)
        grid.set_column_spacing(16)
        grid.set_column_homogeneous(False)
        card.append(grid)

        self._add_info_row(grid, 0, "Snapshots Found:", "Checking...", "backup-snapshots-count")
        self._add_info_row(grid, 1, "Current Snapshot:", "None", "backup-current-snapshot")

        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        button_box.set_halign(Gtk.Align.END)
        refresh_btn = Gtk.Button(label="Refresh Snapshots")
        refresh_btn.connect("clicked", self._on_refresh_snapshots_clicked)
        button_box.append(refresh_btn)
        create_btn = Gtk.Button(label="Create Snapshot")
        create_btn.add_css_class("suggested-action")
        create_btn.connect("clicked", self._on_create_snapshot_clicked)
        button_box.append(create_btn)
        card.append(button_box)

        return card

    def _create_scheduler_card(self) -> Gtk.Box:
        """Create the scheduler configuration card.
        
        Returns:
            Scheduler card widget
        """
        card = self._create_card("Backup Scheduler")

        grid = Gtk.Grid()
        grid.set_row_spacing(8)
        grid.set_column_spacing(16)
        grid.set_column_homogeneous(False)
        card.append(grid)

        self._add_info_row(grid, 0, "Enabled:", "Checking...", "backup-scheduler-enabled")
        self._add_info_row(grid, 1, "Schedule Time:", "Checking...", "backup-schedule-time")

        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        button_box.set_halign(Gtk.Align.END)
        toggle_btn = Gtk.Button(label="Toggle Scheduler")
        toggle_btn.connect("clicked", self._on_toggle_scheduler_clicked)
        button_box.append(toggle_btn)
        card.append(button_box)

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

        title_label = Gtk.Label(label=title)
        title_label.add_css_class("card-title")
        title_label.set_halign(Gtk.Align.START)
        card.append(title_label)

        separator = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        card.append(separator)

        return card

    def _add_info_row(self, grid: Gtk.Grid, row: int, label_text: str, 
                      value_text: str, widget_name: str) -> None:
        """Add an information row to a grid.
        
        Args:
            grid: Grid to add the row to
            row: Row index
            label_text: Label text
            value_text: Value text
            widget_name: Name for the value widget (for updates)
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

    def _start_periodic_updates(self) -> None:
        """Start periodic updates for backup status."""
        self._stop_updates = False
        self._update_thread = threading.Thread(target=self._update_loop)
        self._update_thread.daemon = True
        self._update_thread.start()

    def _stop_periodic_updates(self) -> None:
        """Stop periodic updates."""
        self._stop_updates = True
        if self._update_thread:
            self._update_thread.join(timeout=1.0)

    def _update_loop(self) -> None:
        """Update loop for fetching backup status."""
        while not self._stop_updates:
            try:
                self._update_backup_status()
                time.sleep(30)
            except Exception as e:
                logger.error(f"Error in backup update loop: {e}")
                time.sleep(5)

    def _update_backup_status(self) -> None:
        """Update backup status information."""
        try:
            self._update_backup_location()
            self._update_scheduler_status()
            self._update_snapshot_info()
            self._update_tool_status()
        except Exception as e:
            logger.error(f"Error updating backup status: {e}")

    def _update_backup_location(self) -> None:
        """Update backup location display."""
        try:
            result = self._cli_wrapper.backup_snapshot_list()
            if result and isinstance(result, dict):
                location = result.get("backup_location", "/mnt/backups")
            else:
                location = "Not configured"
            Gtk.idle_add(self._update_label_text, "backup-location", location)
        except Exception:
            Gtk.idle_add(self._update_label_text, "backup-location", "Unavailable")

    def _update_scheduler_status(self) -> None:
        """Update scheduler status display."""
        try:
            result = self._cli_wrapper.backup_scheduler_status()
            if result and isinstance(result, dict):
                enabled = result.get("scheduler_enabled", False)
                schedule_time = result.get("schedule_time", "02:00")
                status_text = "Enabled" if enabled else "Disabled"
            else:
                status_text = "Unavailable"
                schedule_time = "N/A"
            Gtk.idle_add(self._update_label_text, "backup-scheduler-enabled", status_text)
            Gtk.idle_add(self._update_label_text, "backup-schedule-time", schedule_time)
        except Exception:
            Gtk.idle_add(self._update_label_text, "backup-scheduler-enabled", "Unavailable")
            Gtk.idle_add(self._update_label_text, "backup-schedule-time", "Unavailable")

    def _update_snapshot_info(self) -> None:
        """Update snapshot information display."""
        try:
            result = self._cli_wrapper.backup_snapshot_list()
            if result and isinstance(result, dict):
                snapshots = result.get("snapshots", [])
                count = len(snapshots)
                latest = snapshots[-1] if snapshots else "None"
            else:
                count = 0
                latest = "None"
            Gtk.idle_add(self._update_label_text, "backup-snapshots-count", f"{count}")
            Gtk.idle_add(self._update_label_text, "backup-current-snapshot", latest[:50])
        except Exception:
            Gtk.idle_add(self._update_label_text, "backup-snapshots-count", "N/A")
            Gtk.idle_add(self._update_label_text, "backup-current-snapshot", "N/A")

    def _update_tool_status(self) -> None:
        """Update tool status display."""
        try:
            result = self._cli_wrapper.backup_snapshot_list()
            if result is None:
                status_text = "Not installed"
            elif isinstance(result, dict) and "raw_output" in result:
                status_text = "Available"
            else:
                status_text = "Available"
            Gtk.idle_add(self._update_label_text, "backup-tool-status", status_text)
        except Exception:
            Gtk.idle_add(self._update_label_text, "backup-tool-status", "Error")

    def _update_label_text(self, widget_name: str, text: str) -> None:
        """Update a label widget by its name.
        
        Args:
            widget_name: The name of the widget to update
            text: The new text for the widget
        """
        def find_widget(widget):
            if widget.get_name() == widget_name:
                return widget
            if isinstance(widget, Gtk.Container):
                for child in widget.get_children():
                    found = find_widget(child)
                    if found:
                        return found
            return None
        
        widget = find_widget(self.get_root())
        if widget and isinstance(widget, Gtk.Label):
            widget.set_label(text)
        else:
            logger.debug(f"Widget not found or not a label: {widget_name}")

    # Event handlers
    def _on_refresh_snapshots_clicked(self, button: Gtk.Button) -> None:
        """Handle refresh snapshots button click."""
        logger.info("Refresh snapshots button clicked")
        thread = threading.Thread(target=self._refresh_snapshots_thread)
        thread.daemon = True
        thread.start()

    def _refresh_snapshots_thread(self) -> None:
        """Refresh snapshots in a background thread."""
        try:
            result = self._cli_wrapper.backup_snapshot_list()
            if result and isinstance(result, dict):
                snapshots = result.get("snapshots", [])
                count = len(snapshots)
                Gtk.idle_add(self._update_label_text, "backup-snapshots-count", f"{count}")
                latest = snapshots[-1] if snapshots else "None"
                Gtk.idle_add(self._update_label_text, "backup-current-snapshot", latest[:50])
        except Exception as e:
            logger.error(f"Error refreshing snapshots: {e}")

    def _on_create_snapshot_clicked(self, button: Gtk.Button) -> None:
        """Handle create snapshot button click."""
        logger.info("Create snapshot button clicked")
        dialog = Gtk.MessageDialog(
            transient_for=self.get_root(),
            modal=True,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.OK,
            text="Create Snapshot",
        )
        dialog.format_secondary_text(
            "Btrfs snapshot creation requires shani-backup to be installed.\n"
            "The snapshot functionality is not yet available."
        )
        dialog.connect("response", lambda d, r: d.destroy())
        dialog.present()

    def _on_toggle_scheduler_clicked(self, button: Gtk.Button) -> None:
        """Handle toggle scheduler button click."""
        logger.info("Toggle scheduler button clicked")
        dialog = Gtk.MessageDialog(
            transient_for=self.get_root(),
            modal=True,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.OK,
            text="Scheduler Control",
        )
        dialog.format_secondary_text(
            "Backup scheduler control requires shani-backup to be installed.\n"
            "The scheduler functionality is not yet available."
        )
        dialog.connect("response", lambda d, r: d.destroy())
        dialog.present()
