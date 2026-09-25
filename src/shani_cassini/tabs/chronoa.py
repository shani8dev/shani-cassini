"""Chronoa tab for the Shani Cassini — integrates shani-chronoa AI assistant."""

import logging
import os
import subprocess
import threading
import time
from typing import override

from gi.repository import GLib, Gtk  # type: ignore
from shani_cassini.widgets import _gtk4_children

from shani_cassini.state import AppState
from shani_cassini.auth import AuthManager
from shani_cassini.cli_wrapper import get_cli_wrapper

logger = logging.getLogger(__name__)

class ChronoaTab(Gtk.Box):
    """Chronoa tab for the local AI assistant with privacy-first design."""

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
        self._update_thread = None
        self._stop_updates = False

        self._setup_ui()
        logger.info("ChronoaTab initialized")
        
        self._start_periodic_updates()

    def _setup_ui(self) -> None:
        """Set up the user interface for the chronoa tab."""
        logger.debug("Setting up chronoa tab UI")

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

        config_card = self._create_config_card()
        content_box.append(config_card)

        model_card = self._create_model_card()
        content_box.append(model_card)

        privacy_card = self._create_privacy_card()
        content_box.append(privacy_card)

        logger.debug("Chronoa tab UI created")

    def _create_status_card(self) -> Gtk.Box:
        """Create the AI assistant status card.
        
        Returns:
            Status card widget
        """
        card = self._create_card("AI Assistant Status")

        grid = Gtk.Grid()
        grid.set_row_spacing(8)
        grid.set_column_spacing(16)
        grid.set_column_homogeneous(False)
        card.append(grid)

        self._add_info_row(grid, 0, "Assistant:", "Checking...", "chronoa-assistant-status")
        self._add_info_row(grid, 1, "Model:", "Checking...", "chronoa-model")
        self._add_info_row(grid, 2, "Speech Recognition:", "Checking...", "chronoa-stt")
        self._add_info_row(grid, 3, "Text-to-Speech:", "Checking...", "chronoa-tts")
        self._add_info_row(grid, 4, "Privacy Mode:", "Checking...", "chronoa-privacy")

        return card

    def _create_config_card(self) -> Gtk.Box:
        """Create the configuration card.
        
        Returns:
            Configuration card widget
        """
        card = self._create_card("Configuration")

        grid = Gtk.Grid()
        grid.set_row_spacing(8)
        grid.set_column_spacing(16)
        grid.set_column_homogeneous(False)
        card.append(grid)

        self._add_info_row(grid, 0, "Ollama Host:", "Checking...", "chronoa-ollama-host")
        self._add_info_row(grid, 1, "Whisper Model:", "Checking...", "chronoa-whisper-model")
        self._add_info_row(grid, 2, "Voice:", "Checking...", "chronoa-voice")
        self._add_info_row(grid, 3, "Language:", "Checking...", "chronoa-language")

        return card

    def _create_model_card(self) -> Gtk.Box:
        """Create the model selection card.
        
        Returns:
            Model card widget
        """
        card = self._create_card("Model Selection")

        grid = Gtk.Grid()
        grid.set_row_spacing(8)
        grid.set_column_spacing(16)
        grid.set_column_homogeneous(False)
        card.append(grid)

        self._add_info_row(grid, 0, "Hardware Profile:", "Checking...", "chronoa-hardware")
        self._add_info_row(grid, 1, "GPU Available:", "Checking...", "chronoa-gpu")
        self._add_info_row(grid, 2, "RAM:", "Checking...", "chronoa-ram")

        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        button_box.set_halign(Gtk.Align.END)
        refresh_btn = Gtk.Button(label="Refresh Hardware")
        refresh_btn.connect("clicked", self._on_refresh_hardware_clicked)
        button_box.append(refresh_btn)
        card.append(button_box)

        return card

    def _create_privacy_card(self) -> Gtk.Box:
        """Create the privacy controls card.
        
        Returns:
            Privacy card widget
        """
        card = self._create_card("Privacy Controls")

        grid = Gtk.Grid()
        grid.set_row_spacing(8)
        grid.set_column_spacing(16)
        grid.set_column_homogeneous(False)
        card.append(grid)

        self._add_info_row(grid, 0, "Privacy Mode:", "Checking...", "chronoa-privacy-mode")
        self._add_info_row(grid, 1, "Local Only:", "Checking...", "chronoa-local-only")
        self._add_info_row(grid, 2, "Notifications:", "Checking...", "chronoa-notifications")
        self._add_info_row(grid, 3, "Auto Start:", "Checking...", "chronoa-auto-start")

        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        button_box.set_halign(Gtk.Align.END)
        toggle_btn = Gtk.Button(label="Toggle Privacy Mode")
        toggle_btn.connect("clicked", self._on_toggle_privacy_clicked)
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
        """Start periodic updates for chronoa status."""
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
        """Update loop for fetching chronoa status."""
        while not self._stop_updates:
            try:
                self._update_chronoa_status()
                time.sleep(30)
            except Exception as e:
                logger.error(f"Error in chronoa update loop: {e}")
                time.sleep(5)

    def _update_chronoa_status(self) -> None:
        """Update chronoa status information."""
        try:
            self._update_assistant_status()
            self._update_config()
            self._update_model_info()
            self._update_privacy_status()
        except Exception as e:
            logger.error(f"Error updating chronoa status: {e}")

    def _update_assistant_status(self) -> None:
        """Update assistant status display."""
        try:
            result = self._cli_wrapper.chronoa_status()
            if result and isinstance(result, dict):
                status = result.get("status", "Unknown")
                model = result.get("model", "N/A")
                stt = result.get("stt_available", False)
                tts = result.get("tts_available", False)
                privacy = result.get("privacy_mode", False)
            else:
                status = "Not installed"
                model = "N/A"
                stt = False
                tts = False
                privacy = False
            stt_text = "Available" if stt else "Unavailable"
            tts_text = "Available" if tts else "Unavailable"
            privacy_text = "Enabled" if privacy else "Disabled"
            GLib.idle_add(self._update_label_text, "chronoa-assistant-status", status)
            GLib.idle_add(self._update_label_text, "chronoa-model", model)
            GLib.idle_add(self._update_label_text, "chronoa-stt", stt_text)
            GLib.idle_add(self._update_label_text, "chronoa-tts", tts_text)
            GLib.idle_add(self._update_label_text, "chronoa-privacy", privacy_text)
        except Exception:
            GLib.idle_add(self._update_label_text, "chronoa-assistant-status", "Unavailable")
            GLib.idle_add(self._update_label_text, "chronoa-model", "Unavailable")
            GLib.idle_add(self._update_label_text, "chronoa-stt", "Unavailable")
            GLib.idle_add(self._update_label_text, "chronoa-tts", "Unavailable")
            GLib.idle_add(self._update_label_text, "chronoa-privacy", "Unavailable")

    def _update_config(self) -> None:
        """Update configuration display."""
        try:
            result = self._cli_wrapper.chronoa_config()
            if result and isinstance(result, dict):
                ollama_host = result.get("ollama_host", "N/A")
                whisper_model = result.get("whisper_model", "N/A")
                voice = result.get("piper_voice", "N/A")
                language = result.get("language", "en")
            else:
                ollama_host = "N/A"
                whisper_model = "N/A"
                voice = "N/A"
                language = "en"
            GLib.idle_add(self._update_label_text, "chronoa-ollama-host", ollama_host)
            GLib.idle_add(self._update_label_text, "chronoa-whisper-model", whisper_model)
            GLib.idle_add(self._update_label_text, "chronoa-voice", voice)
            GLib.idle_add(self._update_label_text, "chronoa-language", language)
        except Exception:
            GLib.idle_add(self._update_label_text, "chronoa-ollama-host", "Unavailable")
            GLib.idle_add(self._update_label_text, "chronoa-whisper-model", "Unavailable")
            GLib.idle_add(self._update_label_text, "chronoa-voice", "Unavailable")
            GLib.idle_add(self._update_label_text, "chronoa-language", "Unavailable")

    def _update_model_info(self) -> None:
        """Update model and hardware information."""
        try:
            result = self._cli_wrapper.chronoa_status()
            if result and isinstance(result, dict):
                profile = result.get("hardware_profile", "auto")
                gpu = result.get("gpu_available", False)
                ram = result.get("ram_mb", 0)
            else:
                profile = "N/A"
                gpu = False
                ram = 0
            gpu_text = "Yes" if gpu else "No"
            ram_text = f"{ram} MB" if ram > 0 else "Unknown"
            GLib.idle_add(self._update_label_text, "chronoa-hardware", profile)
            GLib.idle_add(self._update_label_text, "chronoa-gpu", gpu_text)
            GLib.idle_add(self._update_label_text, "chronoa-ram", ram_text)
        except Exception:
            GLib.idle_add(self._update_label_text, "chronoa-hardware", "Unavailable")
            GLib.idle_add(self._update_label_text, "chronoa-gpu", "Unavailable")
            GLib.idle_add(self._update_label_text, "chronoa-ram", "Unavailable")

    def _update_privacy_status(self) -> None:
        """Update privacy status display."""
        try:
            result = self._cli_wrapper.chronoa_config()
            if result and isinstance(result, dict):
                privacy_mode = result.get("privacy_mode", False)
                local_only = result.get("local_only", False)
                notifications = result.get("notification_enabled", True)
                auto_start = result.get("auto_start", False)
            else:
                privacy_mode = False
                local_only = False
                notifications = True
                auto_start = False
            GLib.idle_add(self._update_label_text, "chronoa-privacy-mode", 
                        "Enabled" if privacy_mode else "Disabled")
            GLib.idle_add(self._update_label_text, "chronoa-local-only",
                        "Yes" if local_only else "No")
            GLib.idle_add(self._update_label_text, "chronoa-notifications",
                        "Enabled" if notifications else "Disabled")
            GLib.idle_add(self._update_label_text, "chronoa-auto-start",
                        "Enabled" if auto_start else "Disabled")
        except Exception:
            GLib.idle_add(self._update_label_text, "chronoa-privacy-mode", "Unavailable")
            GLib.idle_add(self._update_label_text, "chronoa-local-only", "Unavailable")
            GLib.idle_add(self._update_label_text, "chronoa-notifications", "Unavailable")
            GLib.idle_add(self._update_label_text, "chronoa-auto-start", "Unavailable")

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
    def _on_refresh_hardware_clicked(self, button: Gtk.Button) -> None:
        """Handle refresh hardware button click."""
        logger.info("Refresh hardware button clicked")
        thread = threading.Thread(target=self._refresh_hardware_thread)
        thread.daemon = True
        thread.start()

    def _refresh_hardware_thread(self) -> None:
        """Refresh hardware info in a background thread."""
        try:
            result = self._cli_wrapper.chronoa_status()
            if result and isinstance(result, dict):
                profile = result.get("hardware_profile", "auto")
                gpu = result.get("gpu_available", False)
                ram = result.get("ram_mb", 0)
                GLib.idle_add(self._update_label_text, "chronoa-hardware", profile)
                GLib.idle_add(self._update_label_text, "chronoa-gpu", "Yes" if gpu else "No")
                GLib.idle_add(self._update_label_text, "chronoa-ram", f"{ram} MB" if ram > 0 else "Unknown")
        except Exception as e:
            logger.error(f"Error refreshing hardware info: {e}")

    def _on_toggle_privacy_clicked(self, button: Gtk.Button) -> None:
        """Handle toggle privacy mode button click."""
        logger.info("Toggle privacy mode button clicked")
        dialog = Gtk.MessageDialog(
            transient_for=self.get_root(),
            modal=True,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.OK,
            text="Privacy Control",
        )
        dialog.format_secondary_text(
            "Privacy mode control requires shani-chronoa to be installed.\n"
            "The privacy toggle functionality is not yet available."
        )
        dialog.connect("response", lambda d, r: d.destroy())
        dialog.present()
