"""WireGuard: the interfaces on this machine, and whether each one is on.

Reads `/etc/wireguard/*.conf` for what exists, and asks systemd for
`wg-quick@<iface>.service` for what is running. A switch per interface starts
and stops it.

**No `wg show`.** A first version's docstring said the page read peers from
`wg show`, and it never called it: peers are the contents of the encrypted
files, `wg show dump` exposes the private keys of every peer to anything that
can read `/proc`, and nothing here needs them. The claim was removed with the
implementation that never existed, rather than left to mislead the next reader.

**How it authorises, since `services.py` is the model.** Changes go through
`systemctl` itself, so systemd asks polkit over D-Bus and the desktop's own
password dialog appears - no `pkexec`, and no program for this page to name.
`tests/test_service_toggle_pages.py` asserts that, along with `systemctl` being
the only binary either page runs.

**An interface name is validated before it becomes a unit name.** The names come
from `os.listdir("/etc/wireguard")`, which is root-owned - so this is not an
exploit today, and a filename cannot inject an argv element without a shell
anyway. It matters because the name is interpolated into
`wg-quick@{iface}.service` and this page then asks systemd to *enable* that
unit: a bounded token is a much smaller thing to hand to systemd than an
arbitrary string is. `IFACE_RE` is Linux's own rule for an interface name
(`[A-Za-z_][A-Za-z0-9_-]{0,14}`), not one invented here.

**Not a tunnel manager.** It will not create a key, generate a peer, or edit a
`PrivateKey`. `wg-quick` owns all of that.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
from typing import Final

from gi.repository import Adw, GLib, Gtk  # type: ignore

from shani_cassini import system_status as ss

logger = logging.getLogger(__name__)

CONF_DIR: Final = "/etc/wireguard"

# Linux's own rule for an interface name, from `dev_valid_name()` in
# drivers/net/ethernet/eth.c. A name outside this cannot be a real interface,
# so it is not something to hand systemd as a unit name either.
IFACE_RE: Final = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]{0,14}$")

# systemd can take a while to answer, and the password dialog is part of that.
PRIV_TIMEOUT: Final = 60


def valid_ifaces(directory: "str | None" = None) -> list[str]:
    """The interfaces in `directory` whose name this page is willing to use.

    **The default is resolved inside the body, not in the signature.** A module
    constant as a default argument is evaluated once at definition time, so
    `valid_ifaces(directory=CONF_DIR)` made the function permanently ignore a
    later reassignment of `CONF_DIR` - which is exactly the kind of thing a test
    needs to do, and which silently made the test impossible rather than failing.
    """
    directory = CONF_DIR if directory is None else directory
    if not os.path.isdir(directory):
        return []
    names = []
    for entry in os.listdir(directory):
        if not entry.endswith(".conf"):
            continue
        name = entry[: -len(".conf")]
        if IFACE_RE.match(name):
            names.append(name)
        else:
            logger.warning("skipping %s: %r is not a valid interface name",
                           entry, name)
    return sorted(names)


def unit_for(iface: str) -> str:
    """The unit name, and only ever for a name that already passed `IFACE_RE`.

    Re-checked here rather than trusted from the caller: this is the last point
    before the name reaches systemd, and the cost of the check is a regex.
    """
    if not IFACE_RE.match(iface):
        raise ValueError(f"not an interface name: {iface!r}")
    return f"wg-quick@{iface}.service"


class WireGuardTab(Gtk.Box):
    def __init__(self, state=None, auth_manager=None) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        self._state = state
        self._auth_manager = auth_manager

        self._toasts = Adw.ToastOverlay()
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        self._toasts.set_child(page)
        self.append(self._toasts)

        self._group = Adw.PreferencesGroup(
            title="WireGuard Interfaces",
            description=("Each interface named in /etc/wireguard, and whether "
                         "its per-interface service is running. Use a switch to "
                         "start or stop one."))
        page.append(self._group)

        self._summary = Adw.PreferencesGroup(
            title="What this is",
            description=(
                "WireGuard is a peer-to-peer tunnel that needs a reachable "
                "address, which is exactly the problem a dynamic address "
                "causes. That is the one thing to check before relying on it: "
                "if this machine is behind a router doing NAT, a peer cannot "
                "open a connection to it unless a port is forwarded, and no "
                "setting on this page can arrange that. The Inbound Access page "
                "has the options that do not need a reachable address."))
        page.append(self._summary)

        # Widgets this page added to _group, so a re-read removes exactly those.
        # Adw.PreferencesGroup exposes no way to enumerate its children, and
        # get_first_child() would walk into rows this page did not build.
        self._rows: list[Adw.ActionRow] = []
        GLib.idle_add(self.refresh)

    # ------------------------------------------------------------------ read
    def refresh(self) -> bool:
        for row in self._rows:
            self._group.remove(row)
        self._rows.clear()

        ifaces = valid_ifaces()
        if not ifaces:
            # The subtitle is Pango markup, so the literal <name> a CLI help
            # text would carry has to be escaped: unescaped, `<name>` parses
            # as an unknown element and the row's label is where the markup
            # error lands - measured as a blank subtitle in the slot render.
            row = Adw.ActionRow(
                title="No interfaces configured",
                subtitle=GLib.markup_escape_text(
                    f"wg-quick reads {CONF_DIR}/<name>.conf; there are "
                    "none yet. This page will not create one - `wg-quick "
                    "genkey` and a config file are the tools' own domain.", -1))
            self._group.add(row)
            self._rows.append(row)
            return False

        for iface in ifaces:
            unit = unit_for(iface)
            active = self._unit_state(unit)
            row = Adw.ActionRow(title=iface)
            row.set_subtitle(f"{iface}.conf · {active}")
            if active == "failed":
                row.add_css_class("error")
            elif active == "active":
                row.add_css_class("success")

            switch = Gtk.Switch(valign=Gtk.Align.CENTER,
                                tooltip_text="Start with the system, and now")
            switch.set_active(active == "active")
            switch.connect("state-set", self._on_switch, unit)
            row.add_suffix(switch)

            self._group.add(row)
            self._rows.append(row)
        return False

    def _unit_state(self, unit: str) -> str:
        """One unit's state, synchronously and safely.

        A file read plus a bounded `systemctl is-active`, rather than the
        async fan-out the readers use: this runs per interface, and a page that
        showed "running" or "not running" from a guess would be worse than one
        that admits it does not know.
        """
        try:
            proc = subprocess.run(["systemctl", "is-active", unit],
                                  capture_output=True, text=True,
                                  timeout=PRIV_TIMEOUT, check=False)
        except (OSError, subprocess.SubprocessError):
            return "state unknown"
        state = proc.stdout.strip()
        return state or "not running"

    # ----------------------------------------------------------------- write
    def _on_switch(self, switch, want_active: bool, unit: str) -> bool:
        """Start or stop one interface.

        Off the main thread: `systemctl --now` blocks on a polkit dialog, and a
        window that cannot repaint through a password prompt reads as a hang.
        `services.py` does the same for the same reason.
        """
        verb = "enable" if want_active else "disable"

        def worker() -> None:
            argv = ["systemctl", verb, "--now", unit]
            try:
                proc = subprocess.run(argv, stdin=subprocess.DEVNULL,
                                      capture_output=True, text=True,
                                      timeout=PRIV_TIMEOUT, check=False)
                code, err = proc.returncode, proc.stderr
            except subprocess.TimeoutExpired:
                code, err = 124, f"{verb} did not answer in {PRIV_TIMEOUT}s\n"
            except (OSError, subprocess.SubprocessError) as exc:
                code, err = 1, f"{verb} could not be run: {exc}\n"
            GLib.idle_add(self._done, code, err, switch, want_active)

        GLib.Thread.new(f"wg-{verb}", worker).start()
        return False

    def _done(self, code: int, err: str, switch: Gtk.Switch,
              want_active: bool) -> bool:
        if code != 0:
            # systemd's own words, not a generic failure: 126 is a dismissed
            # dialog and 127 is a refusal, and telling a user their passphrase
            # was wrong when they cancelled the dialog is worse than silence.
            if code == 126:
                message = "Cancelled at the password prompt, so nothing changed"
            elif code == 127:
                message = "Not authorised, so nothing changed"
            else:
                message = " ".join(
                    line for line in err.splitlines() if line.strip())[-240:]
            toast = Adw.Toast(title=GLib.markup_escape_text(
                message or f"systemctl exited {code}"))
            self._toasts.add_toast(toast)
            # Put the switch back: `systemctl` is the only thing that knows.
            switch.handler_block_by_func(self._on_switch)
            switch.set_active(not want_active)
            switch.handler_unblock_by_func(self._on_switch)
        GLib.timeout_add(500, lambda: (self.refresh(), False)[1])
        return False