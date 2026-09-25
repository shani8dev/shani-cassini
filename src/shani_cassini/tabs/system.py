"""System tab for the Shani Cassini."""

import logging
import json
import os
import platform
import subprocess
from typing import override

from gi.repository import Gtk, Pango  # type: ignore
from shani_cassini.widgets import _gtk4_children

from shani_cassini.state import AppState
from shani_cassini.auth import AuthManager
from shani_cassini.api_client import APIClient
from shani_cassini import system_status as ss

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
        
        self._fetch_boot_slots_info()

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
        """Fetch the boot fields exposed by shani-deploy."""
        def done(result, err):
            if result is None:
                for name in ("boot-current", "boot-marker", "boot-deployment", "boot-reboot", "boot-failure", "boot-recovery"):
                    self._update_label(name, "Unavailable")
                logger.warning("Failed to get slot information from shani-deploy: %s", err)
                return

            booted_slot = result.get("booted_slot") or ""
            current_slot = result.get("current_slot") or ""
            self._update_label("boot-current", f"@{booted_slot}" if booted_slot else "Unavailable")
            self._update_label("boot-marker", f"@{current_slot}" if current_slot else "Unavailable")
            self._update_label(
                "boot-deployment",
                "Awaiting reboot" if result.get("candidate_boot") else "No pending deployment",
            )
            self._update_label(
                "boot-reboot",
                "Required" if result.get("reboot_needed") else "Not required",
            )
            self._update_label("boot-failure", result.get("boot_failure") or "None reported")
            self._update_label(
                "boot-recovery",
                "Attempted" if result.get("auto_rollback_done") else "Not attempted",
            )

        ss.deploy_status(done)

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
            if isinstance(widget, Gtk.Widget):
                for child in _gtk4_children(widget):
                    found = find_widget(child)
                    if found:
                        return found
            return None
        
        widget = find_widget(self)  # the tab itself: get_root() is None until it is in a window
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

        self._add_info_row(grid, 0, "Booted Slot:", "", "boot-current")
        self._add_info_row(grid, 1, "Current Slot:", "", "boot-marker")
        self._add_info_row(grid, 2, "Deployment State:", "", "boot-deployment")
        self._add_info_row(grid, 3, "Reboot:", "", "boot-reboot")
        self._add_info_row(grid, 4, "Boot Failure:", "", "boot-failure")
        self._add_info_row(grid, 5, "Recovery Attempt:", "", "boot-recovery")

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
        # wrap: one long value (a kernel version) otherwise widened every page
        value.set_wrap(True)
        value.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
        value.set_xalign(0)
        value.set_selectable(True)
        value.set_halign(Gtk.Align.START)
        if widget_name:
            value.set_name(widget_name)
        grid.attach(value, 1, row, 1, 1)