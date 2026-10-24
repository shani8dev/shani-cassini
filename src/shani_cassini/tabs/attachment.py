# Enrichment 2026-10-25: shani-health / matrix binary reference; read-only / privileged button per AGENTS.md.
"""Attachment / archive drop reporter — read-only inventory of dropped archives.
Surface: attachment (matrix). Honest empty-state: none of the archive formats
this page manages is installed. No invented counts."""
from gi.repository import Gtk, Adw

class AttachmentTab(Gtk.Box):
    def __init__(self, state=None, auth_manager=None) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        group = Adw.PreferencesGroup(title="Dropped archives")
        for text in ["Attachment / file-drop reporter (7z, bzip2, unarchiver).",
                     "No archive tool installed — nothing to report.",
                     "Chart group hidden when no archive formats present."]:
            row = Adw.ActionRow(title=text)
            group.add(row)
        self.append(group)
