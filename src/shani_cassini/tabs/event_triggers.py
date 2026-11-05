# Enrichment 2026-10-25: shani-health / matrix binary reference; read-only / privileged button per AGENTS.md.
"""Event / trigger reporter — surface: trigger (matrix). Reports D-Bus signals, USB plug events, journal arrival events. Read-only, no privileged load.

Leads with a plain summary of what is installed, checked with have_tool()
rather than stated: the rows that used to say "nothing installed" were
written without looking."""
from gi.repository import Gtk, Adw

from shani_cassini import system_status as ss
from shani_cassini.plain import Details, Summary, esc

# (tool, what it gives a person)
TOOLS = [('udevadm', 'devices being plugged in'), ('journalctl', 'messages as they are logged'), ('busctl', 'messages between apps')]


class EventTriggersTab(Gtk.Box):
    def __init__(self, state=None, auth_manager=None) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self._plain = Summary('Event Sources', 'How the system hears about things as they happen: a device plugged in, a message logged.')
        self.append(self._plain)
        details = Details(subtitle="Which tools are installed")
        group = Adw.PreferencesGroup(title='Event sources')
        group.add(Adw.ActionRow(title=esc('Trigger / event reporter: D-Bus, USB plug, journal events.')))
        self._group = group
        details.append(group)
        self.append(details)
        self.render({tool: ss.have_tool(tool) for tool, _w in TOOLS})

    def render(self, present: dict) -> None:
        have = [what for tool, what in TOOLS if present.get(tool)]
        # one plain item per thing a person gets, even when two tools give it
        have = list(dict.fromkeys(have))
        if have:
            self._plain.set_state('ok', 'The system can report events as they happen', ", ".join(have).capitalize() + ".")
        else:
            self._plain.set_state("info", 'No event tool is installed', 'Nothing to do.')
        for tool, what in TOOLS:
            self._group.add(Adw.ActionRow(
                title=esc(tool),
                subtitle=esc(f"installed - {what}" if present.get(tool) else "not installed")))
