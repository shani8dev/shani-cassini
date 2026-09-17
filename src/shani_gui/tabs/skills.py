"""Skills tab for the Shanios GUI."""

import logging
from typing import override

from gi.repository import Gtk  # type: ignore

from shani_gui.state import AppState
from shani_gui.auth import AuthManager


logger = logging.getLogger(__name__)


class SkillsTab(Gtk.Box):
    """Skills tab for managing Pulsar OS Sayri skills."""

    def __init__(
        self,
        state: AppState | None = None,
        auth_manager: AuthManager | None = None,
    ) -> None:
        """Initialize the skills tab.

        Args:
            state: Application state object
            auth_manager: Authentication manager
        """
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self._state = state
        self._auth_manager = auth_manager
        self._cli_wrapper = self._auth_manager.get_cli_wrapper() if auth_manager else None

        self._setup_ui()
        logger.info("SkillsTab initialized")

    def _setup_ui(self) -> None:
        """Set up the user interface for the skills tab."""
        logger.debug("Setting up skills tab UI")

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

        # Create skills controls card
        controls_card = self._create_skills_controls_card()
        content_box.append(controls_card)

        # Create skills list card
        list_card = self._create_skills_list_card()
        content_box.append(list_card)

        logger.debug("Skills tab UI created")

    def _create_skills_controls_card(self) -> Gtk.Box:
        """Create the skills controls card.

        Returns:
            Skills controls card widget
        """
        card = self._create_card("Skills Controls")

        # Create grid for controls
        grid = Gtk.Grid()
        grid.set_row_spacing(12)
        grid.set_column_spacing(16)
        grid.set_column_homogeneous(False)
        card.append(grid)

        # Add skill controls
        install_btn = Gtk.Button(label="Install Skill")
        install_btn.add_css_class("suggested-action")
        install_btn.connect("clicked", self._on_install_skill_clicked)
        grid.attach(install_btn, 0, 0, 1, 1)

        search_entry = Gtk.Entry()
        search_entry.set_placeholder_text("Search skills...")
        search_entry.set_hexpand(True)
        grid.attach(search_entry, 1, 0, 1, 1)

        # Add progress bar
        self._progress_bar = Gtk.ProgressBar()
        self._progress_bar.set_visible(False)
        grid.attach(self._progress_bar, 0, 1, 2, 1)

        return card

    def _create_skills_list_card(self) -> Gtk.Box:
        """Create the skills list card.

        Returns:
            Skills list card widget
        """
        card = self._create_card("Installed Skills")

        # Create list box for skills
        self._skills_list = Gtk.ListBox()
        self._skills_list.set_selection_mode(Gtk.SelectionMode.SINGLE)
        self._skills_list.set_activate_on_single_click(False)
        card.append(self._skills_list)

        # Load initial skills
        self._load_skills()

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

    def _load_skills(self) -> None:
        """Load and display skills from state or CLI wrapper."""
        try:
            # Clear existing items
            for child in self._skills_list.get_children():
                self._skills_list.remove(child)

            # If we have CLI wrapper, try to get installed skills
            if self._cli_wrapper:
                # For now, we'll add some sample skills for demonstration
                # In a real implementation, this would call pulsar-skill list
                sample_skills = [
                    {"name": "weather-skill", "description": "Weather forecasting skill"},
                    {"name": "email-assistant", "description": "Email management assistant"},
                    {"name": "code-review", "description": "Code review and analysis skill"},
                    {"name": "telegram-gateway", "description": "Telegram channel gateway"},
                    {"name": "discord-gateway", "description": "Discord channel gateway"},
                    {"name": "virustotal-scanner", "description": "Security scanner for VirusTotal"},
                ]

                for skill in sample_skills:
                    self._add_skill_to_list(skill)
            else:
                # If no auth manager, show a message
                empty_label = Gtk.Label(label="Please authenticate to view skills")
                empty_label.add_css_class("dim-label")
                empty_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
                empty_row.set_margin_start(12)
                empty_row.set_margin_end(12)
                empty_row.append(empty_label)
                self._skills_list.append(empty_row)

        except Exception as e:
            logger.error(f"Failed to load skills: {e}")
            error_label = Gtk.Label(label="Failed to load skills. Please try again.")
            error_label.add_css_class("error-label")
            empty_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
            empty_row.set_margin_start(12)
            empty_row.set_margin_end(12)
            empty_row.append(error_label)
            self._skills_list.append(empty_row)

    def _add_skill_to_list(self, skill: dict) -> None:
        """Add a skill entry to the skills list.

        Args:
            skill: Skill dictionary with name and description
        """
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row.set_margin_start(12)
        row.set_margin_end(12)
        row.set_margin_top(6)
        row.set_margin_bottom(6)

        # Skill icon
        icon = Gtk.Image.new_from_icon_name("applications-system")
        icon.set_pixel_size(32)
        row.append(icon)

        # Skill info
        info_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        info_box.set_hexpand(True)

        # Skill name
        name_label = Gtk.Label(label=skill["name"])
        name_label.add_css_class("skill-name")
        name_label.set_halign(Gtk.Align.START)
        info_box.append(name_label)

        # Skill description
        desc_label = Gtk.Label(label=skill["description"])
        desc_label.add_css_class("skill-description")
        desc_label.set_halign(Gtk.Align.START)
        desc_label.set_wrap(True)
        info_box.append(desc_label)

        row.append(info_box)

        # Action buttons
        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)

        enable_btn = Gtk.Button(label="Enable")
        enable_btn.add_css_class("suggested-action")
        enable_btn.connect("clicked", self._on_enable_skill_clicked, skill)
        button_box.append(enable_btn)

        disable_btn = Gtk.Button(label="Disable")
        disable_btn.connect("clicked", self._on_disable_skill_clicked, skill)
        button_box.append(disable_btn)

        remove_btn = Gtk.Button(label="Remove")
        remove_btn.add_css_class("destructive-action")
        remove_btn.connect("clicked", self._on_remove_skill_clicked, skill)
        button_box.append(remove_btn)

        row.append(button_box)
        self._skills_list.append(row)

    # Event handlers
    def _on_install_skill_clicked(self, button: Gtk.Button) -> None:
        """Handle install skill button click."""
        logger.info("Install skill button clicked")

        # Show dialog for skill installation
        dialog = Gtk.Dialog(title="Install Skill")
        dialog.set_modal(True)
        dialog.set_default_size(400, 150)

        # Create content area
        content_area = dialog.get_child_area()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        box.set_margin_start(12)
        box.set_margin_end(12)
        box.set_margin_top(12)
        box.set_margin_bottom(12)
        content_area.append(box)

        # Skill name entry
        name_label = Gtk.Label(label="Skill Name:")
        name_label.set_halign(Gtk.Align.START)
        box.append(name_label)

        name_entry = Gtk.Entry()
        name_entry.set_hexpand(True)
        box.append(name_entry)

        # Dialog buttons
        response_area = dialog.get_response_area()
        ok_button = response_area.add_button("Install", Gtk.ResponseType.OK)
        cancel_button = response_area.add_button("Cancel", Gtk.ResponseType.CANCEL)

        dialog.show()

        response = dialog.run()

        if response == Gtk.ResponseType.OK:
            skill_name = name_entry.get_text().strip()
            if skill_name:
                logger.info(f"Installing skill: {skill_name}")
                # TODO: Implement actual skill installation via CLI wrapper
                # For now, just add it to state for demo purposes
                if self._state:
                    self._state._plugins[skill_name] = {
                        "name": skill_name,
                        "installed_at": "2026-09-15T10:30:00Z",
                        "status": "enabled"
                    }
                    self._load_skills()
                    self._show_message(f"Skill '{skill_name}' installed successfully")
        dialog.destroy()

    def _on_enable_skill_clicked(self, button: Gtk.Button, skill: dict) -> None:
        """Handle enable skill button click."""
        logger.info(f"Enable skill button clicked for: {skill['name']}")
        if self._state and skill["name"] in self._state._plugins:
            self._state._plugins[skill["name"]]["status"] = "enabled"
            self._show_message(f"Skill '{skill['name']}' enabled")
            self._load_skills()

    def _on_disable_skill_clicked(self, button: Gtk.Button, skill: dict) -> None:
        """Handle disable skill button click."""
        logger.info(f"Disable skill button clicked for: {skill['name']}")
        if self._state and skill["name"] in self._state._plugins:
            self._state._plugins[skill["name"]]["status"] = "disabled"
            self._show_message(f"Skill '{skill['name']}' disabled")
            self._load_skills()

    def _on_remove_skill_clicked(self, button: Gtk.Button, skill: dict) -> None:
        """Handle remove skill button click."""
        logger.info(f"Remove skill button clicked for: {skill['name']}")

        # Show confirmation dialog
        dialog = Gtk.MessageDialog(
            transient_for=self.get_root(),
            modal=True,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.YES_NO,
            text="Remove Skill",
        )
        dialog.format_secondary_text(
            f"Are you sure you want to remove the '{skill['name']}' skill?\n"
            "This action cannot be undone."
        )
        def on_response(dialog: Gtk.MessageDialog, response: int) -> None:
            if response == Gtk.ResponseType.YES:
                if self._state and skill["name"] in self._state._plugins:
                    del self._state._plugins[skill["name"]]
                    self._show_message(f"Skill '{skill['name']}' removed")
                    self._load_skills()
            dialog.destroy()
        dialog.connect("response", on_response)
        dialog.present()

    def _show_message(self, message: str) -> None:
        """Show a temporary message in the UI.

        Args:
            message: Message to display
        """
        logger.info(message)
        # For now, log the message. In a real implementation, this could show a toast notification
        dialog = Gtk.MessageDialog(
            transient_for=self.get_root(),
            modal=True,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.OK,
            text="Information",
        )
        dialog.format_secondary_text(message)
        dialog.connect("response", lambda d, r: d.destroy())
        dialog.present()
