"""The UPS page, now against NUT.

What changed and why: apcupsd had had no upstream release since 3.14.14
(2016/2017) while NUT is at 2.8.5 with its data model published as IETF RFC
9271, 170+ manufacturers across serial/USB/SNMP/IPMI, and an `apcupsd-ups` driver
that still reaches apcupsd-controlled hardware. So the daemon and the file this
page edits both changed, and the page was rewritten against the real thing
rather than assumed.

**What this page can and cannot configure, stated plainly.** apcupsd's page
offered BATTERYLEVEL / MINUTES / TIMEOUT / KILLDELAY - a percentage-based
shutdown threshold you could move. **NUT has no direct equivalent, and that is a
real reduction rather than a rename.** upsmon acts on the UPS *hardware's own*
low-battery signal: the driver reports the device's own LOWBATT state and
upsmon responds. Getting a charge- or runtime-based trigger instead requires
`dummy-ups` with overridden `battery.charge`/`battery.runtime` plus `upssched`,
which is a deliberate advanced setup and not a default this page should build.

So what is configurable here is the SHAPE of the response - how long to wait,
what to run, and what counts as "the UPS has gone away" - and that is what
`upsmon.conf` holds. The page says this rather than implying a battery
percentage knob that does not exist, because a page whose row promises a
threshold it cannot set is the exact failure this repo keeps finding.

The device itself (`ups.conf`) is deliberately NOT editable here. Which driver
and which port are facts about the hardware, and `nut-scanner -U` writes the
right section without the user having to know their own UPS's protocol - so the
page points at it instead of offering a field to get wrong.
"""

from __future__ import annotations

import logging
import pathlib
import re
import threading

from gi.repository import Adw, GLib, Gtk  # type: ignore

from shani_cassini import config_edit as ce
from shani_cassini import system_status as ss


SUMMARY_NOTE = (
    "Whether the daemon is running, what it is monitoring, and the policy that "
    "decides what happens when the power goes. The policy is editable below."
)

SETUP_NOTE = (
    "Out of the box nothing is configured, so there is nothing to report and "
    "nothing is wrong.\n"
    "Find your UPS first - NUT ships a scanner that needs no guessing from "
    "you:\n"
    "  sudo nut-scanner -U\n"
    "It prints a ready-to-paste section for `/etc/nut/ups.conf`, naming the "
    "driver and port your hardware actually needs. That is why this page does "
    "not offer those two as fields: which protocol a UPS speaks is a fact about "
    "the device, and a wrong value fails as a driver that exits silently.\n"
    "A restart is required. NUT reads these files once, at startup. Saving "
    "changes the file and not the machine until you run "
    "`sudo systemctl restart nut-server.service nut-monitor.service`."
)

READ_NOTE = (
    "Nothing here changes the daemon, and nothing here talks to the UPS.\n"
    "  upsc myups@localhost   everything NUT reports, as it reports it\n"
    "  systemctl status nut-monitor.service"
)


def _row(title: str, subtitle: str = "") -> Adw.ActionRow:
    return Adw.ActionRow(title=title, subtitle=subtitle)


# NUT's shutdown policy. This is a DIRECTIVE file: `KEY value`, one per line,
# with no `=` and no sections - which is a different shape from the INI-like
# ups.conf and upsd.users sitting beside it, and the reason the writer picks the
# separator per file instead of assuming one.
#
# These are the settings that decide what the machine DOES, and each fails in the
# direction worth naming:
#   MINSUPPLIES  - how many supplies must be on battery before shutdown starts.
#                  0 is accepted by upsmon and can then never fire.
#   SHUTDOWNCMD  - the command that brings the machine down. Unquoted, only its
#                  first word is a command and the rest become arguments nothing
#                  reads, so a shutdown that silently never happens.
#   POWERDOWNFLAG- the flag file telling the driver to cut UPS power once the
#                  machine is down.
#   DEADTIME     - seconds of no answer before the UPS is declared gone. When it
#                  fires, upsmon treats that as on-battery, because an
#                  unreachable UPS is indistinguishable from a dead one.
#   FINALDELAY   - seconds between running SHUTDOWNCMD and exiting.
POLICY: tuple[tuple[str, str, str], ...] = (
    ("MINSUPPLIES", "Supplies that must fail before shutting down", "1"),
    ("SHUTDOWNCMD", "Command that brings the machine down", '"/sbin/shutdown -h +0"'),
    ("POWERDOWNFLAG", "Flag file telling the UPS to cut power", "/etc/killpower"),
    ("DEADTIME", "Seconds of silence before the UPS counts as gone", "15"),
    ("FINALDELAY", "Seconds after shutdown before upsmon exits", "0"),
    ("POLLFREQ", "Seconds between checks on mains", "5"),
    ("POLLFREQALERT", "Seconds between checks on battery", "5"),
)

# What each key accepts. INT keys are whole seconds or a count; CMD is a quoted
# shell command; PATH must be absolute. The bounds are the ones the helper's
# validator enforces; they are repeated here so the user gets the answer without
# an administrator authentication for a value that was never going to be
# accepted.
POLICY_KIND: dict[str, str] = {
    "MINSUPPLIES": "INT",
    "SHUTDOWNCMD": "CMD",
    "POWERDOWNFLAG": "PATH",
    "DEADTIME": "INT",
    "FINALDELAY": "INT",
    "POLLFREQ": "INT",
    "POLLFREQALERT": "INT",
}

POLICY_BOUNDS: dict[str, tuple[int, int]] = {
    "MINSUPPLIES": (1, 8),
    "DEADTIME": (1, 600),
    "FINALDELAY": (0, 600),
    "POLLFREQ": (1, 600),
    "POLLFREQALERT": (1, 600),
}

# The keys this page never offers. `upsd.users` holds the credential that can
# force a UPS power-down, so it is generated once by shani-settings' install
# hook and is not something a settings window should be able to rewrite; the
# device section in ups.conf is nut-scanner's job for the reason above.
NOT_EDITABLE: tuple[tuple[str, str], ...] = (
    ("upsd.users", "holds the credential that can force a UPS power-down. "
                   "Generated once at install; not editable from a window."),
    ("ups.conf", "the device - which driver, which port. `sudo nut-scanner -U` "
                 "writes the right one for your hardware."),
)


class UpsTab(Gtk.Box):
    def __init__(self, state=None, auth_manager=None) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self._state = state
        self._auth_manager = auth_manager
        self._page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        # A ToastOverlay because this page now has a Save that can be refused.
        self._toasts = Adw.ToastOverlay()
        self._toasts.set_child(self._page)
        self._toast = self._toasts
        self.append(self._toasts)
        self._build()
        GLib.idle_add(self.load)

    def _build(self) -> None:
        self._summary = Adw.PreferencesGroup(
            title="Uninterruptible power", description=SUMMARY_NOTE)
        self._row_state = _row("Status", "Reading…")
        self._row_service = _row("nut-monitor service", "Reading…")
        self._summary.add(self._row_state)
        self._summary.add(self._row_service)
        self._page.append(self._summary)

        self._not_editable = Adw.PreferencesGroup(
            title="Not editable from here", description="Two NUT files are deliberately absent, and saying why beats a "
                           "page that looks like it can do something it cannot.")
        for name, why in NOT_EDITABLE:
            self._not_editable.add(_row(name, why))
        self._page.append(self._not_editable)

        self._edit = Adw.PreferencesGroup(
            title="What happens when the power goes",
            description="NUT has no battery-percentage threshold: upsmon responds to "
                "the UPS's own low-battery signal. What is set here is the "
                "shape of the response - how long to wait, what to run, and "
                "when an unreachable UPS counts as gone.")
        self._entries: dict[str, Gtk.Entry] = {}
        self._rows: dict[str, Adw.ActionRow] = {}
        self._saves: dict[str, Gtk.Button] = {}
        for key, subtitle, _default in POLICY:
            # **The explanation is on the row, not only in a tooltip. Found by
            # rendering (2026-10-17): seven rows of bare uppercase keys -
            # `MINSUPPLIES`, `SHUTDOWNCMD`, `POWERDOWNFLAG` - each with an empty
            # entry, and the one sentence explaining what any of them means
            # living in a tooltip. Nothing in the capture said what a reader is
            # being asked to type, and a tooltip is invisible on a touch screen
            # and to anyone who does not know to hover.
            #
            # **An `Adw.ActionRow` with a `Gtk.Entry` suffix, not an
            # `Adw.EntryRow`.** `Adw.EntryRow` has no subtitle at all -
            # `set_subtitle` does not exist on it (measured: `dir()` returns
            # only `get_title`/`set_title` and their `_selectable` twins) - so
            # the first attempt raised `AttributeError` and the page rendered as
            # "UPS could not be loaded".
            #
            # And **`Gtk.Entry`, not `Adw.Entry`** — there is no `Adw.Entry`
            # class; the second attempt raised on that too, which is two
            # AttributeErrors for one change and is why it is written down here.
            # `Gtk.Entry` carries the same `get_text` / `set_text` /
            # `set_sensitive` this page already calls on the row, so every call
            # site below is unchanged.
            row = Adw.ActionRow(title=key, subtitle=subtitle)
            row.set_tooltip_text(subtitle)
            entry = Gtk.Entry()
            entry.set_valign(Gtk.Align.CENTER)
            entry.set_hexpand(True)
            entry.set_width_chars(18)
            save = Gtk.Button(label="Save", valign=Gtk.Align.CENTER,
                              css_classes=["suggested-action"])
            save.connect("clicked", self._on_save_clicked, key)
            row.add_suffix(entry)
            row.add_suffix(save)
            self._edit.add(row)
            self._entries[key] = entry
            self._rows[key] = row
            self._saves[key] = save
        self._page.append(self._edit)

        self._raw_group = Adw.PreferencesGroup(
            title="Reported by NUT", description=READ_NOTE)
        self._raw_rows: list[Adw.ActionRow] = []
        self._page.append(self._raw_group)

    def load(self) -> bool:
        ss.ups_state(self._on_state)
        return False

    # -- the one write on this page ------------------------------------------

    def _on_save_clicked(self, _button, key: str) -> None:
        """Validate here, so a typo costs a message rather than a password."""
        row = self._entries[key]
        raw = (row.get_text() or "").strip()
        kind = POLICY_KIND[key]

        bad = None
        if kind == "INT":
            low, high = POLICY_BOUNDS[key]
            if not raw.isdigit() or not (low <= int(raw) <= high):
                bad = f"{key} takes a whole number from {low} to {high}"
        elif kind == "PATH":
            if not raw.startswith("/"):
                bad = f"{key} must be an absolute path"
        elif kind == "CMD":
            # Quoted, because unquoted only the first word is a command and the
            # rest become arguments nothing reads - a shutdown that never runs.
            if not (raw.startswith('"') and raw.endswith('"') and len(raw) >= 2):
                bad = f"{key} must be quoted, e.g. \"/sbin/shutdown -h +0\""

        if bad is not None:
            row.add_css_class("error")
            self._toast.add_toast(Adw.Toast(title=GLib.markup_escape_text(bad)))
            return
        row.remove_css_class("error")

        current = ce.read_config(LOCAL_UPSMON_CONF)
        if current is None:
            self._toast.add_toast(Adw.Toast(
                title="There is no /etc/nut/upsmon.conf on this machine"))
            return
        if raw:
            new_text, what = ce.set_key(current, key, raw)
        else:
            new_text, removed = ce.remove_key(current, key)
            what = "removed" if removed else "unchanged"
        if what == "duplicate":
            self._toast.add_toast(Adw.Toast(
                title=f"{key} is set more than once in that file, so this page "
                      "cannot tell which one upsmon reads"))
            return
        if what == "unchanged":
            self._toast.add_toast(Adw.Toast(title="Already at that value"))
            return

        for entry in self._entries.values():
            entry.set_sensitive(False)

        def run() -> None:
            def done(error: str, note: str) -> None:
                GLib.idle_add(self._saved, key, error)
            ce.save(LOCAL_UPSMON_CONF, new_text, done)

        threading.Thread(target=run, daemon=True).start()

    def _saved(self, key: str, error: str) -> bool:
        for entry in self._entries.values():
            entry.set_sensitive(True)
        if error:
            self._toast.add_toast(Adw.Toast(
                title=GLib.markup_escape_text(error[:300])))
            return False
        self._toast.add_toast(Adw.Toast(
            title=f"{key} saved. Restart nut-monitor.service to make it live"))
        self.load()
        return False

    # -- reporting -------------------------------------------------------------

    def _render_policy(self) -> None:
        """What each setting is set to now, read from the file rather than from
        what this page last wrote - so a hand-edit in a terminal shows up here.
        """
        for key, _subtitle, _default in POLICY:
            value = ce.conf_value(LOCAL_UPSMON_CONF, key)
            row = self._entries[key]
            if row.get_text() != value:
                row.set_text(value)

    def _on_state(self, state: dict, err: str) -> None:
        self._render_policy()

        # not installed is its own answer, and not a fault: a machine with no
        # /etc/nut/upsmon.conf has nothing monitored and nothing wrong.
        if not state.get("installed", True):
            self._row_state.set_subtitle(
                state.get("error") or "NUT is not configured on this machine")
            self._row_service.set_subtitle("Not installed")
            return

        monitor = state.get("monitor", "")
        name = state.get("name", "")
        if monitor:
            self._row_state.set_subtitle(f"Monitoring {name or '(unnamed)'}")
        else:
            self._row_state.set_subtitle(
                "No UPS configured - nothing is being watched")

        # systemctl's failure to say is not evidence the daemon is down, so the
        # three outcomes are kept apart rather than folded into "stopped".
        service = state.get("service")
        if service is None:
            self._row_service.set_subtitle("Unknown")
        elif service:
            self._row_service.set_subtitle("Running")
        else:
            self._row_service.set_subtitle("Not running")

        # The tool's own output, verbatim. `upsc` prints `KEY : VALUE` lines, but
        # no UPS was available to observe the exact shape, so deriving a number
        # from them would put a figure on screen that no tool produced.
        status = (state.get("status") or "").strip()
        if status:
            row = _row("Reported by upsc", status)
            row.set_selectable(True) if hasattr(row, "set_selectable") else None
            self._raw_rows.append(row)
            self._raw_group.add(row)


# NUT's upsmon.conf - the shutdown policy. The device section in ups.conf is
# nut-scanner's job, and upsd.users is generated at install, so neither is
# editable from here (see NOT_EDITABLE).
LOCAL_UPSMON_CONF: str = "/etc/nut/upsmon.conf"
