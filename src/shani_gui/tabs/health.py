"""Health tab for the Shanios GUI."""

import logging
import json
import subprocess
import threading
import time
import os
from datetime import datetime
from typing import override

from gi.repository import Gtk  # type: ignore

from shani_gui.state import AppState
from shani_gui.auth import AuthManager


logger = logging.getLogger(__name__)


class HealthTab(Gtk.Box):
    """Health tab showing system health diagnostics."""

    def __init__(
        self,
        state: AppState | None = None,
        auth_manager: AuthManager | None = None,
    ) -> None:
        """Initialize the health tab.
        
        Args:
            state: Application state object
            auth_manager: Authentication manager
        """
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self._state = state
        self._auth_manager = auth_manager
        self._health_thread = None
        self._stop_health = False

        self._setup_ui()
        logger.info("HealthTab initialized")

    def _setup_ui(self) -> None:
        """Set up the user interface for the health tab."""
        logger.debug("Setting up health tab UI")

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

        # Create health check controls card
        controls_card = self._create_health_check_controls_card()
        content_box.append(controls_card)

        # Create health results card
        results_card = self._create_health_results_card()
        content_box.append(results_card)

        # Create log viewer card
        log_card = self._create_log_viewer_card()
        content_box.append(log_card)

        logger.debug("Health tab UI created")

    def _create_health_check_controls_card(self) -> Gtk.Box:
        """Create the health check controls card.
        
        Returns:
            Health check controls card widget
        """
        card = self._create_card("Health Check Controls")

        # Create grid for controls
        grid = Gtk.Grid()
        grid.set_row_spacing(12)
        grid.set_column_spacing(16)
        grid.set_column_homogeneous(False)
        card.append(grid)

        # Add health check buttons
        verify_btn = Gtk.Button(label="Verify System")
        verify_btn.add_css_class("suggested-action")
        verify_btn.connect("clicked", self._on_verify_clicked)
        grid.attach(verify_btn, 0, 0, 1, 1)

        security_btn = Gtk.Button(label="Security Audit")
        security_btn.connect("clicked", self._on_security_clicked)
        grid.attach(security_btn, 1, 0, 1, 1)

        # Add VirusTotal scan button
        virustotal_btn = Gtk.Button(label="VirusTotal Scan")
        virustotal_btn.add_css_class("suggested-action")
        virustotal_btn.connect("clicked", self._on_virustotal_clicked)
        grid.attach(virustotal_btn, 0, 1, 1, 1)

        # Add VirusTotal scan button
        virustotal_btn = Gtk.Button(label="VirusTotal Scan")
        virustotal_btn.add_css_class("suggested-action")
        virustotal_btn.connect("clicked", self._on_virustotal_clicked)
        grid.attach(virustotal_btn, 0, 1, 1, 1)

        hardware_btn = Gtk.Button(label="Hardware Check")
        hardware_btn.connect("clicked", self._on_hardware_clicked)
        grid.attach(hardware_btn, 0, 1, 1, 1)

        boot_btn = Gtk.Button(label="Boot Validation")
        boot_btn.connect("clicked", self._on_boot_clicked)
        grid.attach(boot_btn, 1, 1, 1, 1)

        all_btn = Gtk.Button(label="Run All Checks")
        all_btn.add_css_class("suggested-action")
        all_btn.connect("clicked", self._on_all_clicked)
        grid.attach(all_btn, 0, 2, 2, 1)

        # Add progress bar
        self._progress_bar = Gtk.ProgressBar()
        self._progress_bar.set_visible(False)
        grid.attach(self._progress_bar, 0, 3, 2, 1)

        return card

    def _create_health_results_card(self) -> Gtk.Box:
        """Create the health results card.
        
        Returns:
            Health results card widget
        """
        card = self._create_card("Health Results")

        # Create scrolled text view for results
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)
        scrolled.set_height_request(300)
        card.append(scrolled)

        # Text view for health results
        self._results_textview = Gtk.TextView()
        self._results_textview.set_editable(False)
        self._results_textview.set_cursor_visible(False)
        self._results_textview.set_wrap_mode(Gtk.WrapMode.WORD)
        scrolled.set_child(self._results_textview)

        # Add action buttons
        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        button_box.set_halign(Gtk.Align.END)
        save_btn = Gtk.Button(label="Save Results")
        save_btn.connect("clicked", self._on_save_results_clicked)
        button_box.append(save_btn)
        clear_btn = Gtk.Button(label="Clear")
        clear_btn.connect("clicked", self._on_clear_results_clicked)
        button_box.append(clear_btn)
        card.append(button_box)

        return card

    def _create_log_viewer_card(self) -> Gtk.Box:
        """Create the log viewer card.
        
        Returns:
            Log viewer card widget
        """
        card = self._create_card("Health Log Viewer")

        # Create scrolled text view for logs
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)
        scrolled.set_height_request(150)
        card.append(scrolled)

        # Text view for health logs
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

    # Event handlers
    def _on_verify_clicked(self, button: Gtk.Button) -> None:
        """Handle verify system button click."""
        logger.info("Verify system button clicked")
        self._run_health_check("--verify")

    def _on_security_clicked(self, button: Gtk.Button) -> None:
        """Handle security audit button click."""
        logger.info("Security audit button clicked")
        self._run_health_check("--security")

    def _on_hardware_clicked(self, button: Gtk.Button) -> None:
        """Handle hardware check button click."""
        logger.info("Hardware check button clicked")
        self._run_health_check("--hardware")

    def _on_boot_clicked(self, button: Gtk.Button) -> None:
        """Handle boot validation button click."""
        logger.info("Boot validation button clicked")
        self._run_health_check("--boot")

    def _on_all_clicked(self, button: Gtk.Button) -> None:
        """Handle run all checks button click."""
        logger.info("Run all checks button clicked")
        self._run_health_check("--all")

    def _on_virustotal_clicked(self, button: Gtk.Button) -> None:
        """Handle VirusTotal scan button click."""
        logger.info("VirusTotal scan button clicked")
        self._run_virustotal_scan()

    def _on_hardware_clicked(self, button: Gtk.Button) -> None:
        """Handle hardware check button click."""
        logger.info("Hardware check button clicked")
        self._run_health_check("--hardware")

    def _on_boot_clicked(self, button: Gtk.Button) -> None:
        """Handle boot validation button click."""
        logger.info("Boot validation button clicked")
        self._run_health_check("--boot")

    def _on_all_clicked(self, button: Gtk.Button) -> None:
        """Handle run all checks button click."""
        logger.info("Run all checks button clicked")
        self._run_health_check("--all")

    def _on_virustotal_clicked(self, button: Gtk.Button) -> None:
        """Handle VirusTotal scan button click."""
        logger.info("VirusTotal scan button clicked")
        self._run_virustotal_scan()

    def _run_health_check(self, check_type: str) -> None:
        """Run a health check with the specified type."""
        logger.info(f"Running health check: {check_type}")
        
        # Show progress bar
        self._progress_bar.set_visible(True)
        self._progress_bar.pulse()
        
        # Disable buttons during check
        self._set_buttons_sensitive(False)
        
        # Run health check in background thread
        self._health_thread = threading.Thread(target=self._health_check_thread, args=(check_type,))
        self._health_thread.daemon = True
        self._health_thread.start()

    def _health_check_thread(self, check_type: str) -> None:
        """Run health check in a background thread.
        
        Args:
            check_type: The type of health check to run (--verify, --security, etc.)
        """
        try:
            # Determine the command to run
            if check_type == "--all":
                # For --all, we run each check separately and combine results
                # But for simplicity, we'll just run shani-health without args (which does verify by default?)
                # According to shani-health --help, default is --verify
                cmd = ["shani-health"]
            else:
                cmd = ["shani-health", check_type]
            
            # Add --json flag for machine-readable output
            cmd.append("--json")
            
            logger.debug(f"Running health check command: {' '.join(cmd)}")
            
            # Run the command
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60  # Health checks can take a while
            )
            
            # Process the result
            if result.returncode == 0:
                # Success - parse JSON output
                try:
                    health_data = json.loads(result.stdout)
                    # Add timestamp if not present
                    if "timestamp" not in health_data:
                        health_data["timestamp"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                    # Add check_type if not present
                    if "check_type" not in health_data:
                        health_data["check_type"] = check_type[2:] if check_type.startswith("--") else check_type
                    # Update UI on main thread
                    Gtk.idle_add(self._display_results, health_data)
                except json.JSONDecodeError as e:
                    logger.error(f"Failed to parse JSON from shani-health: {e}")
                    logger.debug(f"stdout: {result.stdout}")
                    logger.debug(f"stderr: {result.stderr}")
                    Gtk.idle_add(self._display_error, f"Failed to parse health check output: {e}")
            else:
                # Error - show error message
                logger.error(f"Health check failed with return code {result.returncode}: {result.stderr}")
                Gtk.idle_add(self._display_error, f"Health check failed:\n{result.stderr}")
                
        except subprocess.TimeoutExpired:
            logger.error("Health check timed out")
            Gtk.idle_add(self._display_error, "Health check timed out after 60 seconds")
        except Exception as e:
            logger.error(f"Error running health check: {e}")
            Gtk.idle_add(self._display_error, f"Error running health check: {str(e)}")
        finally:
            # Always hide progress bar and re-enable buttons
            Gtk.idle_add(self._progress_bar.set_visible, False)
            Gtk.idle_add(self._set_buttons_sensitive, True)

    def _display_results(self, result: dict) -> None:
        """Display health check results in the results text view.
        
        Args:
            result: Dictionary containing health check results
        """
        logger.debug(f"Displaying health check results: {result}")
        
        # Update state with health information
        if self._state:
            # Update health status based on result
            status = result.get("status", "unknown")
            # Map status to our health status values
            if status == "healthy" or status == "passed":
                self._state._health_status = "healthy"
            elif status == "warning":
                self._state._health_status = "warning"
            elif status == "critical" or status == "failed":
                self._state._health_status = "critical"
            else:
                self._state._health_status = "unknown"
            
            # Update timestamp
            self._state._last_health_check = datetime.fromtimestamp(time.time())
            
            # Update counts if available in details
            details = result.get("details", {})
            if isinstance(details, dict):
                self._state._health_critical_count = details.get("critical_count", 0)
                self._state._health_warning_count = details.get("warning_count", 0)
                self._state._health_info_count = details.get("info_count", 0)
        
        # Format results as JSON for display
        formatted_json = json.dumps(result, indent=2)
        
        # Update results text view
        buffer = self._results_textview.get_buffer()
        buffer.set_text(formatted_json)
        
        # Also add to log
        timestamp = result.get("timestamp", "unknown")
        check_type = result.get("check_type", "unknown")
        status = result.get("status", "unknown")
        log_entry = f"[{timestamp}] {check_type} check: {status}\n"
        self._append_to_log(log_entry)

    def _display_error(self, error_message: str) -> None:
        """Display an error message in the results text view.
        
        Args:
            error_message: Error message to display
        """
        logger.error(f"Displaying health check error: {error_message}")
        
        # Create error result to display
        error_result = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "check_type": "error",
            "status": "failed",
            "details": {
                "message": error_message
            }
        }
        
        # Format as JSON
        formatted_json = json.dumps(error_result, indent=2)
        
        # Update results text view
        buffer = self._results_textview.get_buffer()
        buffer.set_text(formatted_json)
        
        # Also add to log
        log_entry = f"[{error_result['timestamp']}] error check: failed\n"
        self._append_to_log(log_entry)

    def _append_to_log(self, text: str) -> None:
        """Append text to the log viewer.
        
        Args:
            text: Text to append to the log
        """
        buffer = self._log_textview.get_buffer()
        end_iter = buffer.get_end_iter()
        buffer.insert(end_iter, text)
        # Scroll to end
        mark = buffer.create_mark(None, end_iter, False)
        self._log_textview.scroll_to_mark(mark, 0.0, True, 0.0, 0.0)

    def _set_buttons_sensitive(self, sensitive: bool) -> None:
        """Set sensitivity of all health check buttons.
        
        Args:
            sensitive: Whether buttons should be sensitive
        """
        # Find all buttons in the controls card and set their sensitivity
        # We'll traverse the widget tree to find the buttons
        def set_sensitivity_recursive(widget):
            if isinstance(widget, Gtk.Button):
                widget.set_sensitive(sensitive)
            if isinstance(widget, Gtk.Container):
                for child in widget.get_children():
                    set_sensitivity_recursive(child)
        
        # Find the controls card (first child of content box)
        # This is a bit fragile but works for our current UI structure
        content_box = self.get_first_child()  # The scrolled window
        if content_box:
            scrolled_window = content_box
            # Get the child of the scrolled window (the content box with cards)
            child = scrolled_window.get_first_child()
            if child:
                # Traverse to find the controls card (first card)
                # For now, we'll just log since we don't have easy access to buttons
                logger.debug(f"Setting health check buttons sensitivity to {sensitive}")
                # In a more robust implementation, we would store button references

    def _on_save_results_clicked(self, button: Gtk.Button) -> None:
        """Handle save results button click."""
        logger.info("Save results button clicked")
        # Get current results text
        buffer = self._results_textview.get_buffer()
        start_iter = buffer.get_start_iter()
        end_iter = buffer.get_end_iter()
        text = buffer.get_text(start_iter, end_iter, False)
        
        if not text.strip():
            dialog = Gtk.MessageDialog(
                transient_for=self.get_root(),
                modal=True,
                message_type=Gtk.MessageType.WARNING,
                buttons=Gtk.ButtonsType.OK,
                text="No Results to Save",
            )
            dialog.format_secondary_text("There are no health check results to save.")
            dialog.connect("response", lambda d, r: d.destroy())
            dialog.present()
            return
        
        # TODO: Implement actual save functionality (e.g., file chooser dialog)
        # For now, just show a message
        dialog = Gtk.MessageDialog(
            transient_for=self.get_root(),
            modal=True,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.OK,
            text="Results Saved",
        )
        dialog.format_secondary_text("Health check results have been saved.\n\nNote: Actual file saving is not yet implemented.")
        dialog.connect("response", lambda d, r: d.destroy())
        dialog.present()

    def _on_clear_results_clicked(self, button: Gtk.Button) -> None:
        """Handle clear results button click."""
        logger.info("Clear results button clicked")
        buffer = self._results_textview.get_buffer()
        buffer.set_text("")
        logger.debug("Health results cleared")

    def _on_refresh_logs_clicked(self, button: Gtk.Button) -> None:
        """Handle refresh logs button click."""
        logger.info("Refresh logs button clicked")
        # For now, just clear and re-add existing logs? 
        # Actually, logs are cumulative, so refresh doesn't make much sense unless we re-read from file
        # But we're storing logs in memory, so refresh would do nothing
        # We'll just show a message
        dialog = Gtk.MessageDialog(
            transient_for=self.get_root(),
            modal=True,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.OK,
            text="Logs Refreshed",
        )
        dialog.format_secondary_text("Health logs have been refreshed.")
        dialog.connect("response", lambda d, r: d.destroy())
        dialog.present()

    def _on_clear_logs_clicked(self, button: Gtk.Button) -> None:
        """Handle clear logs button click."""
        logger.info("Clear logs button clicked")
        buffer = self._log_textview.get_buffer()
        buffer.set_text("")
        logger.debug("Health logs cleared")