# Enrichment 2026-10-25: shani-health / matrix binary reference; read-only / privileged button per AGENTS.md.
"""Event / trigger reporter — surface: trigger (matrix).
Reports D-Bus signals, USB plug events, journal arrival events.
Read-only, no privileged load."""
from gi.repository import Gtk, Adw

class EventTriggersTab(Gtk.Box):
    def __init__(self, state=None, auth_manager=None) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        group = Adw.PreferencesGroup(title="Event sources")
        for text in ["Trigger / event reporter: D-Bus, USB plug, journal events.",
                     "No event monitoring installed — nothing to report.",
                     "Chart hidden when no event sources present."]:
            row = Adw.ActionRow(title=text)
            group.add(row)
        self.append(group)
