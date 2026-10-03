"""UPS: whether the machine will survive losing power.

`apcupsd` is in every image profile's package list and there is **no panel for
it in either desktop** - GNOME's 28 panels and Plasma's 62 System Settings
modules were both enumerated from the packages themselves, and neither contains
anything about a UPS. Plasma's `powerdevilprofilesconfig` is about power
*profiles* (performance vs. balanced), which is a different question from
whether the machine is about to shut down.

The fact that makes this page worth having is what the shipped configuration
actually says. Arch's `apcupsd` package writes a `DEVICE
/dev/usb/hid/hiddev[0-9]` line and leaves **every `UPSNAME` line commented
out** - so out of the box there is a device pattern to watch and nothing to
call it. That is not a broken daemon, and it is not a healthy UPS either; it
is the third state, and it is the one a desktop gives a user no way to see.

**No status values are parsed, on purpose.** `apcaccess status` prints a block
of `KEY : VALUE` lines, but there is no UPS on any machine this was written on
and apcupsd cannot be made to answer without one, so the exact shape was never
observed. A panel that guessed it would put numbers on screen that no tool
produced - the failure this repo has removed more than once. The tool's own
output is shown verbatim instead, and only the configuration file and
systemd's answer about the daemon are interpreted.

Read-only. Configuring a UPS means plugging one in and naming it.
"""

from __future__ import annotations

import logging

from gi.repository import Adw, GLib, Gtk  # type: ignore

from shani_cassini import system_status as ss

logger = logging.getLogger(__name__)

SUMMARY_NOTE = (
    "What the machine knows about a UPS: the shipped configuration, whether "
    "the daemon is running, and what apcupsd itself reports. Read-only."
)

SETUP_NOTE = (
    "Out of the box no UPS is configured, so there is nothing here to report "
    "and nothing is wrong.\n"
    "To use one, plug it in and name it in `/etc/apcupsd/apcupsd.conf`:\n"
    "  UPSNAME a-name-you-choose\n"
    "  DEVICE  /dev/usb/hid/hiddev0\n"
    "then `sudo systemctl restart apcupsd`. The device line is already there "
    "in a form that matches any hiddev; the name is the missing half."
)

READ_NOTE = (
    "Nothing on this page changes the daemon, the configuration or the UPS.\n"
    "  apcaccess status       everything apcupsd reports, as it reports it\n"
    "  systemctl status apcupsd"
)


def _row(title: str, subtitle: str = "") -> Adw.ActionRow:
    return Adw.ActionRow(title=title, subtitle=subtitle)


class UpsTab(Gtk.Box):
    def __init__(self, state=None, auth_manager=None) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self._state = state
        self._auth_manager = auth_manager
        self._page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self.append(self._page)
        self._build()
        GLib.idle_add(self.load)

    def _build(self) -> None:
        self._summary = Adw.PreferencesGroup(title="UPS", description=SUMMARY_NOTE)
        self._row_config = _row("Configuration", "Reading…")
        self._summary.add(self._row_config)
        self._row_service = _row("apcupsd service", "Reading…")
        self._summary.add(self._row_service)
        self._page.append(self._summary)

        self._setup_group = Adw.PreferencesGroup(
            title="Setting one up", description=SETUP_NOTE)
        self._page.append(self._setup_group)

        self._raw_group = Adw.PreferencesGroup(
            title="Reported by apcupsd",
            description=("Shown exactly as the tool prints it. No value on "
                         "this page is interpreted, so nothing here can be "
                         "misread as a measurement Cassini made."))
        self._raw_label: Gtk.Label | None = None
        self._page.append(self._raw_group)

        self._page.append(Adw.PreferencesGroup(
            title="Reading it yourself", description=READ_NOTE))

    def load(self) -> bool:
        ss.ups_state(self._on_state)
        return False

    def _clear_raw(self) -> None:
        if self._raw_label is not None:
            self._raw_group.remove(self._raw_label)
            self._raw_label = None

    def _show_raw(self, text: str) -> None:
        self._clear_raw()
        label = Gtk.Label(label=text, selectable=True, xalign=0.0, wrap=True)
        label.add_css_class("monospace")
        label.add_css_class("dim-label")
        self._raw_group.add(label)
        self._raw_label = label

    def _on_state(self, state: dict, err: str) -> None:
        if not state.get("installed"):
            self._row_config.set_subtitle(err or "apcupsd is not installed")
            self._row_service.set_subtitle("Not installed")
            self._clear_raw()
            return

        if state.get("configured"):
            name = state.get("name") or "(unnamed)"
            self._row_config.set_subtitle(f"UPS configured as {name}")
            self._setup_group.set_visible(False)
        else:
            # The common case, and the one worth stating plainly rather than
            # leaving as an empty row: a DEVICE pattern with no name.
            device = state.get("device") or ""
            self._row_config.set_subtitle(
                f"No UPS configured (device pattern {device}, no name)"
                if device else "No UPS configured")
            self._setup_group.set_visible(True)

        service = state.get("service")
        if service is True:
            self._row_service.set_subtitle("Running")
        elif service is False:
            self._row_service.set_subtitle("Not running")
        else:
            self._row_service.set_subtitle("Unknown")

        raw = (state.get("status") or "").strip()
        if raw:
            self._show_raw(raw)
        else:
            self._clear_raw()
