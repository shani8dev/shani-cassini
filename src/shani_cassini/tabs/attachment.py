# Enrichment 2026-10-25: shani-health / matrix binary reference; read-only / privileged button per AGENTS.md.
"""Attachment / archive drop reporter — read-only inventory of the archive formats this machine can open. Surface: attachment (matrix).

Leads with a plain summary of what is installed, checked with have_tool()
rather than stated: the rows that used to say "nothing installed" were
written without looking."""
from gi.repository import Gtk, Adw

from shani_cassini import system_status as ss
from shani_cassini.plain import Details, Summary, esc

# (tool, what it gives a person)
TOOLS = [('unzip', '.zip files'), ('7z', '.7z files'), ('7za', '.7z files'), ('bzip2', '.bz2 files'), ('xz', '.xz files'), ('zstd', '.zst files'), ('unar', 'almost any archive')]


class AttachmentTab(Gtk.Box):
    def __init__(self, state=None, auth_manager=None) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self._plain = Summary('Archives', 'Which compressed files (.zip, .7z, .tar.xz…) this computer can open.')
        self.append(self._plain)
        details = Details(subtitle="Which tools are installed")
        group = Adw.PreferencesGroup(title='Dropped archives')
        group.add(Adw.ActionRow(title=esc('Attachment / file-drop reporter (7z, bzip2, unarchiver).')))
        self._group = group
        details.append(group)
        self.append(details)
        self.render({tool: ss.have_tool(tool) for tool, _w in TOOLS})

    def render(self, present: dict) -> None:
        have = [what for tool, what in TOOLS if present.get(tool)]
        # one plain item per thing a person gets, even when two tools give it
        have = list(dict.fromkeys(have))
        if have:
            self._plain.set_state('ok', 'This computer can open these archives', ", ".join(have).capitalize() + ".")
        else:
            self._plain.set_state("info", 'No archive tool is installed', 'Archives cannot be opened until one is. Updating the system usually brings them back.')
        for tool, what in TOOLS:
            self._group.add(Adw.ActionRow(
                title=esc(tool),
                subtitle=esc(f"installed - {what}" if present.get(tool) else "not installed")))
