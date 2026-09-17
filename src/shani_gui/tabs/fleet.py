"""Fleet tab for the Shanios GUI."""

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


class FleetTab(Gtk.Box):
    """Fleet tab showing fleet management and enrollment status."""

    def __init__(
        self,
        state: AppState | None = None,
        auth_manager: AuthManager | None = None,
    ) -> None:
        """Initialize the fleet tab.
        
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
        logger.info("FleetTab initialized")
        
        # Start periodic updates
        self._start_periodic_updates()

    def _setup_ui(self) -> None:
        """Set up the user interface for the fleet tab."""
        logger.debug("Setting up fleet tab UI")

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

        # Create fleet status card
        status_card = self._create_fleet_status_card()
        content_box.append(status_card)

        # Create machine info card
        machine_card = self._create_machine_info_card()
        content_box.append(machine_card)

        # Create console output card
        console_card = self._create_console_output_card()
        content_box.append(console_card)

        # Create task status card
        task_card = self._create_task_status_card()
        content_box.append(task_card)

        # Create remote command execution card
        remote_command_card = self._create_remote_command_card()
        content_box.append(remote_command_card)

        logger.debug("Fleet tab UI created")

    def _create_fleet_status_card(self) -> Gtk.Box:
        """Create the fleet status card.
        
        Returns:
            Fleet status card widget
        """
        card = self._create_card("Fleet Status")

        # Create grid for status info
        grid = Gtk.Grid()
        grid.set_row_spacing(8)
        grid.set_column_spacing(16)
        grid.set_column_homogeneous(False)
        card.append(grid)

        # Add fleet status rows
        self._add_info_row(grid, 0, "Enrollment Status:", "Checking...", "fleet-enrollment")
        self._add_info_row(grid, 1, "Fleet URL:", "Checking...", "fleet-url")
        self._add_info_row(grid, 2, "Last Heartbeat:", "Never", "fleet-heartbeat")
        self._add_info_row(grid, 3, "API Key Status:", "Checking...", "fleet-api-key")

        # Add action buttons
        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        button_box.set_halign(Gtk.Align.END)
        enroll_btn = Gtk.Button(label="Enroll in Fleet")
        enroll_btn.add_css_class("suggested-action")
        enroll_btn.connect("clicked", self._on_enroll_clicked)
        button_box.append(enroll_btn)
        check_status_btn = Gtk.Button(label="Check Status")
        check_status_btn.connect("clicked", self._on_check_status_clicked)
        button_box.append(check_status_btn)
        card.append(button_box)

        return card

    def _create_machine_info_card(self) -> Gtk.Box:
        """Create the machine information card.
        
        Returns:
            Machine info card widget
        """
        card = self._create_card("Machine Information")

        # Create grid for machine info
        grid = Gtk.Grid()
        grid.set_row_spacing(8)
        grid.set_column_spacing(16)
        grid.set_column_homogeneous(False)
        card.append(grid)

        self._add_info_row(grid, 0, "Machine ID:", "Checking...", "machine-id")
        self._add_info_row(grid, 1, "Hostname:", "Checking...", "machine-hostname")
        self._add_info_row(grid, 2, "Platform:", "Checking...", "machine-platform")
        self._add_info_row(grid, 3, "Last Seen:", "Never", "machine-last-seen")
        self._add_info_row(grid, 4, "Tags:", "None", "machine-tags")

        return card

    def _create_console_output_card(self) -> Gtk.Box:
        """Create the console output card.
        
        Returns:
            Console output card widget
        """
        card = self._create_card("Fleet Console Output")

        # Create scrolled text view for console output
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)
        scrolled.set_size_request(-1, 200)
        card.append(scrolled)

        # Text view for console output
        self._console_textview = Gtk.TextView()
        self._console_textview.set_editable(False)
        self._console_textview.set_cursor_visible(False)
        self._console_textview.set_wrap_mode(Gtk.WrapMode.WORD)
        scrolled.set_child(self._console_textview)

        # Add action buttons
        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        button_box.set_halign(Gtk.Align.END)
        clear_btn = Gtk.Button(label="Clear")
        clear_btn.connect("clicked", self._on_clear_console_clicked)
        button_box.append(clear_btn)
        fetch_logs_btn = Gtk.Button(label="Fetch Logs")
        fetch_logs_btn.connect("clicked", self._on_fetch_logs_clicked)
        button_box.append(fetch_logs_btn)
        card.append(button_box)

        return card

    def _create_task_status_card(self) -> Gtk.Box:
        """Create the task status card.
        
        Returns:
            Task status card widget
        """
        card = self._create_card("Task Status")

        # Create grid for task info
        grid = Gtk.Grid()
        grid.set_row_spacing(8)
        grid.set_column_spacing(16)
        grid.set_column_homogeneous(False)
        card.append(grid)

        self._add_info_row(grid, 0, "Current Task:", "None", "task-current")
        self._add_info_row(grid, 1, "Task Status:", "Idle", "task-status")
        self._add_info_row(grid, 2, "Progress:", "0%", "task-progress")
        self._add_info_row(grid, 3, "Last Result:", "No tasks run", "task-last-result")

        # Add action buttons
        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        button_box.set_halign(Gtk.Align.END)
        run_health_btn = Gtk.Button(label="Run Health Check")
        run_health_btn.connect("clicked", self._on_run_health_clicked)
        button_box.append(run_health_btn)
        view_tasks_btn = Gtk.Button(label="View Task History")
        view_tasks_btn.connect("clicked", self._on_view_tasks_clicked)
        button_box.append(view_tasks_btn)
        card.append(button_box)

        return card

    def _create_remote_command_card(self) -> Gtk.Box:
        """Create the remote command execution card.
        
        Returns:
            Remote command card widget
        """
        card = self._create_card("Remote Command")

        # Create grid for command info
        grid = Gtk.Grid()
        grid.set_row_spacing(8)
        grid.set_column_spacing(16)
        grid.set_column_homogeneous(False)
        card.append(grid)

        # Gateway status indicator
        self._add_info_row(grid, 0, "Gateway Status:", "Disconnected", "gateway-status")
        self._add_info_row(grid, 1, "Last Command:", "None", "gateway-last-command")

        # Command input field
        self._gateway_input = Gtk.Entry()
        self._gateway_input.set_placeholder_text("Enter command to gateway...")
        self._gateway_input.set_margin_top(8)
        card.append(self._gateway_input)

        # Send button
        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        button_box.set_halign(Gtk.Align.END)
        send_btn = Gtk.Button(label="Send Command")
        send_btn.add_css_class("suggested-action")
        send_btn.connect("clicked", self._on_remote_command_send)
        button_box.append(send_btn)
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
        """Start periodic updates for fleet status."""
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
        """Update loop for fetching fleet status."""
        while not self._stop_updates:
            try:
                self._update_fleet_status()
                # Update every 30 seconds
                time.sleep(30)
            except Exception as e:
                logger.error(f"Error in fleet update loop: {e}")
                time.sleep(5)  # Shorter delay on error

    def _update_fleet_status(self) -> None:
        """Update fleet status information."""
        try:
            # Update enrollment status
            self._update_enrollment_status()
            
            # Update fleet URL
            self._update_fleet_url()
            
            # Update last heartbeat
            self._update_last_heartbeat()
            
            # Update API key status
            self._update_api_key_status()
            
            # Update machine info
            self._update_machine_info()
            
        except Exception as e:
            logger.error(f"Error updating fleet status: {e}")

    def _update_enrollment_status(self) -> None:
        """Update enrollment status display."""
        try:
            # Check if machine is enrolled
            enrolled_file = "/var/lib/shani-fleet/machine_id"
            if os.path.exists(enrolled_file):
                with open(enrolled_file, 'r') as f:
                    machine_id = f.read().strip()
                if machine_id:
                    status_text = f"Enrolled ({machine_id[:8]}...)"
                else:
                    status_text = "Enrolled (ID not available)"
            else:
                status_text = "Not Enrolled"
                
            # Update UI on main thread
            Gtk.idle_add(self._update_label_text, "fleet-enrollment", status_text)
            
        except Exception as e:
            logger.error(f"Error updating enrollment status: {e}")
            Gtk.idle_add(self._update_label_text, "fleet-enrollment", "Error")

    def _update_fleet_url(self) -> None:
        """Update fleet URL display."""
        try:
            config_file = "/etc/shani-fleet.conf"
            fleet_url = "Not configured"
            if os.path.exists(config_file):
                with open(config_file, 'r') as f:
                    for line in f:
                        if line.startswith("FLEET_URL="):
                            fleet_url = line.split("=", 1)[1].strip().strip('"')
                            break
            Gtk.idle_add(self._update_label_text, "fleet-url", fleet_url)
        except Exception as e:
            logger.error(f"Error updating fleet URL: {e}")
            Gtk.idle_add(self._update_label_text, "fleet-url", "Error")

    def _update_last_heartbeat(self) -> None:
        """Update last heartbeat display."""
        try:
            heartbeat_file = "/var/lib/shani-fleet/last_heartbeat_ok"
            if os.path.exists(heartbeat_file):
                with open(heartbeat_file, 'r') as f:
                    timestamp_str = f.read().strip()
                if timestamp_str:
                    try:
                        timestamp = int(timestamp_str)
                        current_time = int(time.time())
                        diff = current_time - timestamp
                        if diff < 60:
                            status_text = f"{diff}s ago"
                        elif diff < 3600:
                            status_text = f"{diff // 60}m ago"
                        else:
                            status_text = f"{diff // 3600}h ago"
                    except ValueError:
                        status_text = timestamp_str
                else:
                    status_text = "Never"
            else:
                status_text = "Never"
                
            Gtk.idle_add(self._update_label_text, "fleet-heartbeat", status_text)
        except Exception as e:
            logger.error(f"Error updating last heartbeat: {e}")
            Gtk.idle_add(self._update_label_text, "fleet-heartbeat", "Error")

    def _update_api_key_status(self) -> None:
        """Update API key status display."""
        try:
            key_file = "/var/lib/shani-fleet/fleet.key"
            if os.path.exists(key_file):
                with open(key_file, 'r') as f:
                    key_content = f.read().strip()
                if key_content:
                    status_text = f"Configured ({len(key_content)} chars)"
                else:
                    status_text = "Empty key file"
            else:
                status_text = "Not configured"
                
            Gtk.idle_add(self._update_label_text, "fleet-api-key", status_text)
        except Exception as e:
            logger.error(f"Error updating API key status: {e}")
            Gtk.idle_add(self._update_label_text, "fleet-api-key", "Error")

    def _update_machine_info(self) -> None:
        """Update machine information display."""
        try:
            # Machine ID
            machine_id_file = "/var/lib/shani-fleet/machine_id"
            if os.path.exists(machine_id_file):
                with open(machine_id_file, 'r') as f:
                    machine_id = f.read().strip()
                machine_id_display = machine_id if machine_id else "None"
                Gtk.idle_add(self._update_label_text, "machine-id", machine_id_display)
            else:
                Gtk.idle_add(self._update_label_text, "machine-id", "None")

            # Hostname
            hostname = subprocess.check_output(['hostname'], text=True).strip()
            Gtk.idle_add(self._update_label_text, "machine-hostname", hostname)

            # Platform
            platform = subprocess.check_output(['uname', '-m'], text=True).strip()
            Gtk.idle_add(self._update_label_text, "machine-platform", platform)

            # Last seen (same as last heartbeat for now)
            self._update_last_heartbeat()  # This will update machine-last-seen too

            # Tags (placeholder for now)
            Gtk.idle_add(self._update_label_text, "machine-tags", "None")
            
        except Exception as e:
            logger.error(f"Error updating machine info: {e}")

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
    def _on_enroll_clicked(self, button: Gtk.Button) -> None:
        """Handle enroll button click."""
        logger.info("Enroll button clicked")
        dialog = Gtk.MessageDialog(
            transient_for=self.get_root(),
            modal=True,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.OK_CANCEL,
            text="Enroll in Fleet",
        )
        dialog.format_secondary_text(
            "This will enroll this machine in the Shanios fleet.\n"
            "You will need to provide an enrollment token from the Shanios platform.\n"
            "Continue?"
        )
        def on_response(dialog: Gtk.MessageDialog, response: int) -> None:
            if response == Gtk.ResponseType.OK:
                logger.info("User confirmed fleet enrollment")
                # Show enrollment dialog
                self._show_enrollment_dialog()
            dialog.destroy()
        dialog.connect("response", on_response)
        dialog.present()

    def _show_enrollment_dialog(self) -> None:
        """Show enrollment dialog to get token from user."""
        dialog = Gtk.MessageDialog(
            transient_for=self.get_root(),
            modal=True,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.OK_CANCEL,
            text="Fleet Enrollment",
        )
        dialog.format_secondary_text(
            "Please enter your enrollment token from the Shanios platform:\n"
            "(This token is typically provided by your system administrator)"
        )
        
        # Add entry for token
        entry = Gtk.Entry()
        entry.set_placeholder_text("Enter enrollment token")
        entry.set_visibility(False)  # Hide token for security
        dialog.get_content_area().append(entry)
        entry.show()
        
        def on_response(dialog: Gtk.MessageDialog, response: int) -> None:
            if response == Gtk.ResponseType.OK:
                token = entry.get_text().strip()
                if token:
                    logger.info("User provided enrollment token")
                    # Run enrollment in background thread
                    thread = threading.Thread(target=self._enroll_thread, args=(token,))
                    thread.daemon = True
                    thread.start()
                else:
                    # Show error if no token provided
                    error_dialog = Gtk.MessageDialog(
                        transient_for=self.get_root(),
                        modal=True,
                        message_type=Gtk.MessageType.ERROR,
                        buttons=Gtk.ButtonsType.OK,
                        text="Enrollment Failed",
                    )
                    error_dialog.format_secondary_text("Please provide an enrollment token.")
                    error_dialog.connect("response", lambda d, r: d.destroy())
                    error_dialog.present()
            dialog.destroy()
        dialog.connect("response", on_response)
        dialog.present()

    def _enroll_thread(self, token: str) -> None:
        """Run enrollment in a background thread.
        
        Args:
            token: Enrollment token
        """
        try:
            logger.info("Starting fleet enrollment process")
            
            # Update UI to show enrollment in progress
            Gtk.idle_add(self._update_label_text, "fleet-enrollment", "Enrolling...")
            
            # Run the enrollment command
            result = subprocess.run(
                ['shani-fleet-agent', 'enroll'],
                input=token + '\n',
                capture_output=True,
                text=True,
                timeout=30
            )
            
            # Update UI on main thread
            if result.returncode == 0:
                logger.info("Fleet enrollment successful")
                Gtk.idle_add(self._enrollment_success)
            else:
                logger.error(f"Fleet enrollment failed: {result.stderr}")
                Gtk.idle_add(self._enrollment_failure, result.stderr)
                
        except subprocess.TimeoutExpired:
            logger.error("Fleet enrollment timed out")
            Gtk.idle_add(self._enrollment_failure, "Enrollment timed out")
        except Exception as e:
            logger.error(f"Error during fleet enrollment: {e}")
            Gtk.idle_add(self._enrollment_failure, str(e))

    def _enrollment_success(self) -> None:
        """Handle successful enrollment."""
        self._update_label_text("fleet-enrollment", "Enrolled")
        dialog = Gtk.MessageDialog(
            transient_for=self.get_root(),
            modal=True,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.OK,
            text="Enrollment Successful",
        )
        dialog.format_secondary_text(
            "This machine has been successfully enrolled in the Shanios fleet.\n"
            "Heartbeats and task execution will now occur automatically."
        )
        dialog.connect("response", lambda d, r: d.destroy())
        dialog.present()

    def _enrollment_failure(self, error_message: str) -> None:
        """Handle enrollment failure.
        
        Args:
            error_message: Error message to display
        """
        self._update_label_text("fleet-enrollment", "Enrollment Failed")
        dialog = Gtk.MessageDialog(
            transient_for=self.get_root(),
            modal=True,
            message_type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.OK,
            text="Enrollment Failed",
        )
        dialog.format_secondary_text(f"Fleet enrollment failed:\n{error_message}")
        dialog.connect("response", lambda d, r: d.destroy())
        dialog.present()

    def _on_check_status_clicked(self, button: Gtk.Button) -> None:
        """Handle check status button click."""
        logger.info("Check status button clicked")
        # Run status check in background thread
        thread = threading.Thread(target=self._status_check_thread)
        thread.daemon = True
        thread.start()

    def _status_check_thread(self) -> None:
        """Run status check in a background thread."""
        try:
            # Run the status command
            result = subprocess.run(
                ['shani-fleet-agent', 'status'],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            # Update UI on main thread
            if result.returncode == 0:
                logger.info("Fleet status check completed")
                Gtk.idle_add(self._show_status_dialog, result.stdout)
            else:
                logger.error(f"Fleet status check failed: {result.stderr}")
                Gtk.idle_add(self._show_error_dialog, f"Status check failed:\n{result.stderr}")
                
        except Exception as e:
            logger.error(f"Error during fleet status check: {e}")
            Gtk.idle_add(self._show_error_dialog, f"Error during status check:\n{str(e)}")

    def _show_status_dialog(self, status_output: str) -> None:
        """Show fleet status in a dialog.
        
        Args:
            status_output: Output from shani-fleet-agent status
        """
        dialog = Gtk.MessageDialog(
            transient_for=self.get_root(),
            modal=True,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.OK,
            text="Fleet Status",
        )
        dialog.format_secondary_text(status_output)
        dialog.connect("response", lambda d, r: d.destroy())
        dialog.present()

    def _show_error_dialog(self, message: str) -> None:
        """Show an error message dialog.
        
        Args:
            message: Error message to show
        """
        dialog = Gtk.MessageDialog(
            transient_for=self.get_root(),
            modal=True,
            message_type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.OK,
            text="Error",
        )
        dialog.format_secondary_text(message)
        dialog.connect("response", lambda d, r: d.destroy())
        dialog.present()

    def _on_clear_console_clicked(self, button: Gtk.Button) -> None:
        """Handle clear console button click."""
        logger.info("Clear console button clicked")
        buffer = self._console_textview.get_buffer()
        buffer.set_text("")
        logger.debug("Console output cleared")

    def _on_fetch_logs_clicked(self, button: Gtk.Button) -> None:
        """Handle fetch logs button click."""
        logger.info("Fetch logs button clicked")
        # Fetch logs in background thread
        thread = threading.Thread(target=self._fetch_logs_thread)
        thread.daemon = True
        thread.start()

    def _fetch_logs_thread(self) -> None:
        """Fetch fleet logs in a background thread."""
        try:
            log_file = "/var/log/shanios-fleet.log"
            if os.path.exists(log_file):
                with open(log_file, 'r') as f:
                    # Get last 50 lines
                    lines = f.readlines()
                    last_lines = ''.join(lines[-50:]) if len(lines) > 50 else ''.join(lines)
                log_text = last_lines if last_lines else "No log entries found."
            else:
                log_text = "Log file not found."
                
            # Update UI on main thread
            Gtk.idle_add(self._update_console_text, log_text)
            
        except Exception as e:
            logger.error(f"Error fetching fleet logs: {e}")
            Gtk.idle_add(self._update_console_text, f"Error fetching logs: {str(e)}")

    def _update_console_text(self, text: str) -> None:
        """Update the console text view.
        
        Args:
            text: Text to display in the console view
        """
        buffer = self._console_textview.get_buffer()
        buffer.set_text(text)
        # Scroll to end
        iter = buffer.get_end_iter()
        self._console_textview.scroll_to_iter(iter, 0.0, False, 0.0, 0.0)

    def _on_run_health_clicked(self, button: Gtk.Button) -> None:
        """Handle run health check button click."""
        logger.info("Run health check button clicked")
        # Run health check in background thread
        thread = threading.Thread(target=self._run_health_check_thread)
        thread.daemon = True
        thread.start()

    def _run_health_check_thread(self) -> None:
        """Run health check in a background thread."""
        try:
            # Run the healthcheck command
            result = subprocess.run(
                ['shani-fleet-agent', 'healthcheck'],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            # Update UI on main thread
            if result.returncode == 0:
                logger.info("Fleet health check completed successfully")
                Gtk.idle_add(self._show_health_check_dialog, result.stdout, True)
            else:
                logger.warning(f"Fleet health check completed with issues: {result.stderr}")
                output = result.stdout
                if result.stderr:
                    output += f"\n\nErrors:\n{result.stderr}"
                Gtk.idle_add(self._show_health_check_dialog, output, False)
                
        except Exception as e:
            logger.error(f"Error during fleet health check: {e}")
            Gtk.idle_add(self._show_error_dialog, f"Error during health check:\n{str(e)}")

    def _show_health_check_dialog(self, output: str, success: bool) -> None:
        """Show fleet health check results in a dialog.
        
        Args:
            output: Output from shani-fleet-agent healthcheck
            success: Whether the health check was successful
        """
        dialog_type = Gtk.MessageType.INFO if success else Gtk.MessageType.WARNING
        dialog = Gtk.MessageDialog(
            transient_for=self.get_root(),
            modal=True,
            message_type=dialog_type,
            buttons=Gtk.ButtonsType.OK,
            text="Fleet Health Check",
        )
        dialog.format_secondary_text(output)
        dialog.connect("response", lambda d, r: d.destroy())
        dialog.present()

    def _on_view_tasks_clicked(self, button: Gtk.Button) -> None:
        """Handle view task history button click."""
        logger.info("View task history button clicked")
        # For now, show a placeholder dialog
        dialog = Gtk.MessageDialog(
            transient_for=self.get_root(),
            modal=True,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.OK,
            text="Task History",
        )
        dialog.format_secondary_text(
            "Task history viewing is not yet implemented.\n"
            "In the future, this will show a history of tasks executed via the fleet."
        )
        dialog.connect("response", lambda d, r: d.destroy())
        dialog.present()

    def _on_remote_command_send(self, button: Gtk.Button) -> None:
        """Handle remote command send button click."""
        command = self._gateway_input.get_text().strip()
        if not command:
            logger.warning("No command entered for gateway")
            return

        logger.info(f"Sending remote command to gateway: {command}")

        # Update UI immediately
        self._update_label_text("gateway-last-command", command[:50])

        # Run command in background thread
        thread = threading.Thread(target=self._send_gateway_command_thread, args=(command,))
        thread.daemon = True
        thread.start()

    def _send_gateway_command_thread(self, command: str) -> None:
        """Send gateway command in a background thread."""
        try:
            # Use CLI wrapper to send command
            result = self._cli_wrapper.gateway_send_command(command)

            # Update UI on main thread
            if result.get("status") == "success":
                logger.info(f"Gateway command executed successfully: {command}")
                Gtk.idle_add(self._update_label_text, "gateway-status", "Connected")
                Gtk.idle_add(self._show_command_result, command, result)
            else:
                logger.error(f"Gateway command failed: {result.get('error', 'Unknown error')}")
                Gtk.idle_add(self._update_label_text, "gateway-status", "Error")
                Gtk.idle_add(self._show_command_result, command, result, False)

        except Exception as e:
            logger.error(f"Error sending gateway command: {e}")
            Gtk.idle_add(self._update_label_text, "gateway-status", "Error")
            Gtk.idle_add(self._show_error_dialog, f"Error sending command:\n{str(e)}")

    def _show_command_result(self, command: str, result: dict, success: bool = True) -> None:
        """Show command result in a dialog.

        Args:
            command: The command that was executed
            result: Result dictionary from gateway
            success: Whether the command was successful
        """
        dialog_type = Gtk.MessageType.INFO if success else Gtk.MessageType.ERROR
        dialog = Gtk.MessageDialog(
            transient_for=self.get_root(),
            modal=True,
            message_type=dialog_type,
            buttons=Gtk.ButtonsType.OK,
            text="Gateway Command Result",
        )
        dialog.format_secondary_text(f"Command: {command}\n\nResult: {result}")
        dialog.connect("response", lambda d, r: d.destroy())
        dialog.present()