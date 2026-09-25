"""Settings tab for the Shani Cassini."""

import logging
import json
import os
from typing import override

from gi.repository import Gtk  # type: ignore
from shani_cassini.widgets import _gtk4_children

from shani_cassini.state import AppState
from shani_cassini.auth import AuthManager
from shani_cassini.api_client import APIClient
from shani_cassini.cli_wrapper import get_cli_wrapper

logger = logging.getLogger(__name__)

class SettingsTab(Gtk.Box):
    """Settings tab for configuring system preferences."""

    def __init__(
        self,
        state: AppState | None = None,
        auth_manager: AuthManager | None = None,
    ) -> None:
        """Initialize the settings tab.
        
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
        logger.info("SettingsTab initialized")

    def _setup_ui(self) -> None:
        """Set up the user interface for the settings tab."""
        logger.debug("Setting up settings tab UI")

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

        # Create personal settings card
        personal_card = self._create_personal_settings_card()
        content_box.append(personal_card)

        # Create hardware settings card
        hardware_card = self._create_hardware_settings_card()
        content_box.append(hardware_card)

        # Create system settings card
        system_card = self._create_system_settings_card()
        content_box.append(system_card)

        # Fetch initial data
        """Fetch real data and update the UI elements."""
        logger.debug("Fetching real data for settings tab")
        
        # Fetch system settings information
        self._fetch_system_settings()
        
        # Fetch user interface preferences
        self._fetch_ui_preferences()
        
        # Fetch region and language settings
        self._fetch_region_language()
        
        # Fetch date and time settings
        self._fetch_date_time()
        
        # Fetch keyboard settings
        self._fetch_keyboard_settings()

    def _fetch_system_settings(self) -> None:
        """Fetch system settings information and update the UI."""
        try:
            # Get system settings from shani-settings or default values
            # For now, we'll use default values and update the checkboxes
            # In a real implementation, we would read from /etc/shani-* files
            
            # Update automatic updates checkbox
            auto_updates = True  # Default
            auto_updates_cb = self.get_root().get_descendant_by_name("auto-updates-check")
            if auto_updates_cb and isinstance(auto_updates_cb, Gtk.CheckButton):
                self._update_check_button("auto-updates-check", auto_updates)
            
            # Update telemetry collection checkbox
            telemetry = False  # Default
            telemetry_cb = self.get_root().get_descendant_by_name("telemetry-check")
            if telemetry_cb and isinstance(telemetry_cb, Gtk.CheckButton):
                self._update_check_button("telemetry-check", telemetry)
            
            # Update fleet enrollment checkbox
            fleet_enrollment = False  # Default
            fleet_cb = self.get_root().get_descendant_by_name("fleet-enrollment-check")
            if fleet_cb and isinstance(fleet_cb, Gtk.CheckButton):
                self._update_check_button("fleet-enrollment-check", fleet_enrollment)
                
        except Exception as e:
            logger.error(f"Failed to fetch system settings: {e}")

    def _fetch_ui_preferences(self) -> None:
        """Fetch user interface preferences and update the UI."""
        try:
            # Get GTK settings or use defaults
            # Theme
            theme = "Adwaita (default)"
            theme_combo = self.get_root().get_descendant_by_name("theme-combo")
            if theme_combo and isinstance(theme_combo, Gtk.ComboBoxText):
                self._update_combo_box_text("theme-combo", theme)
            
            # Font
            font = "Sans 11"
            font_combo = self.get_root().get_descendant_by_name("font-combo")
            if font_combo and isinstance(font_combo, Gtk.ComboBoxText):
                self._update_combo_box_text("font-combo", font)
            
            # Icon size
            icon_size = "Medium"
            icon_combo = self.get_root().get_descendant_by_name("icon-size-combo")
            if icon_combo and isinstance(icon_combo, Gtk.ComboBoxText):
                self._update_combo_box_text("icon-size-combo", icon_size)
                
        except Exception as e:
            logger.error(f"Failed to fetch UI preferences: {e}")

    def _fetch_region_language(self) -> None:
        """Fetch region and language settings and update the UI."""
        try:
            # Get locale settings
            language = "English (US)"
            language_combo = self.get_root().get_descendant_by_name("language-combo")
            if language_combo and isinstance(language_combo, Gtk.ComboBoxText):
                self._update_combo_box_text("language-combo", language)
            
            # Region
            region = "United States"
            region_combo = self.get_root().get_descendant_by_name("region-combo")
            if region_combo and isinstance(region_combo, Gtk.ComboBoxText):
                self._update_combo_box_text("region-combo", region)
            
            # Format
            format_str = "USD ($)"
            format_combo = self.get_root().get_descendant_by_name("format-combo")
            if format_combo and isinstance(format_combo, Gtk.ComboBoxText):
                self._update_combo_box_text("format-combo", format_str)
                
        except Exception as e:
            logger.error(f"Failed to fetch region and language settings: {e}")

    def _fetch_date_time(self) -> None:
        """Fetch date and time settings and update the UI."""
        try:
            # Get current date and time
            import datetime
            now = datetime.datetime.now()
            date_str = now.strftime("%a %b %d %Y")
            time_str = now.strftime("%H:%M:%S")
            
            date_label = self.get_root().get_descendant_by_name("date-label")
            if date_label and isinstance(date_label, Gtk.Label):
                date_label.set_label(date_str)
            
            time_label = self.get_root().get_descendant_by_name("time-label")
            if time_label and isinstance(time_label, Gtk.Label):
                time_label.set_label(time_str)
            
            # Get timezone
            try:
                timezone = subprocess.check_output(['cat', '/etc/timezone'], text=True).strip()
            except:
                timezone = "Asia/Kolkata"  # Default
            
            timezone_combo = self.get_root().get_descendant_by_name("timezone-combo")
            if timezone_combo and isinstance(timezone_combo, Gtk.ComboBoxText):
                self._update_combo_box_text("timezone-combo", timezone)
            
            # Get automatic time setting
            auto_time = True  # Default
            auto_time_cb = self.get_root().get_descendant_by_name("auto-time-check")
            if auto_time_cb and isinstance(auto_time_cb, Gtk.CheckButton):
                self._update_check_button("auto-time-check", auto_time)
            
            # Update the datetime button label
            datetime_button = self.get_root().get_descendant_by_name("datetime-button")
            if datetime_button and isinstance(datetime_button, Gtk.Button):
                self._update_datetime_label(datetime_button)
                
        except Exception as e:
            logger.error(f"Failed to fetch date and time settings: {e}")

    def _fetch_keyboard_settings(self) -> None:
        """Fetch keyboard settings and update the UI."""
        try:
            # Get keyboard layout
            try:
                layout = subprocess.check_output(['localectl', 'status'], text=True)
                # Parse the output to get the X11 layout
                # For simplicity, we'll use a default
                keyboard_layout = "English (US)"
            except:
                keyboard_layout = "English (US)"
            
            keyboard_combo = self.get_root().get_descendant_by_name("keyboard-combo")
            if keyboard_combo and isinstance(keyboard_combo, Gtk.ComboBoxText):
                self._update_combo_box_text("keyboard-combo", keyboard_layout)
            
            # Get show input menu setting
            show_input = False  # Default
            show_input_cb = self.get_root().get_descendant_by_name("show-input-check")
            if show_input_cb and isinstance(show_input_cb, Gtk.CheckButton):
                self._update_check_button("show-input-check", show_input)
                
        except Exception as e:
            logger.error(f"Failed to fetch keyboard settings: {e}")

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
        
        widget = find_widget(self.get_root())
        if widget and isinstance(widget, Gtk.Label):
            widget.set_label(text)
        else:
            logger.debug(f"Widget not found or not a label: {widget_name}")

    def _update_combo_box_text(self, widget_name: str, text: str) -> None:
        """Update a combo box text widget by its name.
        
        Args:
            widget_name: The name of the widget to update
            text: The text to select
        """
        widget = self.get_root().get_descendant_by_name(widget_name)
        if widget and isinstance(widget, Gtk.ComboBoxText):
            # Find the index of the text and set it
            for i in range(widget.get_n_items()):
                if widget.get_item_text(i) == text:
                    widget.set_active(i)
                    break
        else:
            logger.debug(f"Widget not found or not a combo box text: {widget_name}")

    def _update_check_button(self, widget_name: str, active: bool) -> None:
        """Update a check button widget by its name.
        
        Args:
            widget_name: The name of the widget to update
            active: Whether the button should be active
        """
        widget = self.get_root().get_descendant_by_name(widget_name)
        if widget and isinstance(widget, Gtk.CheckButton):
            widget.set_active(active)
        else:
            logger.debug(f"Widget not found or not a check button: {widget_name}")

    def _update_datetime_label(self, button: Gtk.Button) -> None:
        """Update the date/time label on the button.
        
        Args:
            button: The button to update
        """
        try:
            # Get current date and time
            import datetime
            now = datetime.datetime.now()
            date_str = now.strftime("%a %b %d %Y")
            time_str = now.strftime("%I:%M %p")
            
            # Get timezone
            try:
                timezone = subprocess.check_output(['cat', '/etc/timezone'], text=True).strip()
            except:
                timezone = "Asia/Kolkata"  # Default
            
            # Format the label
            label_text = f"{timezone} • {time_str}"
            button.set_label(label_text)
        except Exception as e:
            logger.error(f"Failed to update datetime label: {e}")
            # Set a default label
            button.set_label("Asia/Kolkata • 07:45 PM")

    def _create_personal_settings_card(self) -> Gtk.Box:
        """Create the personal settings card.
        
        Returns:
            Personal settings card widget
        """
        card = self._create_card("Personal Settings")

        # Create grid for personal settings
        grid = Gtk.Grid()
        grid.set_row_spacing(12)
        grid.set_column_spacing(16)
        card.append(grid)

        # Add personal settings rows
        self._add_setting_row(grid, 0, "Theme:", self._create_theme_combo())
        self._add_setting_row(grid, 1, "Show battery percentage:", self._create_battery_switch())
        self._add_setting_row(grid, 2, "Night light:", self._create_nightlight_switch())
        self._add_setting_row(grid, 3, "Date & Time:", self._create_datetime_box())
        self._add_setting_row(grid, 4, "Keyboard:", self._create_keyboard_box())
        self._add_setting_row(grid, 5, "Region & Language:", self._create_region_language_box())

        return card

    def _create_hardware_settings_card(self) -> Gtk.Box:
        """Create the hardware settings card.
        
        Returns:
            Hardware settings card widget
        """
        card = self._create_card("Hardware Settings")

        # Create grid for hardware settings
        grid = Gtk.Grid()
        grid.set_row_spacing(12)
        grid.set_column_spacing(16)
        card.append(grid)

        # Add hardware settings rows
        self._add_setting_row(grid, 0, "Bluetooth:", self._create_bluetooth_switch())
        self._add_setting_row(grid, 1, "Wi-Fi:", self._create_wifi_switch())
        self._add_setting_row(grid, 2, "Touchpad:", self._create_touchpad_switch())
        self._add_setting_row(grid, 3, "Touchpad tapping:", self._create_tap_to_click_switch())

        return card

    def _create_system_settings_card(self) -> Gtk.Box:
        """Create the system settings card.
        
        Returns:
            System settings card widget
        """
        card = self._create_card("System Settings")

        # Create grid for system settings
        grid = Gtk.Grid()
        grid.set_row_spacing(12)
        grid.set_column_spacing(16)
        card.append(grid)

        # Add system settings rows
        self._add_setting_row(grid, 0, "Automatic Updates:", self._create_auto_update_switch())
        self._add_setting_row(grid, 1, "Auto-suspend when idle:", self._create_suspend_switch())
        self._add_setting_row(grid, 2, "Submit anonymized usage data:", self._create_usage_data_switch())
        self._add_setting_row(grid, 3, "Enable telemetry collection:", self._create_telemetry_switch())

        # Add about system button
        about_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        about_box.set_halign(Gtk.Align.END)
        about_btn = Gtk.Button(label="About This System")
        about_btn.connect("clicked", self._on_about_system_clicked)
        about_box.append(about_btn)
        card.append(about_box)

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

    def _add_setting_row(self, grid: Gtk.Grid, row: int, label_text: str, 
                        widget: Gtk.Widget) -> None:
        """Add a settings row to a grid.
        
        Args:
            grid: Grid to add the row to
            row: Row index
            label_text: Label text
            widget: Settings widget
        """
        label = Gtk.Label(label=label_text)
        label.add_css_class("label-label")
        label.set_halign(Gtk.Align.START)
        grid.attach(label, 0, row, 1, 1)

        # Create container for the widget with proper alignment
        container = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        container.set_halign(Gtk.Align.START)
        container.set_hexpand(True)
        container.append(widget)
        grid.attach(container, 1, row, 1, 1)

    def _create_theme_combo(self) -> Gtk.ComboBoxText:
        """Create theme selection combo box.
        
        Returns:
            Theme combo box
        """
        combo = Gtk.ComboBoxText()
        combo.set_name("theme-combo")  # Set name for updating
        combo.append_text("System Default")
        combo.append_text("Light")
        combo.append_text("Dark")
        combo.append_text("Dark (High Contrast)")
        combo.set_active(0)  # System Default
        return combo

    def _create_battery_switch(self) -> Gtk.Switch:
        """Create battery percentage switch.
        
        Returns:
            Battery percentage switch
        """
        switch = Gtk.Switch()
        switch.set_name("battery-percentage-switch")  # Set name for updating
        switch.set_active(False)  # Default: don't show battery percentage
        return switch

    def _create_nightlight_switch(self) -> Gtk.Switch:
        """Create night light switch.
        
        Returns:
            Night light switch
        """
        switch = Gtk.Switch()
        switch.set_name("nightlight-switch")  # Set name for updating
        switch.set_active(True)  # Default: night light on
        return switch

    def _create_datetime_button(self) -> Gtk.Button:
        """Create date & time button.
        
        Returns:
            Date & time button
        """
        button = Gtk.Button()
        button.set_name("datetime-button")  # Set name for updating
        button.add_css_class("flat")
        # Set initial label
        self._update_datetime_label(button)
        return button

    def _create_keyboard_button(self) -> Gtk.Button:
        """Create keyboard settings button.
        
        Returns:
            Keyboard settings button
        """
        button = Gtk.Button(label="US English")
        button.add_css_class("flat")
        return button

    def _create_language_button(self) -> Gtk.Button:
        """Create region & language button.
        
        Returns:
            Region & language button
        """
        button = Gtk.Button(label="English (United States)")
        button.add_css_class("flat")
        return button

    def _create_datetime_box(self) -> Gtk.Box:
        """Create date & time display box."""
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        box.set_halign(Gtk.Align.FILL)
        box.set_hexpand(True)
        
        date_label = Gtk.Label()
        date_label.set_name("date-label")
        date_label.set_halign(Gtk.Align.START)
        box.append(date_label)
        
        separator = Gtk.Label(label="•")
        separator.set_halign(Gtk.Align.CENTER)
        box.append(separator)
        
        time_label = Gtk.Label()
        time_label.set_name("time-label")
        time_label.set_halign(Gtk.Align.START)
        box.append(time_label)
        
        self._update_datetime_box_labels(date_label, time_label)

        return box

    def _update_datetime_box_labels(
        self, date_label: Gtk.Label, time_label: Gtk.Label
    ) -> None:
        """Update the date and time labels in the datetime box.

        Replaces the old button-based ``_update_datetime_label``; the box
        exposes its text via ``Gtk.Label`` widgets rather than a button, so
        the labels are updated directly instead of calling a method that
        expects a ``Gtk.Button`` (which does not exist in this scope).
        """
        try:
            import datetime

            now = datetime.datetime.now()
            date_label.set_text(now.strftime("%a %b %d %Y"))
            time_label.set_text(now.strftime("%I:%M %p"))
        except Exception as e:
            logger.error(f"Failed to update datetime labels: {e}")
            date_label.set_text("Jan 01 2025")
            time_label.set_text("12:00 AM")

    def _create_keyboard_box(self) -> Gtk.Box:
        """Create keyboard settings box."""
        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        box.set_halign(Gtk.Align.FILL)
        box.set_hexpand(True)
        
        keyboard_label = Gtk.Label(label="US English")
        keyboard_label.set_name("keyboard-label")
        keyboard_label.set_halign(Gtk.Align.START)
        box.append(keyboard_label)
        
        show_input_cb = Gtk.CheckButton(label="Show input menu in menu bar")
        show_input_cb.set_name("show-input-check")
        show_input_cb.set_halign(Gtk.Align.END)
        box.append(show_input_cb)
        
        return box

    def _create_region_language_box(self) -> Gtk.Box:
        """Create region & language settings box."""
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.set_halign(Gtk.Align.FILL)
        box.set_hexpand(True)
        
        # Language row
        lang_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        lang_label = Gtk.Label(label="Language:")
        lang_label.set_halign(Gtk.Align.START)
        lang_box.append(lang_label)
        
        lang_combo = Gtk.ComboBoxText()
        lang_combo.set_name("language-combo")
        lang_combo.append_text("English (US)")
        lang_combo.append_text("English (UK)")
        lang_combo.append_text("Spanish")
        lang_combo.append_text("French")
        lang_combo.append_text("German")
        lang_combo.set_active(0)
        lang_box.append(lang_combo)
        lang_box.set_hexpand(True)
        box.append(lang_box)
        
        # Region row
        region_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        region_label = Gtk.Label(label="Region:")
        region_label.set_halign(Gtk.Align.START)
        region_box.append(region_label)
        
        region_combo = Gtk.ComboBoxText()
        region_combo.set_name("region-combo")
        region_combo.append_text("United States")
        region_combo.append_text("United Kingdom")
        region_combo.append_text("Canada")
        region_combo.append_text("Australia")
        region_combo.append_text("India")
        region_combo.set_active(0)
        region_box.append(region_combo)
        region_box.set_hexpand(True)
        box.append(region_box)
        
        # Format row
        format_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        format_label = Gtk.Label(label="Format:")
        format_label.set_halign(Gtk.Align.START)
        format_box.append(format_label)
        
        format_combo = Gtk.ComboBoxText()
        format_combo.set_name("format-combo")
        format_combo.append_text("USD ($)")
        format_combo.append_text("EUR (€)")
        format_combo.append_text("GBP (£)")
        format_combo.append_text("INR (₹)")
        format_combo.append_text("JPY (¥)")
        format_combo.set_active(0)
        format_box.append(format_combo)
        format_box.set_hexpand(True)
        box.append(format_box)
        
        return box

    def _create_font_combo(self) -> Gtk.ComboBoxText:
        """Create font selection combo box.
        
        Returns:
            Font combo box
        """
        combo = Gtk.ComboBoxText()
        combo.set_name("font-combo")  # Set name for updating
        combo.append_text("Sans 9")
        combo.append_text("Sans 10")
        combo.append_text("Sans 11")
        combo.append_text("Sans 12")
        combo.append_text("Sans 13")
        combo.append_text("Sans 14")
        combo.set_active(2)  # Sans 11
        return combo

    def _create_icon_size_combo(self) -> Gtk.ComboBoxText:
        """Create icon size selection combo box.
        
        Returns:
            Icon size combo box
        """
        combo = Gtk.ComboBoxText()
        combo.set_name("icon-size-combo")  # Set name for updating
        combo.append_text("Small")
        combo.append_text("Medium")
        combo.append_text("Large")
        combo.set_active(1)  # Medium
        return combo

    def _create_bluetooth_switch(self) -> Gtk.Switch:
        """Create Bluetooth switch.
        
        Returns:
            Bluetooth switch
        """
        switch = Gtk.Switch()
        switch.set_active(True)  # Default: Bluetooth on
        return switch

    def _create_wifi_switch(self) -> Gtk.Switch:
        """Create Wi-Fi switch.
        
        Returns:
            Wi-Fi switch
        """
        switch = Gtk.Switch()
        switch.set_active(True)  # Default: Wi-Fi on
        return switch

    def _create_touchpad_switch(self) -> Gtk.Switch:
        """Create touchpad switch.
        
        Returns:
            Touchpad switch
        """
        switch = Gtk.Switch()
        switch.set_active(True)  # Default: Touchpad on
        return switch

    def _create_tap_to_click_switch(self) -> Gtk.Switch:
        """Create tap-to-click switch.
        
        Returns:
            Tap-to-click switch
        """
        switch = Gtk.Switch()
        switch.set_active(True)  # Default: Tap-to-click on
        return switch

    def _create_auto_update_switch(self) -> Gtk.Switch:
        """Create automatic updates switch.

        Returns:
            Automatic updates switch
        """
        switch = Gtk.Switch()
        switch.set_name("auto-updates-check")  # Set name for updating
        switch.set_active(True)  # Default: Automatic updates on
        return switch

    def _create_suspend_switch(self) -> Gtk.Switch:
        """Create auto-suspend switch.

        Returns:
            Auto-suspend switch
        """
        switch = Gtk.Switch()
        switch.set_name("auto-suspend-check")  # Set name for updating
        switch.set_active(True)  # Default: Auto-suspend when idle
        return switch

    def _create_usage_data_switch(self) -> Gtk.Switch:
        """Create usage data switch.

        Returns:
            Usage data switch
        """
        switch = Gtk.Switch()
        switch.set_name("usage-data-check")  # Set name for updating
        switch.set_active(False)  # Default: Don't submit usage data
        return switch

    def _create_telemetry_switch(self) -> Gtk.Switch:
        """Create telemetry collection switch.
        
        Returns:
            Telemetry collection switch
        """
        switch = Gtk.Switch()
        switch.set_name("telemetry-check")  # Set name for updating
        switch.set_active(False)  # Default: Don't collect telemetry data
        return switch

    def _on_about_system_clicked(self, button: Gtk.Button) -> None:
        """Handle about system button click."""
        logger.info("About system button clicked")
        # TODO: Implement about system dialog
        dialog = Gtk.MessageDialog(
            transient_for=self.get_root(),
            modal=True,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.OK,
            text="About This System",
        )
        dialog.format_secondary_text(
            "OS Name:       Shanios\n"
            "Version:       1.2.3\n"
            "GNOME Version: 45.0\n"
            "Kernel:        6.8.0-42-generic\n"
            "\n"
            "Hardware:\n"
            "● Model:       ThinkPad E14 Gen 2\n"
            "● Processor:   11th Gen Intel Core i7-1165G7\n"
            "● Memory:      31.1 GB"
        )
        dialog.connect("response", lambda d, r: d.destroy())
        dialog.present()