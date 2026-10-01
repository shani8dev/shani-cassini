"""Audio: the PipeWire graph, which is more than a volume slider.

GNOME Control Center's Sound panel is a volume slider, an output picker and an
input-volume slider. What PipeWire actually is — which devices exist, which
sinks and sources they expose, which of those is the session default, and which
programs are connected right now — has no panel in either settings app.

**The default device is a fact worth having.** wpctl marks it with `*` before
the node id, and this page reports which node that is, per section. It is the
single most useful row on the page: "which output is sound coming out of" is a
question a volume slider cannot answer.

**Audio and Video headings reuse the same words.** wpctl prints `Sinks:` under
both Audio and Video, so a parse that keys on the heading alone files the camera
under the audio sinks and reports the camera as the default *microphone*. The
heading is therefore never used alone: every list and every default is keyed on
the section and the heading together, which is why this page can say "default
input" and mean the microphone.

**The `*` marker survives the tree-stripping, deliberately.** wpctl indents with
box characters, and stripping them is what lets the headings be recognised. The
first version of the tree stripper also ate `*`, because it was in the same
character class — so every node came back "not the default" on a machine whose
default sink was plainly marked. The star is the one character that must not be
stripped, and the regex says so.

**Clients are programs, not hardware.** wpctl files running applications under
`Clients:` and everything else under a heading, and the *line itself* does not
say which it is. They are listed under their own heading rather than being
folded into "devices", because "your browser is connected to PipeWire" and "you
have this sound card" are different facts and a page that merged them would be
inventing a relationship wpctl never claimed.

**This page sets no volumes.** `wpctl set-volume` is a state change on the
running session, and GNOME's own panel already owns that one — doing it in two
places is exactly the duplication this app's read-only-reporter rule exists to
avoid. So it reports the graph and names the commands.
"""

from __future__ import annotations

import logging

from gi.repository import Adw, GLib, Gtk  # type: ignore

from shani_cassini import system_status as ss

logger = logging.getLogger(__name__)

SERVER_NOTE = (
    "The PipeWire server this session is talking to, and its version."
)
DEVICES_NOTE = (
    "Hardware PipeWire can see. A device with no entry here is not plugged in, "
    "or the driver for it is not loaded."
)
OUTPUTS_NOTE = (
    "Where sound can go. The one marked Default is where it is going now."
)
INPUTS_NOTE = (
    "Where sound can come from. The one marked Default is what a call or a "
    "recording would use."
)
PROGRAMS_NOTE = (
    "Programs connected to PipeWire right now. This is what you close to fix "
    "“the sound is still coming from the browser”."
)
DOES_NOT_NOTE = (
    "Nothing on this page changes a volume or moves the default device — GNOME "
    "and Plasma already own that, and two places to set it is two places to "
    "keep honest.\n"
    "  wpctl status                 the whole graph\n"
    "  wpctl set-volume @DEFAULT_SINK 30%   one level\n"
    "  pactl list short sinks       the PulseAudio view of it"
)


def _esc(value: object) -> str:
    return GLib.markup_escape_text(str(value), -1)


def _row(title: str, subtitle: str = "") -> Adw.ActionRow:
    row = Adw.ActionRow(title=title, subtitle=subtitle)
    row.set_subtitle_selectable(True)
    return row


class AudioTab(Gtk.Box):
    def __init__(self, state=None, auth_manager=None) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self._state = state
        self._auth_manager = auth_manager
        self._toasts = Adw.ToastOverlay()
        self.append(self._toasts)
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self._toasts.set_child(page)

        self._added: list[tuple[Adw.PreferencesGroup, Adw.ActionRow]] = []
        self._busy = False

        self._server = Adw.PreferencesGroup(title="Session",
                                            description=SERVER_NOTE)
        self._row_server = _row("PipeWire", "Reading…")
        self._btn_read = Gtk.Button(label="Read", valign=Gtk.Align.CENTER)
        self._btn_read.connect("clicked", lambda *_: self.load())
        self._row_server.add_suffix(self._btn_read)
        self._server.add(self._row_server)

        self._devices_group = Adw.PreferencesGroup(title="Devices",
                                                   description=DEVICES_NOTE)
        self._outputs_group = Adw.PreferencesGroup(title="Outputs",
                                                   description=OUTPUTS_NOTE)
        self._inputs_group = Adw.PreferencesGroup(title="Inputs",
                                                  description=INPUTS_NOTE)
        self._programs_group = Adw.PreferencesGroup(title="Connected programs",
                                                    description=PROGRAMS_NOTE)

        guide = Adw.PreferencesGroup(title="What this page does not do")
        guide.add(_row("Volumes and default devices", DOES_NOT_NOTE))

        for group in (self._server, self._devices_group, self._outputs_group,
                      self._inputs_group, self._programs_group, guide):
            page.append(group)

        self.load()

    # ------------------------------------------------------------------ data
    def load(self) -> None:
        if self._busy:
            return
        self._busy = True
        self._btn_read.set_sensitive(False)
        self._btn_read.set_label("Reading…")
        self._row_server.set_subtitle("Reading…")

        def done(payload, _error: str) -> None:
            self._busy = False
            self._btn_read.set_sensitive(True)
            self._btn_read.set_label("Read")
            self._render(payload)

        ss.pipewire_status(done)

    # -------------------------------------------------------------- rendering
    def _render(self, payload: dict) -> None:
        for group in (self._devices_group, self._outputs_group,
                      self._inputs_group, self._programs_group):
            self._clear(group)

        if not payload.get("ok"):
            self._row_server.set_subtitle(payload["problem"])
            for group in (self._devices_group, self._outputs_group,
                          self._inputs_group, self._programs_group):
                group.set_visible(False)
            return
        for group in (self._devices_group, self._outputs_group,
                      self._inputs_group, self._programs_group):
            group.set_visible(True)

        self._row_server.set_subtitle(payload["server"] or "Connected")

        devices = payload["audio_devices"]
        self._devices_group.set_description(
            DEVICES_NOTE if devices else
            DEVICES_NOTE + "\nPipeWire reports no audio hardware on this machine.")
        for node in devices:
            self._add(self._devices_group, _node_row(node))

        self._render_endpoints(self._outputs_group, payload["audio_sinks"],
                               "No outputs — nothing can play audio here.")
        self._render_endpoints(self._inputs_group, payload["audio_sources"],
                               "No inputs — nothing can record from here.")

        programs = payload["programs"]
        self._programs_group.set_description(
            PROGRAMS_NOTE if programs else
            PROGRAMS_NOTE + "\nNo application is connected to PipeWire.")
        for node in programs:
            self._add(self._programs_group,
                      _row(_esc(node["name"] or f"node {node['id']}"),
                           _esc(node["flags"])))

    def _render_endpoints(self, group, nodes: list, empty: str) -> None:
        if not nodes:
            group.set_description(empty)
            return
        group.set_description(OUTPUTS_NOTE if group is self._outputs_group
                              else INPUTS_NOTE)
        for node in nodes:
            self._add(group, _node_row(node))

    def _clear(self, group) -> None:
        for owner, row in self._added:
            if owner is group:
                group.remove(row)
        self._added = [(o, r) for o, r in self._added if o is not group]

    def _add(self, group, row: Adw.ActionRow) -> None:
        group.add(row)
        self._added.append((group, row))


def _node_row(node: dict) -> Adw.ActionRow:
    """One endpoint, with the default marked rather than described in prose."""
    row = _row(_esc(node["name"] or f"node {node['id']}"),
               _esc(node["flags"] or f"node {node['id']}"))
    if node.get("default"):
        img = Gtk.Image.new_from_icon_name("audio-volume-high-symbolic")
        row.add_prefix(img)
        row.set_subtitle(_esc(
            (node["flags"] + " · " if node["flags"] else "") + "Default"))
    return row
