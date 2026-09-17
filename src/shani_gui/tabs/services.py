"""Services tab for the Shanios GUI."""

import logging
import subprocess
import threading
from typing import override

from gi.repository import Gtk  # type: ignore

from shani_gui.state import AppState
from shani_gui.auth import AuthManager


logger = logging.getLogger(__name__)


class ServicesTab(Gtk.Box):
    """Services tab for managing system services."""

    def __init__(
        self,
        state: AppState | None = None,
        auth_manager: AuthManager | None = None,
    ) -> None:
        """Initialize the services tab.
        
        Args:
            state: Application state object
            auth_manager: Authentication manager
        """
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self._state = state
        self._auth_manager = auth_manager
        self._services = []  # List to store service data
        self._refresh_thread = None

        self._setup_ui()
        logger.info("ServicesTab initialized")
        
        # Start initial service refresh
        self._refresh_services()

    def _setup_ui(self) -> None:
        """Set up the user interface for the services tab."""
        logger.debug("Setting up services tab UI")

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

        # Create search box
        search_box = self._create_search_box()
        content_box.append(search_box)

        # Create services list
        self._services_list = Gtk.ListBox()
        self._services_list.set_selection_mode(Gtk.SelectionMode.NONE)
        self._services_list.set_activate_on_single_click(False)
        content_box.append(self._services_list)

        # Create refresh button
        refresh_button = Gtk.Button()
        refresh_button.set_icon_name("view-refresh-symbolic")
        refresh_button.set_tooltip_text("Refresh services list")
        refresh_button.add_css_class("flat")
        refresh_button.connect("clicked", self._on_refresh_clicked)
        content_box.append(refresh_button)

        logger.debug("Services tab UI created")

    def _create_search_box(self) -> Gtk.Box:
        """Create the search box for filtering services.
        
        Returns:
            Search box widget
        """
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        box.set_margin_bottom(12)

        # Search icon
        search_icon = Gtk.Image.new_from_icon_name("system-search-symbolic")
        search_icon.set_pixel_size(16)
        box.append(search_icon)

        # Search entry
        self._search_entry = Gtk.Entry()
        self._search_entry.set_placeholder_text("Search services...")
        self._search_entry.set_hexpand(True)
        self._search_entry.connect("changed", self._on_search_changed)
        box.append(self._search_entry)

        return box

    def _on_refresh_clicked(self, button: Gtk.Button) -> None:
        """Handle refresh button click."""
        logger.info("Refresh button clicked")
        self._refresh_services()

    def _refresh_services(self) -> None:
        """Refresh the services list in a background thread."""
        # Cancel any existing refresh thread
        if self._refresh_thread and self._refresh_thread.is_alive():
            return
            
        # Start new refresh thread
        self._refresh_thread = threading.Thread(target=self._fetch_services_thread)
        self._refresh_thread.daemon = True
        self._refresh_thread.start()

    def _fetch_services_thread(self) -> None:
        """Fetch services information in a background thread."""
        try:
            # Get list of all services
            services_data = self._get_all_services()
            
            # Update UI on main thread
            Gtk.idle_add(self._update_services_list, services_data)
            
        except Exception as e:
            logger.error(f"Error fetching services: {e}")
            Gtk.idle_add(self._show_error, f"Failed to fetch services: {e}")

    def _get_all_services(self) -> list[dict]:
        """Get information about all system services.
        
        Returns:
            List of dictionaries containing service information
        """
        services = []
        
        try:
            # Get all service units
            result = subprocess.run(
                ['systemctl', 'list-units', '--type=service', '--all', '--no-legend', '--no-pager'],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode != 0:
                logger.error(f"Failed to list services: {result.stderr}")
                return services
                
            # Parse each line
            for line in result.stdout.strip().split('\n'):
                if not line.strip():
                    continue
                    
                # Parse line format: UNIT       LOAD   ACTIVE SUB     DESCRIPTION
                parts = line.split()
                if len(parts) < 4:
                    continue
                    
                service_id = parts[0]
                load_state = parts[1]
                active_state = parts[2]
                sub_state = parts[3]
                description = ' '.join(parts[4:]) if len(parts) > 4 else ""
                
                # Skip if not a service unit (should end with .service)
                if not service_id.endswith('.service'):
                    continue
                    
                # Get enabled state
                enabled_state = self._get_service_enabled_state(service_id)
                
                # Determine if service is active (running)
                is_active = active_state == "active" and sub_state == "running"
                
                services.append({
                    'id': service_id,
                    'description': description or service_id,
                    'is_active': is_active,
                    'state': f"{active_state}/{sub_state}",
                    'enabled': enabled_state,
                    'load': load_state,
                    'active': active_state,
                    'sub': sub_state
                })
                
        except Exception as e:
            logger.error(f"Error in _get_all_services: {e}")
            
        return services

    def _get_service_enabled_state(self, service_id: str) -> str:
        """Get whether a service is enabled.
        
        Args:
            service_id: The service ID to check
            
        Returns:
            Enabled state string (enabled, disabled, masked, etc.)
        """
        try:
            result = subprocess.run(
                ['systemctl', 'is-enabled', service_id],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if result.returncode == 0:
                return result.stdout.strip()
            else:
                # If command failed, check if it's masked
                result2 = subprocess.run(
                    ['systemctl', 'status', service_id],
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                if "masked" in result2.stdout:
                    return "masked"
                return "disabled"
                
        except Exception:
            return "unknown"

    def _update_services_list(self, services: list[dict]) -> None:
        """Update the services list with new data.
        
        Args:
            services: List of service dictionaries
        """
        logger.debug(f"Updating services list with {len(services)} services")
        
        # Store the services data
        self._services = services
        
        # Clear the current list
        self._services_list.remove_all()
        
        # Sort services: active first, then by name
        services.sort(key=lambda x: (not x['is_active'], x['id']))
        
        for service in services:
            row = self._create_service_row(
                service['id'],
                service['description'],
                service['is_active'],
                service['state']
            )
            # Store service ID for reference
            row.set_name(service['id'])
            # Store additional data for use in callbacks
            row.set_property('service-data', service)
            self._services_list.append(row)
            
        logger.debug("Services list updated")

    def _create_service_row(self, service_id: str, description: str, 
                            is_active: bool, state_text: str) -> Gtk.Box:
        """Create a service row for the services list.
        
        Args:
            service_id: Systemd service ID
            description: Service description
            is_active: Whether service is currently active
            state_text: Service state text (enabled/disabled/etc.)
            
        Returns:
            Service row widget
        """
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row.set_margin_start(6)
        row.set_margin_end(6)
        row.set_margin_top(4)
        row.set_margin_bottom(4)

        # Service status indicator
        status_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        status_indicator = Gtk.Label()
        status_indicator.set_text("●" if is_active else "○")
        # Use different colors for different states
        if is_active:
            status_indicator.add_css_class("service-active")
        else:
            status_indicator.add_css_class("service-inactive")
        status_box.append(status_indicator)

        status_label = Gtk.Label(label=description)
        status_label.set_halign(Gtk.Align.START)
        status_label.set_hexpand(True)
        status_box.append(status_label)

        row.append(status_box)

        # Action buttons box
        action_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        action_box.set_halign(Gtk.Align.END)

        # Toggle button
        toggle_btn = Gtk.ToggleButton()
        toggle_btn.set_active(is_active)
        toggle_btn.set_tooltip_text(f"{'Stop' if is_active else 'Start'} {service_id}")
        toggle_btn.connect("toggled", self._on_service_toggled, service_id)
        action_box.append(toggle_btn)

        # Settings button (for services that have configuration)
        settings_btn = Gtk.Button()
        settings_btn.set_icon_name("applications-system-symbolic")
        settings_btn.set_tooltip_text(f"Configure {service_id}")
        settings_btn.add_css_class("flat")
        settings_btn.connect("clicked", self._on_service_settings_clicked, service_id)
        action_box.append(settings_btn)

        row.append(action_box)

        # State label
        state_label = Gtk.Label(label=state_text)
        state_label.add_css_class("dim-label")
        state_label.set_halign(Gtk.Align.END)
        row.append(state_label)

        # Store service ID for reference
        row.set_name(service_id)

        return row

    def _on_search_changed(self, entry: Gtk.Entry) -> None:
        """Handle search entry changes.
        
        Args:
            entry: The search entry widget
        """
        search_text = entry.get_text().lower()
        logger.debug(f"Searching for: {search_text}")

        # Show/hide rows based on search text
        for row in self._services_list:
            if not isinstance(row, Gtk.Box):
                continue

            # Get service data from the row
            service_data = getattr(row, 'service-data', None)
            if not service_data:
                # Fallback to old method if service-data not available
                description_label = None
                for child in row:
                    if isinstance(child, Gtk.Box):
                        # Look inside the status box for the description label
                        for grandchild in child:
                            if isinstance(grandchild, Gtk.Box):
                                for great_grandchild in grandchild:
                                    if isinstance(great_grandchild, Gtk.Label) and not great_grandchild.get_name():
                                        description_label = great_grandchild
                                        break
                                if description_label:
                                    break
                        if description_label:
                            break

                if description_label:
                    description = description_label.get_text().lower()
                    service_id = row.get_name()
                    visible = (search_text in description) or (search_text in service_id.lower())
                    row.set_visible(visible)
                continue
                
            # Use stored service data
            description = service_data['description'].lower()
            service_id = service_data['id']
            visible = (search_text in description) or (search_text in service_id.lower())
            row.set_visible(visible)

    def _on_service_toggled(self, button: Gtk.ToggleButton, service_id: str) -> None:
        """Handle service toggle (start/stop).
        
        Args:
            button: The toggle button
            service_id: The service ID to toggle
        """
        is_active = button.get_active()
        action = "start" if is_active else "stop"
        logger.info(f"{action.capitalize()}ing service: {service_id}")
        button.set_tooltip_text(f"{'Stop' if is_active else 'Start'} {service_id}")
        
        # Disable button during operation to prevent rapid clicks
        button.set_sensitive(False)
        
        # Run the service control in a background thread
        thread = threading.Thread(target=self._control_service_thread, args=(service_id, action, button))
        thread.daemon = True
        thread.start()

    def _control_service_thread(self, service_id: str, action: str, button: Gtk.ToggleButton) -> None:
        """Control a service in a background thread.
        
        Args:
            service_id: The service ID to control
            action: The action to perform (start/stop)
            button: The toggle button to update
        """
        try:
            # Run the systemctl command
            result = subprocess.run(
                ['systemctl', action, service_id],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            # Update UI on main thread
            if result.returncode == 0:
                logger.info(f"Successfully {action}ed service {service_id}")
                Gtk.idle_add(self._service_control_success, service_id, action, button)
            else:
                logger.error(f"Failed to {action} service {service_id}: {result.stderr}")
                Gtk.idle_add(self._service_control_error, service_id, action, result.stderr, button)
                
        except Exception as e:
            logger.error(f"Error controlling service {service_id}: {e}")
            Gtk.idle_add(self._service_control_error, service_id, action, str(e), button)

    def _service_control_success(self, service_id: str, action: str, button: Gtk.ToggleButton) -> None:
        """Handle successful service control.
        
        Args:
            service_id: The service ID that was controlled
            action: The action that was performed (start/stop)
            button: The toggle button to update
        """
        # Re-enable button
        button.set_sensitive(True)
        
        # Update button state and tooltip
        is_now_active = (action == "start")
        button.set_active(is_now_active)
        button.set_tooltip_text(f"{'Stop' if is_now_active else 'Start'} {service_id}")
        
        # Show success message
        dialog = Gtk.MessageDialog(
            transient_for=self.get_root(),
            modal=True,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.OK,
            text=f"Service {action}",
        )
        dialog.format_secondary_text(f"Service {service_id} has been successfully {action}ed.")
        dialog.connect("response", lambda d, r: d.destroy())
        dialog.present()
        
        # Refresh services list to update status
        self._refresh_services()

    def _service_control_error(self, service_id: str, action: str, error_message: str, button: Gtk.ToggleButton) -> None:
        """Handle service control error.
        
        Args:
            service_id: The service ID that failed to control
            action: The action that was attempted (start/stop)
            error_message: The error message
            button: The toggle button to reset
        """
        # Re-enable button
        button.set_sensitive(True)
        
        # Reset button to previous state (opposite of what was attempted)
        was_trying_to_start = (action == "start")
        button.set_active(not was_trying_to_start)  # Reset to opposite state
        button.set_tooltip_text(f"{'Start' if was_trying_to_start else 'Stop'} {service_id}")
        
        # Show error message
        dialog = Gtk.MessageDialog(
            transient_for=self.get_root(),
            modal=True,
            message_type=Gtk.MessageType.ERROR,
            buttons=Gtk.ButtonsType.OK,
            text=f"Failed to {action} service",
        )
        dialog.format_secondary_text(f"Failed to {action} service {service_id}:\n{error_message}")
        dialog.connect("response", lambda d, r: d.destroy())
        dialog.present()

    def _on_service_settings_clicked(self, button: Gtk.Button, service_id: str) -> None:
        """Handle service settings button click.
        
        Args:
            button: The settings button
            service_id: The service ID to configure
        """
        logger.info(f"Opening settings for service: {service_id}")
        # For now, show a message that service-specific configuration is not implemented
        # In a real implementation, this would open a service-specific configuration dialog
        dialog = Gtk.MessageDialog(
            transient_for=self.get_root(),
            modal=True,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.OK,
            text=f"Service Settings - {service_id}",
        )
        dialog.format_secondary_text(
            f"Configuration interface for {service_id} is not yet implemented.\n"
            f"You can manage this service using the start/stop buttons above.\n"
            f"For advanced configuration, please use the command line:\n"
            f"  systemctl status {service_id}\n"
            f"  systemctl show {service_id}"
        )
        dialog.connect("response", lambda d, r: d.destroy())
        dialog.present()

    def _show_error(self, message: str) -> None:
        """Show an error message.
        
        Args:
            message: The error message to show
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