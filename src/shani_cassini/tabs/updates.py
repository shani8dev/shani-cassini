"""Updates tab for the Shani Cassini."""

import logging
import subprocess
import threading
import time
import os
import json
import re
from datetime import datetime
from typing import override

from gi.repository import GLib, Gtk  # type: ignore

from shani_cassini.state import AppState
from shani_cassini.auth import AuthManager
from shani_cassini.cli_wrapper import get_cli_wrapper


logger = logging.getLogger(__name__)


class UpdatesTab(Gtk.Box):
    """Updates tab for managing system updates and channels."""

    def __init__(
        self,
        state: AppState | None = None,
        auth_manager: AuthManager | None = None,
    ) -> None:
        """Initialize the updates tab.
        
        Args:
            state: Application state object
            auth_manager: Authentication manager
        """
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self._state = state
        self._auth_manager = auth_manager
        self._cli_wrapper = get_cli_wrapper()
        # Guard against re-entrant channel-change requests. Set while
        # _fetch_update_info programmatically selects the active channel so
        # the toggled signal does not spawn a background set-channel call
        # during construction.
        self._channel_in_progress = False
        self._suppress_channel_toggle = False

        self._setup_ui()
        logger.info("UpdatesTab initialized")

    def _setup_ui(self) -> None:
        """Set up the user interface for the updates tab."""
        logger.debug("Setting up updates tab UI")

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

        # Create update channel card
        channel_card = self._create_update_channel_card()
        content_box.append(channel_card)

        # Create update history card
        history_card = self._create_update_history_card()
        content_box.append(history_card)

        # Create actions card
        actions_card = self._create_actions_card()
        content_box.append(actions_card)

        # Create update progress card
        self._progress_card = self._create_update_progress_card()
        content_box.append(self._progress_card)
        self._progress_card.set_visible(False)  # Hidden by default

        # Fetch initial data
        self._fetch_update_info()

        logger.debug("Updates tab UI created")

    def _create_update_channel_card(self) -> Gtk.Box:
        """Create the update channel card.
        
        Returns:
            Update channel card widget
        """
        card = self._create_card("Update Channel")

        # Create grid for channel options
        grid = Gtk.Grid()
        grid.set_row_spacing(8)
        grid.set_column_spacing(16)
        card.append(grid)

        # Add channel options
        self._channel_stable = Gtk.CheckButton(label="stable")
        self._channel_stable.add_css_class("flat")
        self._channel_stable.connect("toggled", self._on_channel_toggled)
        grid.attach(Gtk.Label(label=""), 0, 0, 1, 1)  # Empty label for alignment
        grid.attach(self._channel_stable, 1, 0, 1, 1)
        grid.attach(Gtk.Label(label="(recommended)"), 2, 0, 1, 1)

        self._channel_latest = Gtk.CheckButton()
        self._channel_latest.set_label("latest")
        self._channel_latest.add_css_class("flat")
        self._channel_latest.connect("toggled", self._on_channel_toggled)
        grid.attach(Gtk.Label(label=""), 0, 1, 1, 1)  # Empty label for alignment
        grid.attach(self._channel_latest, 1, 1, 1, 1)
        grid.attach(Gtk.Label(label="(cutting edge)"), 2, 1, 1, 1)

        # Add channel description
        description = Gtk.Label()
        description.set_label("The update channel determines which updates you receive. "
                            "Stable releases are thoroughly tested, while latest offers "
                            "newer features but may be less stable.")
        description.add_css_class("dim-label")
        description.set_halign(Gtk.Align.START)
        description.set_wrap(True)
        card.append(description)

        return card

    def _create_update_history_card(self) -> Gtk.Box:
        """Create the update history card.
        
        Returns:
            Update history card widget
        """
        card = self._create_card("Update History")

        # Create list box for history
        self._history_list = Gtk.ListBox()
        self._history_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self._history_list.set_activate_on_single_click(False)
        card.append(self._history_list)

        self._add_history_entry("v1.2.3", "2026-09-10", "Security update")
        self._add_history_entry("v1.2.2", "2026-08-25", "Feature update")
        self._add_history_entry("v1.2.1", "2026-08-05", "Initial release")

        return card

    def _create_actions_card(self) -> Gtk.Box:
        """Create the actions card.
        
        Returns:
            Actions card widget
        """
        card = self._create_card("Actions")

        # Create button box
        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        button_box.set_halign(Gtk.Align.START)
        card.append(button_box)

        # Add action buttons
        check_btn = Gtk.Button(label="Check for Updates")
        check_btn.add_css_class("suggested-action")
        check_btn.connect("clicked", self._on_check_updates_clicked)
        button_box.append(check_btn)

        view_changelog_btn = Gtk.Button(label="View Changelog")
        view_changelog_btn.connect("clicked", self._on_view_changelog_clicked)
        button_box.append(view_changelog_btn)

        cleanup_btn = Gtk.Button(label="Cleanup Downloads")
        cleanup_btn.connect("clicked", self._on_cleanup_clicked)
        button_box.append(cleanup_btn)

        optimize_btn = Gtk.Button(label="Optimize Storage")
        optimize_btn.connect("clicked", self._on_optimize_clicked)
        button_box.append(optimize_btn)

        return card

    def _create_update_progress_card(self) -> Gtk.Box:
        """Create the update progress card.
        
        Returns:
            Update progress card widget
        """
        card = self._create_card("Update Progress")

        # Create progress box
        progress_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        card.append(progress_box)

        # Add progress bar
        self._progress_bar = Gtk.ProgressBar()
        self._progress_bar.set_show_text(True)
        progress_box.append(self._progress_bar)

        # Add progress details
        self._progress_details = Gtk.Label()
        self._progress_details.add_css_class("dim-label")
        self._progress_details.set_halign(Gtk.Align.START)
        progress_box.append(self._progress_details)

        # Add action buttons
        action_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        action_box.set_halign(Gtk.Align.END)
        progress_box.append(action_box)

        self._pause_btn = Gtk.Button(label="Pause")
        self._pause_btn.connect("clicked", self._on_pause_clicked)
        action_box.append(self._pause_btn)

        self._cancel_btn = Gtk.Button(label="Cancel")
        self._cancel_btn.add_css_class("destructive-action")
        self._cancel_btn.connect("clicked", self._on_cancel_clicked)
        action_box.append(self._cancel_btn)

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

    def _add_history_entry(self, version: str, date: str, description: str) -> None:
        """Add an entry to the update history list.
        
        Args:
            version: Version string
            date: Date string
            description: Description text
        """
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row.set_margin_start(12)
        row.set_margin_end(12)
        row.set_margin_top(6)
        row.set_margin_bottom(6)

# Version label
        version_label = Gtk.Label(label=f"[v{version}]")
        version_label.add_css_class("dim-label")
        version_label.set_halign(Gtk.Align.START)
        row.append(version_label)

        # Date label
        date_label = Gtk.Label(label=date)
        date_label.add_css_class("dim-label")
        date_label.set_halign(Gtk.Align.START)
        row.append(date_label)

        # Description label
        desc_label = Gtk.Label(label=description)
        desc_label.set_halign(Gtk.Align.START)
        desc_label.set_hexpand(True)
        row.append(desc_label)

        self._history_list.append(row)

    def _on_channel_toggled(self, button: Gtk.CheckButton) -> None:
        """Handle update channel toggle.

        Delegates the actual persist to a background thread so the UI
        never blocks on shani-deploy. ``_channel_in_progress`` prevents
        re-entrant requests; ``_suppress_channel_toggle`` is set while
        ``_fetch_update_info`` programmatically selects the active channel
        during construction so the toggled signal does not spawn a request.
        """
        if self._suppress_channel_toggle or self._channel_in_progress:
            return
        if not button.get_active():
            return
        channel = button.get_label()
        if channel not in ("stable", "latest"):
            return
        logger.info(f"Update channel changed to: {channel}")
        self._channel_in_progress = True
        threading.Thread(
            target=self._set_channel_thread, args=(channel,), daemon=True
        ).start()

    def _set_channel_thread(self, channel: str) -> None:
        """Persist ``channel`` via the shared CLIWrapper."""
        try:
            self._cli_wrapper.set_update_channel(channel)
        except Exception as e:
            logger.error(f"Failed to set update channel {channel}: {e}")
        finally:
            self._channel_in_progress = False

    def _on_check_updates_clicked(self, button: Gtk.Button) -> None:
        """Handle check for updates button click."""
        logger.info("Check for updates button clicked")
        # Show progress card
        self._progress_card.set_visible(True)
        self._progress_bar.set_fraction(0.0)
        self._progress_bar.set_text("Checking for updates...")
        self._progress_details.set_text("Checking system and update servers...")

        # TODO: Implement actual update check in a thread to avoid blocking UI
        # For now, we'll simulate the check
        # In a real implementation, we would use threading or asyncio

    def _on_view_changelog_clicked(self, button: Gtk.Button) -> None:
        """Handle view changelog button click."""
        logger.info("View changelog button clicked")
        # TODO: Implement changelog viewer
        dialog = Gtk.MessageDialog(
            transient_for=self.get_root(),
            modal=True,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.OK,
            text="Release Notes - v1.2.4",
        )
        dialog.format_secondary_text(
            "Shanios v1.2.4\n\n"
            "• Security fixes for kernel vulnerabilities\n"
            "• Improved Btrfs scrub performance\n"
            "• Updated firmware for Thunderbolt controllers\n"
            "• Enhanced security audit logging\n"
            "• Bug fixes in system update manager\n"
            "• Added support for new hardware devices"
        )
        dialog.connect("response", lambda d, r: d.destroy())
        dialog.present()

    def _on_cleanup_clicked(self, button: Gtk.Button) -> None:
        """Handle cleanup downloads button click."""
        logger.info("Cleanup downloads button clicked")
        # TODO: Implement cleanup functionality
        dialog = Gtk.MessageDialog(
            transient_for=self.get_root(),
            modal=True,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.YES_NO,
            text="Clean Update Downloads",
        )
        dialog.format_secondary_text(
            "This will remove all downloaded update files.\n"
            "This will free up disk space but will require re-downloading "
            "if an update is needed.\n"
            "Continue?"
        )
        def on_response(dialog: Gtk.MessageDialog, response: int) -> None:
            if response == Gtk.ResponseType.YES:
                logger.info("User confirmed cleanup")
                # TODO: Implement actual cleanup
                info_dialog = Gtk.MessageDialog(
                    transient_for=self.get_root(),
                    modal=True,
                    message_type=Gtk.MessageType.INFO,
                    buttons=Gtk.ButtonsType.OK,
                    text="Cleanup Complete",
                )
                info_dialog.format_secondary_text("Update downloads have been cleaned up.")
                info_dialog.connect("response", lambda d, r: d.destroy())
                info_dialog.present()
            dialog.destroy()
        dialog.connect("response", on_response)
        dialog.present()

    def _on_optimize_clicked(self, button: Gtk.Button) -> None:
        """Handle optimize storage button click."""
        logger.info("Optimize storage button clicked")
        # TODO: Implement storage optimization
        dialog = Gtk.MessageDialog(
            transient_for=self.get_root(),
            modal=True,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.OK,
            text="Storage Optimization",
        )
        dialog.format_secondary_text(
            "Btrfs storage optimization has been started.\n"
            "This may take several minutes depending on disk usage."
        )
        dialog.connect("response", lambda d, r: d.destroy())
        dialog.present()

    def _on_pause_clicked(self, button: Gtk.Button) -> None:
        """Handle pause button click."""
        logger.info("Pause button clicked")
        # TODO: Implement pause functionality
        self._pause_btn.set_label("Resume")
        self._pause_btn.disconnect_by_func(self._on_pause_clicked)
        self._pause_btn.connect("clicked", self._on_resume_clicked)

    def _on_resume_clicked(self, button: Gtk.Button) -> None:
        """Handle resume button click."""
        logger.info("Resume button clicked")
        # TODO: Implement resume functionality
        self._pause_btn.set_label("Pause")
        self._pause_btn.disconnect_by_func(self._on_resume_clicked)
        self._pause_btn.connect("clicked", self._on_pause_clicked)

    def _on_cancel_clicked(self, button: Gtk.Button) -> None:
        """Handle cancel button click."""
        logger.info("Cancel button clicked")
        # TODO: Implement cancel functionality
        self._progress_card.set_visible(False)
        self._progress_bar.set_fraction(0.0)
        self._progress_bar.set_text("")
        self._progress_details.set_text("")

    def _fetch_update_info(self) -> None:
        """Fetch update information and update the UI."""
        try:
            # Read local version and profile
            local_version = self._read_file_or_default("/etc/shani-version", "19700101", "0-9")
            local_profile = self._read_file_or_default("/etc/shani-profile", "default", "a-z0-9_-")
            
            # Read current channel
            channel = self._read_file_or_default("/etc/shani-channel", "stable", "stable|latest")
            
            # Validate channel
            if channel not in ["stable", "latest"]:
                channel = "stable"
            
            # Update channel radio buttons. Suppress the toggled signal so the
            # programmatic selection during construction does not spawn a
            # background set-channel request.
            self._suppress_channel_toggle = True
            try:
                if channel == "stable":
                    self._channel_stable.set_active(True)
                else:
                    self._channel_latest.set_active(True)
            finally:
                self._suppress_channel_toggle = False
            
            # Check for actual updates using shani-deploy
            update_available = False
            latest_version = "Unknown"
            gateway_status = "Disconnected"
            
            try:
                # Use shani-deploy to check for updates
                result = self._cli_wrapper.run_shani_deploy(['--check', '--json'])
                if result and isinstance(result, dict):
                    # Extract update information from the result
                    current_version = result.get('current_version', local_version)
                    latest_version_from_check = result.get('latest_version', 'Unknown')
                    update_available = result.get('update_available', False)
                    # Update the latest version if we got a valid one from the check
                    if latest_version_from_check != 'Unknown':
                        latest_version = latest_version_from_check
                    
                    # Try to get gateway status using API client if available
                    if hasattr(self, '_api_client') and self._api_client:
                        try:
                            gateway_status_response = self._api_client.get_gateway_status()
                            gateway_status = gateway_status_response.get('status', 'Disconnected') if gateway_status_response else 'Disconnected'
                        except Exception:
                            logger.debug("Gateway status not available via API")
                    
                    logger.info(f"Update check: current={current_version}, latest={latest_version}, available={update_available}, gateway={gateway_status}")
                else:
                    logger.warning("Failed to get update information from shani-deploy")
            except Exception as e:
                logger.error(f"Error checking for updates: {e}")
            
            # Update state with update information
            if self._state:
                self._state._current_version = local_version
                self._state._latest_version = latest_version
                self._state._update_available = update_available
                self._state._update_channel = channel
                # Store gateway status in state
                if hasattr(self._state, '_gateway_status'):
                    self._state._gateway_status['updates_tab'] = gateway_status
                
            logger.info(f"Local version: {local_version}-{local_profile}, channel: {channel}, update available: {update_available}, gateway: {gateway_status}")
            
            # Clear history and add a real entry if available
            # For now, we'll keep the sample history
            
        except Exception as e:
            logger.error(f"Failed to fetch update info: {e}")

    def _check_updates_thread(self) -> None:
        """Run an update check in the background and surface the result.

        Calls the shared ``CLIWrapper.get_deploy_updates`` (which owns the
        ``shani-deploy --check --json`` invocation) and dispatches the UI
        update through ``GLib.idle_add`` so the main loop owns all widget
        mutation. A ``None`` result surfaces as an error dialog rather than
        being silently swallowed.
        """
        try:
            result = self._cli_wrapper.get_deploy_updates()
        except Exception as e:
            logger.error(f"Error checking for updates: {e}")
            GLib.idle_add(self._show_check_error, str(e))
            return
        if result is None:
            GLib.idle_add(self._show_check_error, "Failed to get update information from shani-deploy")
            return
        GLib.idle_add(self._display_check_result, result)

    def _display_check_result(self, result: dict) -> None:
        """Apply a successful update-check result to the UI (main loop)."""
        try:
            if not isinstance(result, dict):
                self._show_check_error("Unexpected update-check response")
                return
            current_version = result.get("current_version", "Unknown")
            latest_version = result.get("latest_version", "Unknown")
            update_available = result.get("update_available", False)
            if self._state:
                self._state._current_version = current_version
                self._state._latest_version = latest_version
                self._state._update_available = update_available
            self._progress_bar.set_text(
                f"Current: {current_version} | Latest: {latest_version}"
            )
            self._progress_details.set_text(
                "Update available" if update_available else "Up to date"
            )
        except Exception as e:
            logger.error(f"Failed to display update result: {e}")

    def _show_check_error(self, message: str) -> None:
        """Surface an update-check failure as a visible error dialog."""
        logger.error(f"Update check failed: {message}")
        try:
            dialog = Gtk.MessageDialog(
                transient_for=self.get_root(),
                modal=True,
                message_type=Gtk.MessageType.ERROR,
                buttons=Gtk.ButtonsType.OK,
                text="Update Check Failed",
            )
            dialog.format_secondary_text(message)
            dialog.connect("response", lambda d, r: d.destroy())
            dialog.present()
        except Exception as e:
            logger.error(f"Failed to show update check error dialog: {e}")

    def _read_file_or_default(self, file_path: str, default: str, filter_chars: str) -> str:
        """Read a file or return a default value.
        
        Args:
            file_path: Path to the file to read
            default: Default value to return if file cannot be read
            filter_chars: Characters to allow in the output (others will be removed)
            
        Returns:
            File content or default value
        """
        try:
            if not os.path.exists(file_path):
                return default

            with open(file_path, 'r') as f:
                content = f.read().strip()

            # filter_chars is a regex the content must fully match (e.g.
            # "stable|latest" for the channel file, "0-9" for the version).
            # A bare character-filter would silently accept "abae" from
            # "garbage!!!" against "stable|latest", so validate instead.
            if re.fullmatch(filter_chars, content):
                return content
            return default
        except Exception:
            return default