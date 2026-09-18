"""About dialog for the Shanios GUI."""

import logging
from typing import override

from gi.repository import Gtk  # type: ignore

from shani_gui.state import AppState
from shani_gui.auth import AuthManager


logger = logging.getLogger(__name__)


class ShaniosAboutDialog(Gtk.AboutDialog):
    """About dialog showing application information."""

    def __init__(self, parent: Gtk.Window | None = None) -> None:
        """Initialize the about dialog.
        
        Args:
            parent: Parent window
        """
        super().__init__()
        self.set_transient_for(parent)
        self.set_modal(True)
        
        self._setup_dialog()
        logger.info("ShaniosAboutDialog initialized")

    def _setup_dialog(self) -> None:
        """Set up the about dialog content."""
        self.set_program_name("Shanios System Manager")
        self.set_version("0.1.0")
        self.set_copyright("© 2026 Shanios Developers")
        self.set_website("https://github.com/shani8dev/shani-gui")
        self.set_website_label("GitHub Repository")
        self.set_comments("Native GUI Client for Shanios System Management")
        
        # Set authors
        authors = [
            "Shanios Developers <dev@shani.dev>",
        ]
        self.set_authors(authors)
        
        # Set documenters
        documenters = [
            "Shanios Documentation Team",
        ]
        self.set_documenters(documenters)
        
        # Set translators (placeholder)
        translators = [
            "Shanios Localization Team",
        ]
        self.set_translator_credits("\n".join(translators))
        
        # Set license
        license_text = """Shanios GUI Client is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <https://www.gnu.org/licenses/>."""
        self.set_license(license_text)
        
        # Set logo (placeholder - would use actual icon in real implementation)
        # self.set_logo(icon_name="application-default-icon")
        
        logger.debug("About dialog content set up")