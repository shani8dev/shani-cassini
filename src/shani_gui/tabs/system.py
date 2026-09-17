"""System tab for the Shanios GUI."""

import logging
import json
import os
import platform
import subprocess
from typing import override

from gi.repository import Gtk  # type: ignore

from shani_gui.state import AppState
from shani_gui.auth import AuthManager
from shani_gui.api_client import APIClient
from shani_gui.cli_wrapper import get_cli_wrapper


logger = logging.getLogger(__name__)


class SystemTab(Gtk.Box):
    """System tab showing detailed system information."""

    def __init__(
        self,
        state: AppState | None = None,
        auth_manager: AuthManager | None = None,
    ) -> None:
        """Initialize the system tab.
        
        Args:
            state: Application state object
            auth_manager: Authentication manager
        """
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self._state = state
        self._auth_manager = auth_manager
        self._api_client = APIClient(auth_manager) if auth_manager else None
        self._cli_wrapper = get_cli_wrapper()

        self._setup_ui()
        logger.info("SystemTab initialized")

    def _setup_ui(self) -> None:
        """Set up the user interface for the system tab."""
        logger.debug("Setting up system tab UI")

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

        # Create hardware info card
        hardware_card = self._create_hardware_info_card()
        content_box.append(hardware_card)

        # Create storage info card
        storage_card = self._create_storage_info_card()
        content_box.append(storage_card)

        # Create boot & slots card
        boot_card = self._create_boot_slots_card()
        content_box.append(boot_card)

        # Create system services card
        services_card = self._create_system_services_card()
        content_box.append(services_card)

        logger.debug("System tab UI created")
        
        # Fetch and display initial data
        self._update_data()

    def _update_data(self) -> None:
        """Fetch real data and update the UI elements."""
        logger.debug("Fetching real data for system tab")
        
        # Fetch hardware information
        self._fetch_hardware_info()
        
        # Fetch storage information
        self._fetch_storage_info()
        
        # Fetch boot and slaves information
        self._fetch_boot_slots_info()
        
        # Fetch system services information
        self._fetch_system_services_info()

    def _fetch_hardware_info(self) -> None:
        """Fetch hardware information and update the UI."""
        try:
            # Get CPU information
            with open('/proc/cpuinfo', 'r') as f:
                cpu_info = f.read()
                # Extract model name
                model_line = [line for line in cpu_info.split('\n') if 'model name' in line]
                if model_line:
                    cpu_model = model_line[0].split(':')[1].strip()
                else:
                    cpu_model = "Unknown"
                
                # Count processors
                processor_lines = [line for line in cpu_info.split('\n') if line.startswith('processor')]
                cpu_count = len(processor_lines)
                
                cpu_text = f"{cpu_model} ({cpu_count} threads)"
                self._update_label("hw-cpu", cpu_text)
            
            # Get CPU temperature
            try:
                with open('/sys/class/thermal/thermal_zone0/temp', 'r') as f:
                    temp_temp = int(f.read().strip()) / 1000
                    cpu_temp_text = f"{temp_temp:.0f}°C"
                    self._update_label("hw-cpu-temp", cpu_temp_text)
            except:
                self._update_label("hw-cpu-temp", "N/A")
            
            # Get GPU information
            try:
                gpu_output = subprocess.check_output(['lspci'], text=True)
                gpu_lines = [line for line in gpu_output.split('\n') if 'VGA' in line or '3D' in line]
                if gpu_lines:
                    gpu_info = gpu_lines[0].split(':')[2].strip()
                else:
                    gpu_info = "Unknown"
                self._update_label("hw-gpu", gpu_info)
            except:
                self._update_label("hw-gpu", "Unknown")
            
            # Get RAM information
            with open('/proc/meminfo', 'r') as f:
                mem_info = f.read()
                mem_lines = mem_info.split('\n')
                mem_total = int([line for line in mem_lines if 'MemTotal' in line][0].split()[1]) // 1024  # MB
                mem_available = int([line for line in mem_lines if 'MemAvailable' in line][0].split()[1]) // 1024  # MB
                mem_used = mem_total - mem_available
                ram_text = f"{mem_total} MB ({mem_used} MB used)"
                self._update_label("hw-ram", ram_text)
            
            # Get battery information (if available)
            try:
                with open('/sys/class/power_supply/BAT0/capacity', 'r') as f:
                    battery_percent = f.read().strip()
                with open('/sys/class/power_supply/BAT0/status', 'r') as f:
                    battery_status = f.read().strip()
                battery_text = f"{battery_percent}% ({battery_status})"
                self._update_label("hw-battery", battery_text)
            except:
                self._update_label("hw-battery", "N/A")
            
            # Get virtualization information
            try:
                with open('/proc/cpuinfo', 'r') as f:
                    cpuinfo = f.read()
                    if 'vmx' in cpuinfo or 'svm' in cpuinfo:
                        virt_text = "VT-x/AMD-V available"
                    else:
                        virt_text = "VT-x/AMD-V not available"
                self._update_label("hw-virt", virt_text)
            except:
                self._update_label("hw-virt", "Unknown")
            
            # Get Bluetooth status
            try:
                result = subprocess.run(['bluetoothctl', 'show'], capture_output=True, text=True, timeout=5)
                if 'Powered: yes' in result.stdout:
                    self._update_label("hw-bluetooth", "● Active")
                else:
                    self._update_label("hw-bluetooth", "○ Inactive")
            except:
                self._update_label("hw-bluetooth", "○ Inactive")
                
        except Exception as e:
            logger.error(f"Failed to fetch hardware information: {e}")

    def _fetch_storage_info(self) -> None:
        """Fetch storage information and update the UI."""
        try:
            # Get root filesystem information
            result = subprocess.run(['df', '-h', '/'], capture_output=True, text=True)
            if result.returncode == 0:
                lines = result.stdout.strip().split('\n')
                if len(lines) >= 2:
                    parts = lines[1].split()
                    if len(parts) >= 6:
                        size = parts[1]
                        used = parts[2]
                        avail = parts[3]
                        self._update_label("storage-root-usage", f"{used}/{size}")
            
            # Get /home filesystem information (if separate)
            try:
                result = subprocess.run(['df', '-h', '/home'], capture_output=True, text=True)
                if result.returncode == 0:
                    lines = result.stdout.strip().split('\n')
                    if len(lines) >= 2:
                        parts = lines[1].split()
                        if len(parts) >= 6:
                            size = parts[1]
                            used = parts[2]
                            avail = parts[3]
                            self._update_label("storage-home-usage", f"{used}/{size}")
            except:
                self._update_label("storage-home-usage", "N/A")
            
            # Get /var filesystem information (if separate)
            try:
                result = subprocess.run(['df', '-h', '/var'], capture_output=True, text=True)
                if result.returncode == 0:
                    lines = result.stdout.strip().split('\n')
                    if len(lines) >= 2:
                        parts = lines[1].split()
                        if len(parts) >= 6:
                            size = parts[1]
                            used = parts[2]
                            avail = parts[3]
                            self._update_label("storage-var-usage", f"{used}/{size}")
            except:
                self._update_label("storage-var-usage", "N/A")
            
            # Get /var/log size
            try:
                result = subprocess.run(['du', '-sh', '/var/log'], capture_output=True, text=True)
                if result.returncode == 0:
                    size = result.stdout.split()[0]
                    self._update_label("storage-varlog", size)
            except:
                self._update_label("storage-varlog", "N/A")
            
            # Get swap information
            try:
                result = subprocess.run(['free', '-h'], capture_output=True, text=True)
                if result.returncode == 0:
                    lines = result.stdout.strip().split('\n')
                    for line in lines:
                        if line.startswith('Swap'):
                            parts = line.split()
                            if len(parts) >= 4:
                                self._update_label("storage-swap", f"{parts[2]} used / {parts[1]} total")
                                break
            except:
                self._update_label("storage-swap", "N/A")
                
        except Exception as e:
            logger.error(f"Failed to fetch storage information: {e}")

    def _fetch_boot_slots_info(self) -> None:
        """Fetch boot and slots information and update the UI."""
        try:
            # Use shani-deploy to get boot slot information
            result = self._cli_wrapper.run_shani_deploy(['--status', '--json'])
            if result and isinstance(result, dict):
                # Extract slot information from the result
                current_slot = result.get('current_slot', '@blue')
                expected_slot = result.get('expected_slot', '@blue')
                candidate_slot = result.get('candidate_slot', '@green')
                uki_status = result.get('uki_status', '● Valid Signatures')
                boot_entries = result.get('boot_entries', '2 valid (1 fallback)')
                
                self._update_label("boot-current", current_slot)
                self._update_label("boot-expected", expected_slot)
                self._update_label("boot-candidate", candidate_slot)
                self._update_label("boot-uki", uki_status)
                self._update_label("boot-entries", boot_entries)
            else:
                # Fallback to getting slot information from /boot or other sources
                # For now, we'll use default values
                logger.warning("Failed to get slot information from shani-deploy, using defaults")
        except Exception as e:
            logger.error(f"Failed to fetch boot and slots information: {e}")

    def _fetch_system_services_info(self) -> None:
        """Fetch system services information and update the UI."""
        try:
            # Get list of services and their status
            result = subprocess.run(['systemctl', 'list-units', '--type=service', '--state=running', '--no-legend'], 
                                  capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                # Parse the output to get service information
                # For simplicity, we'll just update a few key services
                services = [
                    ("sshd.service", "SSH Daemon"),
                    ("NetworkManager.service", "Network Manager"),
                    ("firewalld.service", "Firewall"),
                    ("systemd-resolved.service", "System DNS Resolver"),
                    ("docker.service", "Docker"),
                    ("udisks2.service", "UDISKS2"),
                    ("fail2ban.service", "Fail2Ban"),
                    ("polkit.service", "PolicyKit"),
                    ("shani-health.timer", "Shani Health Timer"),
                    ("shani-update.timer", "Shani Update Timer"),
                    ("shani-fleet.timer", "Shani Fleet Timer"),
                    ("bees.service", "Btrfs Equalization Daemon"),
                ]
                
                # Get the status of each service
                service_statuses = {}
                for line in result.stdout.strip().split('\n'):
                    if line:
                        parts = line.split()
                        if len(parts) >= 4:
                            service_name = parts[0]
                            service_status = parts[2]  # active, inactive, etc.
                            service_statuses[service_name] = service_status
                
                # Update the service items
                flow_box = self.get_root().get_descendant_by_name("services-flow-box")
                if flow_box and isinstance(flow_box, Gtk.FlowBox):
                    for child in flow_box.get_children():
                        if isinstance(child, Gtk.Box):
                            # Find the service ID label and status indicator in this box
                            service_id_label = None
                            status_indicator = None
                            for grandchild in child.get_children():
                                if isinstance(grandchild, Gtk.Label):
                                    name = grandchild.get_name()
                                    if name and name.startswith("service-id-"):
                                        service_id_label = grandchild
                                    elif name and name.startswith("service-status-"):
                                        status_indicator = grandchild
                            
                            if service_id_label and status_indicator:
                                # Extract service ID from the label name
                                # The name is in the format "service-id-{service_id}"
                                service_id_with_dashes = service_id_label.get_name().replace("service-id-", "")
                                service_id = service_id_with_dashes.replace("-", ".")
                                
                                # Update the status indicator
                                if service_id in service_statuses:
                                    status = service_statuses[service_id]
                                    is_active = status == "active"
                                    status_indicator.set_text("●" if is_active else "○")
                                    status_indicator.remove_css_class("service-active")
                                    status_indicator.remove_css_class("service-inactive")
                                    if is_active:
                                        status_indicator.add_css_class("service-active")
                                    else:
                                        status_indicator.add_css_class("service-inactive")
                                else:
                                    # Service not found in the list, assume inactive
                                    status_indicator.set_text("○")
                                    status_indicator.remove_css_class("service-active")
                                    status_indicator.remove_css_class("service-inactive")
                                    status_indicator.add_css_class("service-inactive")
                else:
                    logger.warning("Could not find services flow box")
            else:
                logger.warning("Failed to get system services information")
        except Exception as e:
            logger.error(f"Failed to fetch system services information: {e}")

    def _update_label(self, widget_name: str, text: str) -> None:
        """Update a label widget by its name.
        
        Args:
            widget_name: The name of the widget to update
            text: The new text for the widget
        """
        # Find the widget by name in the entire widget tree
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

    def _create_hardware_info_card(self) -> Gtk.Box:
        """Create the hardware information card.
        
        Returns:
            Hardware info card widget
        """
        card = self._create_card("Hardware Information")

        # Create grid for hardware info
        grid = Gtk.Grid()
        grid.set_row_spacing(8)
        grid.set_column_spacing(16)
        grid.set_column_homogeneous(False)
        card.append(grid)

        # Add hardware info rows
        self._add_info_row(grid, 0, "CPU:", "", "hw-cpu")
        self._add_info_row(grid, 1, "CPU Temperature:", "", "hw-cpu-temp")
        self._add_info_row(grid, 2, "GPU:", "", "hw-gpu")
        self._add_info_row(grid, 3, "RAM:", "", "hw-ram")
        self._add_info_row(grid, 4, "Battery:", "", "hw-battery")
        self._add_info_row(grid, 5, "Virtualization:", "", "hw-virt")
        self._add_info_row(grid, 6, "Bluetooth:", "", "hw-bluetooth")

        return card

    def _create_storage_info_card(self) -> Gtk.Box:
        """Create the storage information card.
        
        Returns:
            Storage info card widget
        """
        card = self._create_card("Storage Information")

        # Create grid for storage info
        grid = Gtk.Grid()
        grid.set_row_spacing(8)
        grid.set_column_spacing(16)
        grid.set_column_homogeneous(False)
        card.append(grid)

        # Add storage info rows
        self._add_info_row(grid, 0, "Root Filesystem:", "", "storage-root")
        self._add_info_row(grid, 1, "Used/Available:", "", "storage-root-usage")
        self._add_info_row(grid, 2, "/home:", "", "storage-home")
        self._add_info_row(grid, 3, "Used/Available:", "", "storage-home-usage")
        self._add_info_row(grid, 4, "/var:", "", "storage-var")
        self._add_info_row(grid, 5, "Used/Available:", "", "storage-var-usage")
        self._add_info_row(grid, 6, "/var/log:", "", "storage-varlog")
        self._add_info_row(grid, 7, "Swap:", "", "storage-swap")

        return card

    def _create_boot_slots_card(self) -> Gtk.Box:
        """Create the boot and slots information card.
        
        Returns:
            Boot and slots card widget
        """
        card = self._create_card("Boot & Slots")

        # Create grid for boot info
        grid = Gtk.Grid()
        grid.set_row_spacing(8)
        grid.set_column_spacing(16)
        grid.set_column_homogeneous(False)
        card.append(grid)

        # Add boot info rows
        self._add_info_row(grid, 0, "Booted Slot:", "", "boot-current")
        self._add_info_row(grid, 1, "Expected Slot:", "", "boot-expected")
        self._add_info_row(grid, 2, "Candidate Slot:", "", "boot-candidate")
        self._add_info_row(grid, 3, "UKI Status:", "", "boot-uki")
        self._add_info_row(grid, 4, "Boot Entries:", "", "boot-entries")
        self._add_info_row(grid, 5, "Slot Marker:", "", "boot-marker")

        return card

    def _create_system_services_card(self) -> Gtk.Box:
        """Create the system services card.
        
        Returns:
            System services card widget
        """
        card = self._create_card("System Services")

        # Create flow box for services
        flow_box = Gtk.FlowBox()
        flow_box.set_valign(Gtk.Align.START)
        flow_box.set_max_children_per_line(3)
        flow_box.set_selection_mode(Gtk.SelectionMode.NONE)
        flow_box.set_name("services-flow-box")  # Set name for updating
        card.append(flow_box)

        # Add service status indicators
        services = [
            ("sshd.service", "SSH Daemon", True),
            ("NetworkManager.service", "Network Manager", True),
            ("firewalld.service", "Firewall", True),
            ("systemd-resolved.service", "System DNS Resolver", True),
            ("docker.service", "Docker", False),
            ("udisks2.service", "UDISKS2", True),
            ("fail2ban.service", "Fail2Ban", True),
            ("polkit.service", "PolicyKit", True),
            ("shani-health.timer", "Shani Health Timer", True),
            ("shani-update.timer", "Shani Update Timer", True),
            ("shani-fleet.timer", "Shani Fleet Timer", True),
            ("bees.service", "Btrfs Equalization Daemon", True),
        ]

        for service_id, description, is_active in services:
            box = self._create_service_item(service_id, description, is_active)
            flow_box.append(box)

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

    def _create_service_item(self, service_id: str, description: str, is_active: bool) -> Gtk.Box:
        """Create a service status indicator item.
        
        Args:
            service_id: Systemd service ID
            description: Human-readable description
            is_active: Whether service is active
            
        Returns:
            Service item box
        """
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        box.set_margin_start(8)
        box.set_margin_end(8)
        box.set_margin_top(4)
        box.set_margin_bottom(4)

        # Service status indicator
        status_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        status_indicator = Gtk.Label()
        status_indicator.set_name(f"service-status-{service_id.replace('.', '-')}")  # Set name for updating
        status_indicator.set_text("●" if is_active else "○")
        status_indicator.add_css_class("service-active" if is_active else "service-inactive")
        status_box.append(status_indicator)

        status_label = Gtk.Label(label=description)
        status_label.set_halign(Gtk.Align.START)
        status_box.append(status_label)
        status_box.set_hexpand(True)

        box.append(status_box)

        # Service ID (smaller text)
        id_label = Gtk.Label(label=service_id)
        id_label.add_css_class("dim-label")
        id_label.set_halign(Gtk.Align.START)
        id_label.set_name(f"service-id-{service_id.replace('.', '-')}")  # Set name for updating
        box.append(id_label)

        return box

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