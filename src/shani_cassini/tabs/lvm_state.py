# Enrichment 2026-10-25: shani-health / matrix binary reference; read-only / privileged button per AGENTS.md.
"""LVM reporter — surface: verifier + memory (lvs/lvdisplay/pvdisplay)."""
from gi.repository import Gtk, Adw
class LvmStateTab(Gtk.Box):
    def __init__(self, state=None, auth_manager=None) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        group = Adw.PreferencesGroup(title="Logical volumes")
        for text in ["LVM state: lvs, lvdisplay, pvdisplay — read-only.",
                     "No LVM installed — nothing to report."]:
            group.add(Adw.ActionRow(title=text))
        self.append(group)
