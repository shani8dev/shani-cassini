# Enrichment 2026-10-25: shani-health / matrix binary reference; read-only / privileged button per AGENTS.md.
"""Network monitoring reporter — read-only event-source / trigger.
Surface: trigger (curl / iperf3 / arpsnmp / network-state)."""
from gi.repository import Gtk, Adw
class NetworkMonitorTab(Gtk.Box):
    def __init__(self, state=None, auth_manager=None) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        group = Adw.PreferencesGroup(title="Network monitoring")
        for text in ["Network monitor: curl, iperf3, reachability checks.",
                     "No network monitor installed — nothing to report.",
                     "Hidden when no monitoring tools present."]:
            group.add(Adw.ActionRow(title=text))
        self.append(group)
