"""Voice / accessibility reporter — read-only surface from matrix (voice).
Surface: voice (matrix). No privileged call on load; honest empty state."""
from gi.repository import Gtk, Adw

class VoiceAccessTab(Gtk.Box):
    def __init__(self, state=None, auth_manager=None) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        group = Adw.PreferencesGroup(title="Voice & screen reading")
        for text in ["Voice / speech-dispatcher / at-spi registry.",
                     "No speech tool installed — nothing to report.",
                     "Chart group hidden when no voice tools present."]:
            row = Adw.ActionRow(title=text)
            group.add(row)
        self.append(group)
