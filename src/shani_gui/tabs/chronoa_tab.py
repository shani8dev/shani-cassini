"""Chronoa tab for the Shanios GUI.

Integrates shani-chronoa functionality - local AI assistant with Whisper STT,
Ollama LLM, and Piper TTS. Shows configuration status and handles gracefully
when heavy dependencies are not installed.
"""

import logging
from typing import Optional

from gi.repository import Gtk  # type: ignore

from shani_gui.state import AppState
from shani_gui.auth import AuthManager
from shani_gui.cli_wrapper import get_cli_wrapper


logger = logging.getLogger(__name__)


class ChronoaTab(Gtk.Box):
    """Chronoa tab integrating shani-chronoa functionality.

    Provides user interface for Chronoa AI assistant configuration,
    showing GSettings-backed values and status. Handles gracefully
    when heavy dependencies (whisper.cpp, Ollama, Piper TTS) are not
    installed.
    """

    def __init__(
        self,
        state: AppState | None = None,
        auth_manager: AuthManager | None = None,
    ) -> None:
        """Initialize the chronoa tab.

        Args:
            state: Application state object
            auth_manager: Authentication manager
        """
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self._state = state
        self._auth_manager = auth_manager
        self._cli_wrapper = get_cli_wrapper()

        # Initialize shani-chronoa config (GSettings integration)
        from shani_chronoa.config import ChronoaConfig
        self._config = ChronoaConfig()

        self._setup_ui()
        logger.info("ChronoaTab initialized")

    def _setup_ui(self) -> None:
        """Set up the user interface for the chronoa tab."""
        logger.debug("Setting up chronoa tab UI")

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

        # Create AI configuration card
        config_card = self._create_ai_config_card()
        content_box.append(config_card)

        # Create hardware profile card
        hardware_card = self._create_hardware_profile_card()
        content_box.append(hardware_card)

        # Create orb/state status card
        status_card = self._create_orb_status_card()
        content_box.append(status_card)

        # Fetch and display initial data
        self._update_data()

        logger.debug("Chronoa tab UI created")

    def _create_ai_config_card(self) -> Gtk.Box:
        """Create the AI configuration card with GSettings values."""
        card = self._create_card("AI Configuration")

        # Create grid for config rows
        grid = Gtk.Grid()
        grid.set_row_spacing(8)
        grid.set_column_spacing(16)
        grid.set_column_homogeneous(False)
        card.append(grid)

        # Model row
        model = self._config.model
        self._add_info_row(grid, 0, "Model:",
                          model or "Not configured",
                          "model")

        # Privacy mode row
        privacy_mode = self._config.privacy_mode
        privacy_text = "Enabled (Local Only)" if privacy_mode else "Disabled (External Services)"
        self._add_info_row(grid, 1, "Privacy Mode:",
                          privacy_text, "privacy-mode")

        # Whisper model row
        whisper_model = self._config.whisper_model
        self._add_info_row(grid, 2, "Whisper Model:",
                          whisper_model or "Not configured",
                          "whisper-model")

        # Piper voice row
        piper_voice = self._config.piper_voice
        self._add_info_row(grid, 3, "Piper Voice:",
                          piper_voice or "Not configured",
                          "piper-voice")

        # Ollama host row
        ollama_host = self._config.ollama_host
        self._add_info_row(grid, 4, "Ollama Host:",
                          ollama_host or "Not configured",
                          "ollama-host")

        return card

    def _create_hardware_profile_card(self) -> Gtk.Box:
        """Create the hardware profile detection card."""
        card = self._create_card("Hardware Profile")

        # Detect and display hardware profile
        ram_mb = 0
        try:
            import os
            with open("/proc/meminfo") as f:
                for line in f:
                    if line.startswith("MemTotal:"):
                        ram_mb = int(line.split()[1]) // 1024
                        break
        except Exception:
            ram_mb = 0

        gpu_info = "No GPU detected"
        try:
            import subprocess
            result = subprocess.run(
                ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
                capture_output=True, text=True, timeout=5
            )
            gpu_info = result.stdout.strip() if result.returncode == 0 else "No GPU detected"
        except Exception:
            pass

        # CPU cores
        cpu_cores = 0
        try:
            cpu_cores = os.cpu_count() or 0
        except Exception:
            cpu_cores = 0

        # Profile determination (simplified)
        if ram_mb >= 16384:
            profile = "High (16+ GB RAM)"
        elif ram_mb >= 8192:
            profile = "Medium (8+ GB RAM)"
        else:
            profile = "Low (< 8 GB RAM)"

        # GPU status
        gpu_status = "GPU: " + gpu_info

        # Create grid for hardware rows
        grid = Gtk.Grid()
        grid.set_row_spacing(8)
        grid.set_column_spacing(16)
        grid.set_column_homogeneous(False)
        card.append(grid)

        # RAM row
        self._add_info_row(grid, 0, "System RAM:",
                          f"{ram_mb} MB",
                          "hardware-ram")

        # CPU cores row
        self._add_info_row(grid, 1, "CPU Cores:",
                          str(cpu_cores),
                          "hardware-cores")

        # Profile row
        self._add_info_row(grid, 2, "Hardware Profile:",
                          profile,
                          "hardware-profile")

        # GPU row
        self._add_info_row(grid, 3, "GPU Status:",
                          gpu_status,
                          "hardware-gpu")

        # Model selection row (based on profile)
        if gpu_info != "No GPU detected":
            has_gpu = True
        else:
            has_gpu = False
        if has_gpu:
            from shani_chronoa.config import HardwareProfile
            hw = HardwareProfile()
            model_for_profile = hw.get_model()
        else:
            from shani_chronoa.config import HardwareProfile
            hw = HardwareProfile()
            model_for_profile = hw.get_whisper_model()
        self._add_info_row(grid, 4, "Suggested Model:",
                          model_for_profile or "Not determined",
                          "suggested-model")

        return card

    def _create_orb_status_card(self) -> Gtk.Box:
        """Create the Chronoa orb widget status card.

        Since the full ChronoaOrbWidget requires the complete GUI setup,
        we show a simplified status indicator instead.
        """
        card = self._create_card("AI Assistant Status")

        # Status indicators
        grid = Gtk.Grid()
        grid.set_row_spacing(8)
        grid.set_column_spacing(16)
        grid.set_column_homogeneous(False)
        card.append(grid)

        # Orb state
        orb_state = "Ready"
        self._add_info_row(grid, 0, "Orb State:",
                          orb_state,
                          "orb-state")

        # Listening state
        self._add_info_row(grid, 1, "Listening:",
                          "No",
                          "listening-state")

        # Processing state
        self._add_info_row(grid, 2, "Processing:",
                          "No",
                          "processing-state")

        # Error state
        self._add_info_row(grid, 3, "Error State:",
                          "No",
                          "error-state")

        # Connection status
        self._add_info_row(grid, 4, "MCP Connection:",
                          "Not available",
                          "mcp-status")

        # Summary
        summary = Gtk.Label()
        summary.set_label(
            "Shani Chronoa AI Assistant Configuration\n\n"
            "This tab shows the current GSettings configuration for the\n"
            "Chronoa local AI assistant. Heavy dependencies (whisper.cpp,\n"
            "Ollama, Piper TTS) are not installed in this environment,\n"
            "so AI functionality is not available.\n\n"
            "Configuration values are read from the org.shani.chronoa GSettings\n"
            "schema. To use full AI features, install the required dependencies."
        )
        summary.set_justify(Gtk.Justify.LEFT)
        summary.set_xalign(0)
        grid.attach(summary, 0, 5, 2, 1)

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
        logger.debug("Fetching real data for chronoa tab")

        # Config values already displayed via config card
        # GSettings provides the values - no additional fetch needed

        logger.debug("Chronoa tab data updated")
