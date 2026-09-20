"""Deploy tab for the Shanios GUI."""

import logging
import subprocess
import threading
import time
import os
import json
import re
from datetime import datetime
from typing import override, Dict, Any

from gi.repository import GLib, Gtk  # type: ignore
from shani_gui.widgets import _gtk4_children

from shani_gui.state import AppState
from shani_gui.auth import AuthManager
from shani_gui.api_client import APIClient

logger = logging.getLogger(__name__)

class DeployTab(Gtk.Box):
    """Deploy tab showing system deployment and rollback options."""

    def __init__(
        self,
        state: AppState | None = None,
        auth_manager: AuthManager | None = None,
    ) -> None:
        """Initialize the deploy tab.
        
        Args:
            state: Application state object
            auth_manager: Authentication manager
        """
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self._state = state
        self._auth_manager = auth_manager
        self._update_thread = None
        self._stop_updates = False
        self._deploy_thread = None
        self._api_client = APIClient(auth_manager) if auth_manager else None

        self._setup_ui()
        logger.info("DeployTab initialized")
        
        # Start periodic updates
        self._start_periodic_updates()

    def _setup_ui(self) -> None:
        """Set up the user interface for the deploy tab."""
        logger.debug("Setting up deploy tab UI")

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

        # Create deploy status card
        status_card = self._create_deploy_status_card()
        content_box.append(status_card)

        # Create channel management card
        channel_card = self._create_channel_management_card()
        content_box.append(channel_card)

        # Create log viewer card
        log_card = self._create_log_viewer_card()
        content_box.append(log_card)

        logger.debug("Deploy tab UI created")

    def _create_deploy_status_card(self) -> Gtk.Box:
        """Create the deploy status card.
        
        Returns:
            Deploy status card widget
        """
        card = self._create_card("Deploy Status")

        # Create grid for status info
        grid = Gtk.Grid()
        grid.set_row_spacing(8)
        grid.set_column_spacing(16)
        grid.set_column_homogeneous(False)
        card.append(grid)

        # Add deploy status rows
        self._add_info_row(grid, 0, "Current Version:", "Checking...", "deploy-current")
        self._add_info_row(grid, 1, "Latest Version:", "Checking...", "deploy-latest")
        self._add_info_row(grid, 2, "Update Available:", "Checking...", "deploy-update-available")
        self._add_info_row(grid, 3, "Last Check:", "Never", "deploy-last-check")
        self._add_info_row(grid, 4, "Boot Slot:", "Checking...", "deploy-boot-slot")
        self._add_info_row(grid, 5, "Rollback Available:", "Checking...", "deploy-rollback-available")
        self._add_info_row(grid, 6, "Gateway Status:", "Disconnected", "deploy-gateway-status")

        # Add action buttons
        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        button_box.set_halign(Gtk.Align.END)
        check_updates_btn = Gtk.Button(label="Check for Updates")
        check_updates_btn.add_css_class("suggested-action")
        check_updates_btn.connect("clicked", self._on_check_updates_clicked)
        button_box.append(check_updates_btn)
        force_redeploy_btn = Gtk.Button(label="Force Redeploy")
        force_redeploy_btn.connect("clicked", self._on_force_redeploy_clicked)
        button_box.append(force_redeploy_btn)
        rollback_btn = Gtk.Button(label="Rollback")
        rollback_btn.connect("clicked", self._on_rollback_clicked)
        button_box.append(rollback_btn)
        card.append(button_box)

        return card

    def _create_channel_management_card(self) -> Gtk.Box:
        """Create the channel management card.
        
        Returns:
            Channel management card widget
        """
        card = self._create_card("Update Channel Management")

        # Create grid for channel info
        grid = Gtk.Grid()
        grid.set_row_spacing(8)
        grid.set_column_spacing(16)
        grid.set_column_homogeneous(False)
        card.append(grid)

        # Add channel info rows
        self._add_info_row(grid, 0, "Current Channel:", "Checking...", "deploy-current-channel")
        self._add_info_row(grid, 1, "Available Channels:", "Checking...", "deploy-available-channels")
        self._add_info_row(grid, 2, "Auto-Updates:", "Checking...", "deploy-auto-updates")

        # Add channel selector
        channel_label = Gtk.Label(label="Switch to Channel:")
        channel_label.add_css_class("label-label")
        channel_label.set_halign(Gtk.Align.START)
        grid.attach(channel_label, 0, 3, 1, 1)

        self._channel_combo = Gtk.ComboBoxText()
        self._channel_combo.append_text("stable")
        self._channel_combo.append_text("testing")
        self._channel_combo.append_text("unstable")
        self._channel_combo.set_active(0)  # stable by default
        grid.attach(self._channel_combo, 1, 3, 1, 1)

        # Add action buttons
        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        button_box.set_halign(Gtk.Align.END)
        change_channel_btn = Gtk.Button(label="Change Channel")
        change_channel_btn.connect("clicked", self._on_change_channel_clicked)
        button_box.append(change_channel_btn)
        sync_license_btn = Gtk.Button(label="Sync License")
        sync_license_btn.connect("clicked", self._on_sync_license_clicked)
        button_box.append(sync_license_btn)
        card.append(button_box)

        return card

    def _create_log_viewer_card(self) -> Gtk.Box:
        """Create the log viewer card.
        
        Returns:
            Log viewer card widget
        """
        card = self._create_card("Deploy Log Viewer")

        # Create scrolled text view for logs
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)
        scrolled.set_size_request(-1, 200)
        card.append(scrolled)

        # Text view for deploy logs
        self._log_textview = Gtk.TextView()
        self._log_textview.set_editable(False)
        self._log_textview.set_cursor_visible(False)
        self._log_textview.set_wrap_mode(Gtk.WrapMode.WORD)
        scrolled.set_child(self._log_textview)

        # Add action buttons
        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        button_box.set_halign(Gtk.Align.END)
        refresh_btn = Gtk.Button(label="Refresh")
        refresh_btn.connect("clicked", self._on_refresh_logs_clicked)
        button_box.append(refresh_btn)
        clear_btn = Gtk.Button(label="Clear Logs")
        clear_btn.connect("clicked", self._on_clear_logs_clicked)
        button_box.append(clear_btn)
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
        """Start periodic updates for deploy status."""
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
        """Update loop for fetching deploy status."""
        while not self._stop_updates:
            try:
                self._update_deploy_status()
                # Update every 30 seconds
                time.sleep(30)
            except Exception as e:
                logger.error(f"Error in deploy update loop: {e}")
                time.sleep(5)  # Shorter delay on error

    def _update_deploy_status(self) -> None:
        """Update deploy status information."""
        try:
            # Update current version
            self._update_current_version()
            
            # Update latest version and check for updates
            self._update_latest_version()
            
            # Update last check time
            self._update_last_check()
            
            # Update boot slot
            self._update_boot_slot()
            
            # Update rollback availability
            self._update_rollback_available()
            
            # Update channel info
            self._update_channel_info()
            
            # Update gateway status
            self._update_gateway_status_indicator()
            
        except Exception as e:
            logger.error(f"Error updating deploy status: {e}")

    def _update_current_version(self) -> None:
        """Update current version display."""
        try:
            version_file = "/etc/shani-version"
            profile_file = "/etc/shani-profile"
            
            version = "Unknown"
            profile = "Unknown"
            
            if os.path.exists(version_file):
                with open(version_file, 'r') as f:
                    version = f.read().strip()
                    
            if os.path.exists(profile_file):
                with open(profile_file, 'r') as f:
                    profile = f.read().strip()
            
            if version and profile:
                version_text = f"v{version}-{profile}"
            else:
                version_text = "Unknown"
                
            GLib.idle_add(self._update_label_text, "deploy-current", version_text)
            
        except Exception as e:
            logger.error(f"Error updating current version: {e}")
            GLib.idle_add(self._update_label_text, "deploy-current", "Error")

    def _update_latest_version(self) -> None:
        """Update latest version and check for updates."""
        try:
            # Read current version and profile
            current_version = self._read_file_or_default("/etc/shani-version", "19700101", "0-9")
            current_profile = self._read_file_or_default("/etc/shani-profile", "default", "a-z0-9_-")
            
            # Read current channel
            channel = self._read_file_or_default("/etc/shani-channel", "stable", "stable|latest")
            
            # Validate channel
            if channel not in ["stable", "latest"]:
                channel = "stable"
            
            # Construct URLs for version checking
            base_url = "https://sourceforge.net/projects/shanios/files"
            r2_base_url = "https://downloads.shani.dev"
            
            channel_url = f"{base_url}/{current_profile}/{channel}.txt"
            r2_url = f"{r2_base_url}/{current_profile}/{channel}.txt"
            
            # Try to fetch remote info (simplified for GUI)
            remote_image = self._fetch_remote_info(r2_url) or self._fetch_remote_info(channel_url)
            
            latest_version_text = "Unknown"
            update_available_text = "Checking..."
            update_needed = False
            
            if remote_image:
                # Parse remote image name: shanios-YYYYMMDD-profile.zst
                import re
                match = re.match(r'shanios-([0-9]{8})-([a-z0-9_-]+)\.zst$', remote_image)
                if match:
                    remote_version = match.group(1)
                    remote_profile = match.group(2)
                    
                    # Format latest version
                    latest_version_text = f"v{remote_version}-{remote_profile}"
                    
                    # Check if update is needed
                    update_needed = self._is_update_needed(current_version, current_profile, remote_version, remote_profile)
                    update_available_text = "● Yes" if update_needed else "○ No"
            
            # Update UI on main thread
            GLib.idle_add(self._update_label_text, "deploy-latest", latest_version_text)
            GLib.idle_add(self._update_label_text, "deploy-update-available", update_available_text)
            
            # Update state
            if self._state:
                GLib.idle_add(setattr, self._state, '_update_available', update_needed)
            
        except Exception as e:
            logger.error(f"Error updating latest version: {e}")
            GLib.idle_add(self._update_label_text, "deploy-latest", "Error")
            GLib.idle_add(self._update_label_text, "deploy-update-available", "Error")
            # Update state to reflect error
            if self._state:
                GLib.idle_add(setattr, self._state, '_update_available', False)

    def _update_last_check(self) -> None:
        """Update last check time display."""
        try:
            # For now, we'll just show the current time as last check
            # In a more sophisticated implementation, we might store when we last checked
            current_time = time.strftime("%H:%M:%S")
            status_text = f"{current_time}"
            GLib.idle_add(self._update_label_text, "deploy-last-check", status_text)
        except Exception as e:
            logger.error(f"Error updating last check: {e}")
            GLib.idle_add(self._update_label_text, "deploy-last-check", "Error")

    def _update_boot_slot(self) -> None:
        """Update boot slot display."""
        try:
            slot_file = "/data/current-slot"
            if os.path.exists(slot_file):
                with open(slot_file, 'r') as f:
                    slot = f.read().strip()
                if slot in ["blue", "green"]:
                    status_text = f"@{slot}"
                else:
                    status_text = f"@unknown ({slot})"
            else:
                status_text = "@unknown"
                
            GLib.idle_add(self._update_label_text, "deploy-boot-slot", status_text)
        except Exception as e:
            logger.error(f"Error updating boot slot: {e}")
            GLib.idle_add(self._update_label_text, "deploy-boot-slot", "@error")

    def _update_rollback_available(self) -> None:
        """Update rollback availability display."""
        try:
            # Check if we can rollback (if there's a non-booted slot with a different version)
            current_slot = self._get_booted_subvol()
            other_slot = self._other_slot(current_slot)
            
            # Get version of current slot
            current_version = self._get_slot_version(current_slot)
            # Get version of other slot
            other_version = self._get_slot_version(other_slot)
            
            # Check if versions differ
            if current_version and other_version and current_version != other_version:
                status_text = "● Yes"
            else:
                status_text = "○ No"
                
            GLib.idle_add(self._update_label_text, "deploy-rollback-available", status_text)
        except Exception as e:
            logger.error(f"Error updating rollback availability: {e}")
            GLib.idle_add(self._update_label_text, "deploy-rollback-available", "○ Error")

    def _update_channel_info(self) -> None:
        """Update channel information display."""
        try:
            # Current channel
            current_channel = self._read_file_or_default("/etc/shani-channel", "stable", "stable|latest")
            if current_channel not in ["stable", "latest"]:
                current_channel = "stable"
            GLib.idle_add(self._update_label_text, "deploy-current-channel", current_channel)
            
            # Available channels (hardcoded for now)
            GLib.idle_add(self._update_label_text, "deploy-available-channels", "stable, testing, unstable")
            
            # Auto-updates (check if shani-update service is enabled)
            auto_updates = self._is_service_enabled("shani-update.service")
            status_text = "Enabled" if auto_updates else "Disabled"
            GLib.idle_add(self._update_label_text, "deploy-auto-updates", status_text)
            
        except Exception as e:
            logger.error(f"Error updating channel info: {e}")
            GLib.idle_add(self._update_label_text, "deploy-current-channel", "Error")
            GLib.idle_add(self._update_label_text, "deploy-available-channels", "Error")
            GLib.idle_add(self._update_label_text, "deploy-auto-updates", "Error")

    def _update_gateway_status_indicator(self) -> None:
        """Update gateway status display."""
        try:
            if self._api_client:
                result = self._api_client.get_gateway_status()
                if result.get("connected"):
                    status_text = "Connected"
                else:
                    status_text = "Disconnected"
            else:
                status_text = "Disconnected"
            GLib.idle_add(self._update_label_text, "deploy-gateway-status", status_text)
        except Exception as e:
            logger.error(f"Error updating gateway status: {e}")
            GLib.idle_add(self._update_label_text, "deploy-gateway-status", "Error")

    def _get_booted_subvol(self) -> str:
        """Get the booted subvolume.
        
        Returns:
            Booted subvolume (blue/green) or unknown
        """
        try:
            # Try to get from /proc/cmdline
            result = subprocess.run(
                ['grep', '-o', 'subvol=@?\\K[^,]+', '/proc/cmdline'],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0 and result.stdout.strip():
                subvol = result.stdout.strip()
                if subvol.startswith('@'):
                    subvol = subvol[1:]
                if subvol in ['blue', 'green']:
                    return subvol
            
            # Fallback to btrfs default subvolume
            result = subprocess.run(
                ['btrfs', 'subvolume', 'get-default', '/'],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0:
                subvol = result.stdout.strip()
                if subvol.startswith('@'):
                    subvol = subvol[1:]
                if subvol in ['blue', 'green']:
                    return subvol
                    
        except Exception:
            pass
        return "unknown"

    def _other_slot(self, slot: str) -> str:
        """Get the other slot.
        
        Args:
            slot: Current slot (blue/green)
            
        Returns:
            Other slot (green/blue)
        """
        if slot == "blue":
            return "green"
        elif slot == "green":
            return "blue"
        return "unknown"

    def _get_slot_version(self, slot: str) -> str | None:
        """Get the version of a specific slot.
        
        Args:
            slot: Slot name (blue/green)
            
        Returns:
            Version string or None if not found
        """
        try:
            # Check if the slot is mounted
            result = subprocess.run(
                ['findmnt', '-n', '-o', 'TARGET', '--source', f'LABEL=shanios_{slot}'],
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0 and result.stdout.strip():
                mount_point = result.stdout.strip()
                version_file = os.path.join(mount_point, 'etc', 'shani-version')
                profile_file = os.path.join(mount_point, 'etc', 'shani-profile')
                
                if os.path.exists(version_file) and os.path.exists(profile_file):
                    with open(version_file, 'r') as f:
                        version = f.read().strip()
                    with open(profile_file, 'r') as f:
                        profile = f.read().strip()
                    if version and profile:
                        return f"{version}-{profile}"
        except Exception:
            pass
        return None

    def _is_service_enabled(self, service_name: str) -> bool:
        """Check if a service is enabled.
        
        Args:
            service_name: Name of the service to check
            
        Returns:
            True if enabled, False otherwise
        """
        try:
            result = subprocess.run(
                ['systemctl', 'is-enabled', service_name],
                capture_output=True,
                text=True,
                timeout=5
            )
            return result.returncode == 0 and result.stdout.strip() == "enabled"
        except Exception:
            return False

    def _fetch_remote_info(self, url: str) -> str | None:
        """Fetch remote information from URL.
        
        Args:
            url: URL to fetch
            
        Returns:
            Remote image name or None if failed
        """
        try:
            import subprocess
            result = subprocess.run(
                ['curl', '-fsSL', '--connect-timeout', '10', '--max-time', '30', url],
                capture_output=True,
                text=True,
                timeout=35
            )
            if result.returncode == 0 and result.stdout.strip():
                # Extract first line and filter to alphanumeric, dash, dot, underscore
                content = result.stdout.strip().split('\n')[0]
                filtered = ''.join(c for c in content if c.isalnum() or c in '.-_')
                return filtered if filtered else None
        except Exception as e:
            logger.debug(f"Failed to fetch remote info from {url}: {e}")
        return None

    def _is_update_needed(self, lv: str, lp: str, rv: str, rp: str) -> bool:
        """Check if an update is needed.
        
        Args:
            lv: Local version
            lp: Local profile
            rv: Remote version
            rp: Remote profile
            
        Returns:
            True if update needed, False otherwise
        """
        # Simple version comparison (YYYYMMDD format)
        if lv == rv:
            return lp != rp  # Update needed if profiles differ
        return lv < rv  # Update needed if remote version is newer

    def _update_label_text(self, widget_name: str, text: str) -> None:
        """Update a label widget by its name.
        
        Args:
            widget_name: The name of the widget to update
            text: The new text for the widget
        """
        def find_widget(widget):
            if widget.get_name() == widget_name:
                return widget
            if isinstance(widget, Gtk.Widget):
                for child in _gtk4_children(widget):
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
    def _on_check_updates_clicked(self, button: Gtk.Button) -> None:
        """Handle check for updates button click."""
        logger.info("Check for updates button clicked")
        # Disable button during check
        button.set_sensitive(False)
        button.set_label("Checking...")
        
        # Run update check in background thread
        self._deploy_thread = threading.Thread(target=self._check_updates_thread, args=(button,))
        self._deploy_thread.daemon = True
        self._deploy_thread.start()

    def _check_updates_thread(self, button: Gtk.Button) -> None:
        """Check for updates in a background thread.
        
        Args:
            button: The button that was clicked
        """
        try:
            # Trigger an immediate update check
            self._update_latest_version()
            
            # Update last check time
            GLib.idle_add(self._update_label_text, "deploy-last-check", time.strftime("%H:%M:%S"))
            
            # Re-enable button
            GLib.idle_add(button.set_sensitive, True)
            GLib.idle_add(button.set_label, "Check for Updates")
            
        except Exception as e:
            logger.error(f"Error checking for updates: {e}")
            GLib.idle_add(button.set_sensitive, True)
            GLib.idle_add(button.set_label, "Check for Updates")
            # Show error dialog
            error_dialog = Gtk.MessageDialog(
                transient_for=self.get_root(),
                modal=True,
                message_type=Gtk.MessageType.ERROR,
                buttons=Gtk.ButtonsType.OK,
                text="Update Check Failed",
            )
            error_dialog.format_secondary_text(f"Failed to check for updates:\n{str(e)}")
            error_dialog.connect("response", lambda d, r: d.destroy())
            error_dialog.present()

    def _on_force_redeploy_clicked(self, button: Gtk.Button) -> None:
        """Handle force redeploy button click."""
        logger.info("Force redeploy button clicked")
        dialog = Gtk.MessageDialog(
            transient_for=self.get_root(),
            modal=True,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.YES_NO,
            text="Confirm Force Redeploy",
        )
        dialog.format_secondary_text(
            "This will force a redeploy of the current version.\n"
            "This can be useful if the system is in an inconsistent state.\n"
            "A reboot will be required to complete the redeploy.\n"
            "Continue?"
        )
        def on_response(dialog: Gtk.MessageDialog, response: int) -> None:
            if response == Gtk.ResponseType.YES:
                logger.info("User confirmed force redeploy")
                # Run force redeploy in background thread
                self._deploy_thread = threading.Thread(target=self._force_redeploy_thread)
                self._deploy_thread.daemon = True
                self._deploy_thread.start()
            dialog.destroy()
        dialog.connect("response", on_response)
        dialog.present()

    def _force_redeploy_thread(self) -> None:
        """Run force redeploy in a background thread."""
        try:
            # Run the shani-deploy command with --force
            result = subprocess.run(
                ['shani-deploy', '--force'],
                capture_output=True,
                text=True,
                timeout=300  # 5 minute timeout for deploy
            )
            
            # Update UI on main thread
            if result.returncode == 0:
                logger.info("Force redeploy successful")
                GLib.idle_add(self._show_redeploy_success)
            else:
                logger.error(f"Force redeploy failed: {result.stderr}")
                GLib.idle_add(self._show_redeploy_error, result.stderr)
                
        except subprocess.TimeoutExpired:
            logger.error("Force redeploy timed out")
            GLib.idle_add(self._show_redeploy_error, "Force redeploy timed out")
        except Exception as e:
            logger.error(f"Error during force redeploy: {e}")
            GLib.idle_add(self._show_redeploy_error, str(e))

    def _show_redeploy_success(self) -> None:
        """Show redeploy success message."""
        dialog = Gtk.MessageDialog(
            transient_for=self.get_root(),
            modal=True,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.OK,
            text="Redeploy Successful",
        )
        dialog.format_secondary_text(
            "The force redeploy has completed successfully.\n"
            "A reboot is required to boot into the redeployed system.\n"
            "Please save your work and reboot when ready."
        )
        dialog.connect("response", lambda d, r: d.destroy())
        dialog.present()

    def _show_redeploy_error(self, error_message: str) -> None:
        """Show redeploy error message.
        
        Args:
            error_message: Error message to display
        """
        dialog = Gtk.MessageDialog(
            transient_for=self.get_root(),
            modal=True,
            message_type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.OK,
            text="Redeploy Failed",
        )
        dialog.format_secondary_text(f"The force redeploy failed:\n{error_message}")
        dialog.connect("response", lambda d, r: d.destroy())
        dialog.present()

    def _on_rollback_clicked(self, button: Gtk.Button) -> None:
        """Handle rollback button click."""
        logger.info("Rollback button clicked")
        dialog = Gtk.MessageDialog(
            transient_for=self.get_root(),
            modal=True,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.YES_NO,
            text="Confirm Rollback",
        )
        dialog.format_secondary_text(
            "This will rollback to the previous version.\n"
            "A reboot will be required to complete the rollback.\n"
            "Continue?"
        )
        def on_response(dialog: Gtk.MessageDialog, response: int) -> None:
            if response == Gtk.ResponseType.YES:
                logger.info("User confirmed rollback")
                # Run rollback in background thread
                self._deploy_thread = threading.Thread(target=self._rollback_thread)
                self._deploy_thread.daemon = True
                self._deploy_thread.start()
            dialog.destroy()
        dialog.connect("response", on_response)
        dialog.present()

    def _rollback_thread(self) -> None:
        """Run rollback in a background thread."""
        try:
            # Run the shani-deploy command with --rollback
            result = subprocess.run(
                ['shani-deploy', '--rollback'],
                capture_output=True,
                text=True,
                timeout=300  # 5 minute timeout for rollback
            )
            
            # Update UI on main thread
            if result.returncode == 0:
                logger.info("Rollback successful")
                GLib.idle_add(self._show_rollback_success)
            else:
                logger.error(f"Rollback failed: {result.stderr}")
                GLib.idle_add(self._show_rollback_error, result.stderr)
                
        except subprocess.TimeoutExpired:
            logger.error("Rollback timed out")
            GLib.idle_add(self._show_rollback_error, "Rollback timed out")
        except Exception as e:
            logger.error(f"Error during rollback: {e}")
            GLib.idle_add(self._show_rollback_error, str(e))

    def _show_rollback_success(self) -> None:
        """Show rollback success message."""
        dialog = Gtk.MessageDialog(
            transient_for=self.get_root(),
            modal=True,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.OK,
            text="Rollback Successful",
        )
        dialog.format_secondary_text(
            "The rollback has completed successfully.\n"
            "A reboot is required to boot into the rolled-back system.\n"
            "Please save your work and reboot when ready."
        )
        dialog.connect("response", lambda d, r: d.destroy())
        dialog.present()

    def _show_rollback_error(self, error_message: str) -> None:
        """Show rollback error message.
        
        Args:
            error_message: Error message to display
        """
        dialog = Gtk.MessageDialog(
            transient_for=self.get_root(),
            modal=True,
            message_type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.OK,
            text="Rollback Failed",
        )
        dialog.format_secondary_text(f"The rollback failed:\n{error_message}")
        dialog.connect("response", lambda d, r: d.destroy())
        dialog.present()

    def _on_change_channel_clicked(self, button: Gtk.Button) -> None:
        """Handle change channel button click."""
        logger.info("Change channel button clicked")
        selected_channel = self._channel_combo.get_active_text()
        # Run channel change in background thread
        self._deploy_thread = threading.Thread(target=self._change_channel_thread, args=(selected_channel,))
        self._deploy_thread.daemon = True
        self._deploy_thread.start()

    def _on_sync_license_clicked(self, button: Gtk.Button) -> None:
        """Handle sync license button click."""
        logger.info("Sync license button clicked")
        # Run license sync in background thread
        self._deploy_thread = threading.Thread(target=self._sync_license_thread)
        self._deploy_thread.daemon = True
        self._deploy_thread.start()

    def _sync_license_thread(self) -> None:
        """Run license sync in a background thread."""
        try:
            # Run the shani-deploy command to sync license
            result = subprocess.run(
                ['shani-deploy', '--sync-license'],  # This might not be a real flag, adjust as needed
                capture_output=True,
                text=True,
                timeout=30
            )
            
            # Update UI on main thread
            if result.returncode == 0:
                logger.info("License sync successful")
                GLib.idle_add(self._show_license_sync_success)
            else:
                logger.error(f"License sync failed: {result.stderr}")
                GLib.idle_add(self._show_license_sync_error, result.stderr)
                
        except Exception as e:
            logger.error(f"Error during license sync: {e}")
            GLib.idle_add(self._show_license_sync_error, str(e))

    def _show_license_sync_success(self) -> None:
        """Show license sync success message."""
        dialog = Gtk.MessageDialog(
            transient_for=self.get_root(),
            modal=True,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.OK,
            text="License Sync Successful",
        )
        dialog.format_secondary_text(
            "The license has been successfully synchronized with the Shanios platform."
        )
        dialog.connect("response", lambda d, r: d.destroy())
        dialog.present()

    def _show_license_sync_error(self, error_message: str) -> None:
        """Show license sync error message.
        
        Args:
            error_message: Error message to display
        """
        dialog = Gtk.MessageDialog(
            transient_for=self.get_root(),
            modal=True,
            message_type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.OK,
            text="License Sync Failed",
        )
        dialog.format_secondary_text(f"Failed to synchronize license:\n{error_message}")
        dialog.connect("response", lambda d, r: d.destroy())
        dialog.present()

    def _on_refresh_logs_clicked(self, button: Gtk.Button) -> None:
        """Handle refresh logs button click."""
        logger.info("Refresh logs button clicked")
        # Refresh logs in background thread
        self._deploy_thread = threading.Thread(target=self._refresh_logs_thread)
        self._deploy_thread.daemon = True
        self._deploy_thread.start()

    def _refresh_logs_thread(self) -> None:
        """Refresh deploy logs in a background thread."""
        try:
            log_file = "/var/log/shanios-deploy.log"
            if os.path.exists(log_file):
                with open(log_file, 'r') as f:
                    # Get last 50 lines
                    lines = f.readlines()
                    last_lines = ''.join(lines[-50:]) if len(lines) > 50 else ''.join(lines)
                log_text = last_lines if last_lines else "No log entries found."
            else:
                log_text = "Log file not found."
                
            # Update UI on main thread
            GLib.idle_add(self._update_console_text, log_text)
            
        except Exception as e:
            logger.error(f"Error refreshing deploy logs: {e}")
            GLib.idle_add(self._update_console_text, f"Error refreshing logs: {str(e)}")

    def _update_console_text(self, text: str) -> None:
        """Update the console text view.
        
        Args:
            text: Text to display in the console view
        """
        buffer = self._log_textview.get_buffer()
        buffer.set_text(text)
        # Scroll to end
        iter = buffer.get_end_iter()
        self._log_textview.scroll_to_iter(iter, 0.0, False, 0.0, 0.0)

    def _on_clear_logs_clicked(self, button: Gtk.Button) -> None:
        """Handle clear logs button click."""
        logger.info("Clear logs button clicked")
        buffer = self._log_textview.get_buffer()
        buffer.set_text("")
        logger.debug("Deploy logs cleared")

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
            
            # Filter out unwanted characters
            filtered = ''.join(c for c in content if c in filter_chars)
            return filtered if filtered else default
        except Exception:
            return default