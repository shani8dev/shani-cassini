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
import threading

from gi.repository import Adw, GLib, Gtk  # type: ignore

from shani_cassini import config_edit as ce
from shani_cassini import system_status as ss

logger = logging.getLogger(__name__)

SUMMARY_NOTE = (
    "What the machine knows about a UPS: the shipped configuration, whether "
    "the daemon is running, and what apcupsd itself reports. The shutdown "
    "policy below is the one thing here you can change."
)

SETUP_NOTE = (
    "Out of the box no UPS is configured, so there is nothing here to report "
    "and nothing is wrong.\n"
    "The device line is already in the file in a form that matches any hiddev, "
    "so a UPS is usually detected without configuration. Two things still need "
    "a name - the UPS itself, and which shutdown policy you want - and both are "
    "below.\n"
    "**A restart is required.** apcupsd reads this file once, at startup; its own "
    "header says so. Saving changes the file and not the machine until you run "
    "`sudo systemctl restart apcupsd.service`."
)

EDIT_NOTE = (
    "What the machine does when the power goes, which is the part people come "
    "here to set and the part with consequences either way.\n"
    "Every value is apcupsd's own setting in `/etc/apcupsd/apcupsd.conf`, edited "
    "where apcupsd's package put it and checked before it is written: a value "
    "that would not parse is refused rather than saved.\n"
    "**The daemon reads this file once, at startup.** After a save, run "
    "`sudo systemctl restart apcupsd.service` - the page will say so again rather than "
    "imply the machine has already changed."
)

# apcupsd's own configuration file, edited in place. There is no drop-in
# mechanism and no reason to want one: this is the only file apcupsd reads, and
# its DEVICE/UPSCABLE/UPSTYPE lines are per-machine, so shani-settings cannot
# ship a default that would be right on someone else's hardware.
APCUPSD_CONF: str = "/etc/apcupsd/apcupsd.conf"

# The shutdown policy, and the reason it is these four.
#
# The keys come from apcupsd 3.14.8's own shipped file - `grep -nE '^[A-Z]'`
# gives 25 live settings across 344 lines, the rest being per-key documentation -
# and NOT from the ArchWiki page, which documents the path and `TIMEOUT` and
# then points at the file. **apcupsd.conf is `KEY VALUE`, whitespace-separated,
# with zero `=` characters in it**, which is why the writer picks the separator
# off the file rather than assuming one. (An earlier version of this page's
# validator assumed `KEY=VALUE`, imported from a neighbouring systemd
# EnvironmentFile target, and refused the distribution's own file on its first
# live line.)
#
# These four are what a UPS owner actually comes to set, and each fails in the
# direction worth naming:
#   BATTERYLEVEL - too high and the machine shuts down while the battery is
#                  nearly full; too low and it stays up until the UPS dies.
#   MINUTES      - the same decision expressed as remaining runtime.
#   TIMEOUT      - whether a *timed-out* UPS (nothing said for N seconds) counts
#                  as a failure at all. apcupsd ships this 0, which ignores it.
#   KILLDELAY    - how long before the last resort.
POLICY: tuple[tuple[str, str, str, str], ...] = (
    ("BATTERYLEVEL", "Shut down at this battery percentage", "5", "1-100"),
    ("MINUTES", "...or with this many minutes of runtime left", "3", "whole seconds"),
    ("TIMEOUT", "Treat a timed-out UPS as a failure", "0", "whole seconds"),
    ("KILLDELAY", "Then force it after this many seconds", "0", "whole seconds"),
)

# Every value is whole seconds or a percentage, so one rule covers the four.
# The bounds are the ones the helper's validator enforces; they are repeated
# here so the user gets the answer without an administrator authentication for a
# value that was never going to be accepted.
POLICY_BOUNDS: dict[str, tuple[int, int]] = {
    "BATTERYLEVEL": (1, 100),
    "MINUTES": (0, 9999),
    "TIMEOUT": (0, 9999),
    "KILLDELAY": (0, 9999),
}

READ_NOTE = (
    "Nothing here changes the daemon, and nothing here talks to the UPS.\n"
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
        # A ToastOverlay because this page now has a Save that can be refused.
        # It wraps rather than replaces `_page`, so `_page` stays the plain
        # container every group below appends to.
        self._toasts = Adw.ToastOverlay()
        self._toasts.set_child(self._page)
        self._toast = self._toasts
        self.append(self._toasts)
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

        # The one group that writes.
        self._edit = Adw.PreferencesGroup(
            title="Shutdown policy", description=EDIT_NOTE)
        self._entries: dict[str, Adw.EntryRow] = {}
        self._saves: dict[str, Gtk.Button] = {}
        for key, subtitle, _default, _hint in POLICY:
            row = Adw.EntryRow(title=key, text="")
            row.set_tooltip_text(
                f"{subtitle}. Left empty, the file keeps no {key} line and "
                f"apcupsd uses its own default.")
            save = Gtk.Button(label="Save", valign=Gtk.Align.CENTER,
                              css_classes=["suggested-action"])
            save.connect("clicked", self._on_save_clicked, key)
            row.add_suffix(save)
            self._edit.add(row)
            self._entries[key] = row
            self._saves[key] = save
        self._page.append(self._edit)

        self._raw_group = Adw.PreferencesGroup(
            title="Reported by apcupsd",
            description=("Shown exactly as the tool prints it. No value on "
                         "this page is interpreted, so nothing here can be "
                         "misread as a measurement Cassini made."))
        self._raw_label: Gtk.Label | None = None
        self._page.append(self._raw_group)

        self._page.append(Adw.PreferencesGroup(
            title="Reading it yourself", description=READ_NOTE))

    # -- the one write on this page ------------------------------------------

    def _on_save_clicked(self, _button, key: str) -> None:
        """Range-check here, so a typo costs a message rather than a password.

        These values decide whether the machine goes down when the power does.
        The helper re-checks the same bounds on the far side - this is for the
        user's benefit, not for the file's.
        """
        row = self._entries[key]
        raw = (row.get_text() or "").strip()
        low, high = POLICY_BOUNDS[key]
        # **Empty is a legitimate value and means "remove the line"**, so it is
        # checked before the numeric test rather than after it. The first version
        # tested `raw.isdigit()` unconditionally, so an empty entry - which is
        # exactly how an unset key is shown - was rejected as malformed and the
        # user could never go back to "apcupsd's own default". The error message
        # in that version even advertised "or empty to leave it unset" while the
        # code refused it.
        if raw and (not raw.isdigit() or not (low <= int(raw) <= high)):
            row.add_css_class("error")
            self._toast.add_toast(Adw.Toast(title=GLib.markup_escape_text(
                f"{key} takes a whole number from {low} to {high}, or empty "
                f"to leave it unset")))
            return
        row.remove_css_class("error")

        current = ce.read_config(APCUPSD_CONF)
        if current is None:
            self._toast.add_toast(Adw.Toast(
                title="There is no /etc/apcupsd/apcupsd.conf on this machine"))
            return
        if raw:
            new_text, what = ce.set_key(current, key, raw)
        else:
            new_text, removed = ce.remove_key(current, key)
            what = "removed" if removed else "unchanged"
        if what == "duplicate":
            self._toast.add_toast(Adw.Toast(
                title=f"{key} is set more than once in that file, so this page "
                      "cannot tell which one apcupsd reads"))
            return
        if what == "unchanged":
            self._toast.add_toast(Adw.Toast(title="Already at that value"))
            return

        for entry in self._entries.values():
            entry.set_sensitive(False)

        def run() -> None:
            def done(error: str, note: str) -> None:
                GLib.idle_add(self._saved, key, error)
            ce.save(APCUPSD_CONF, new_text, done)

        threading.Thread(target=run, daemon=True).start()

    def _saved(self, key: str, error: str) -> bool:
        for entry in self._entries.values():
            entry.set_sensitive(True)
        if error:
            self._toast.add_toast(Adw.Toast(
                title=GLib.markup_escape_text(error[:300])))
            return False
        self._toast.add_toast(Adw.Toast(
            title=f"{key} saved. Restart apcupsd.service to make it live"))
        self.load()
        return False

    def _render_policy(self) -> None:
        """What each setting is set to now, read from the file rather than from
        what this page last wrote - so a hand-edit in a terminal shows up here.

        An absent line reads as an empty entry, which is honest: the file sets
        nothing and apcupsd is using its own default.
        """
        for key, _subtitle, default, _hint in POLICY:
            value = ce.conf_value(APCUPSD_CONF, key)
            row = self._entries[key]
            if row.get_text() != value:
                row.set_text(value)
            row.set_tooltip_text(
                f"apcupsd's own default is {default}. Empty means this file "
                f"sets nothing for {key}.")

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
        self._render_policy()
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
