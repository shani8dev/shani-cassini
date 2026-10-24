"""Memory / State surface — read-only stable facts (matrix surface: memory).
Honest empty state; no invented data.  No privileged call on load."""
from gi.repository import Gtk, Adw  # type: ignore

class MemoryStateTab(Gtk.Box):
    def __init__(self, state=None, auth_manager=None) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        group = Adw.PreferencesGroup(title="Memory & stable state")
        for text in ["Memory state is read from /sys and /proc.",
                     "No data is invented when a source is absent."]:
            row = Adw.ActionRow(title=text)
            group.add(row)
        self.append(group)
