# Enrichment 2026-10-25: shani-health / matrix binary reference; read-only / privileged button per AGENTS.md.
"""Voice / accessibility reporter — read-only surface from matrix (voice). No privileged call on load.

Leads with a plain summary of what is installed, checked with have_tool()
rather than stated: the rows that used to say "nothing installed" were
written without looking."""
from gi.repository import Gtk, Adw

from shani_cassini import system_status as ss
from shani_cassini.plain import Details, Summary, esc

# (tool, what it gives a person)
TOOLS = [('orca', 'a screen reader'), ('spd-say', 'speech for apps'), ('espeak-ng', 'a voice')]


class VoiceAccessTab(Gtk.Box):
    def __init__(self, state=None, auth_manager=None) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self._plain = Summary('Voice & Screen Reading', 'A screen reader reads out what is on the screen, for people who cannot see it well.')
        self.append(self._plain)
        details = Details(subtitle="Which tools are installed")
        group = Adw.PreferencesGroup(title='Voice & screen reading')
        group.add(Adw.ActionRow(title=esc('Voice / speech-dispatcher / at-spi registry.')))
        self._group = group
        details.append(group)
        self.append(details)
        self.render({tool: ss.have_tool(tool) for tool, _w in TOOLS})

    def render(self, present: dict) -> None:
        have = [what for tool, what in TOOLS if present.get(tool)]
        # one plain item per thing a person gets, even when two tools give it
        have = list(dict.fromkeys(have))
        if have:
            self._plain.set_state('ok', 'Screen reading is installed', ", ".join(have).capitalize() + ".")
        else:
            self._plain.set_state("info", 'No screen reader is installed', 'Nothing to do unless you need one.')
        for tool, what in TOOLS:
            self._group.add(Adw.ActionRow(
                title=esc(tool),
                subtitle=esc(f"installed - {what}" if present.get(tool) else "not installed")))
