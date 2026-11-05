# Enrichment 2026-10-25: shani-health / matrix binary reference; read-only / privileged button per AGENTS.md.
"""Network monitoring reporter — read-only event-source / trigger. Surface: trigger (curl / iperf3 / arpsnmp / network-state).

Leads with a plain summary of what is installed, checked with have_tool()
rather than stated: the rows that used to say "nothing installed" were
written without looking."""
from gi.repository import Gtk, Adw

from shani_cassini import system_status as ss
from shani_cassini.plain import Details, Summary, esc

# (tool, what it gives a person)
TOOLS = [('ping', 'checking a computer answers'), ('curl', 'checking a website answers'), ('iperf3', 'measuring network speed')]


class NetworkMonitorTab(Gtk.Box):
    def __init__(self, state=None, auth_manager=None) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self._plain = Summary('Network Monitor', 'Tools that check whether the network and the internet can be reached, and how fast.')
        self.append(self._plain)
        details = Details(subtitle="Which tools are installed")
        group = Adw.PreferencesGroup(title='Network monitoring')
        group.add(Adw.ActionRow(title=esc('Network monitor: curl, iperf3, reachability checks.')))
        self._group = group
        details.append(group)
        self.append(details)
        self.render({tool: ss.have_tool(tool) for tool, _w in TOOLS})

    def render(self, present: dict) -> None:
        have = [what for tool, what in TOOLS if present.get(tool)]
        # one plain item per thing a person gets, even when two tools give it
        have = list(dict.fromkeys(have))
        if have:
            self._plain.set_state('ok', 'These checks are available', ", ".join(have).capitalize() + ".")
        else:
            self._plain.set_state("info", 'No network check is installed', 'Nothing to do.')
        for tool, what in TOOLS:
            self._group.add(Adw.ActionRow(
                title=esc(tool),
                subtitle=esc(f"installed - {what}" if present.get(tool) else "not installed")))
