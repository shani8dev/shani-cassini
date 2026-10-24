"""Inbound Access: what could let traffic *reach* this machine.

Most home and mobile connections have a dynamic address behind carrier-grade
NAT. There is nothing to point a DNS record at and no port forward to open, so
the tools that solve that are genuinely useful - and each one is a deliberate
decision to let traffic in.

**Six shipped packages can do it, and on a stock install none of them is on.**
That was verified against the built image's rootfs, not assumed: no unit
symlinked into any systemd target for `cloudflared` or `tailscaled`, no
`/etc/cloudflared` or `~/.cloudflared` tunnel config anywhere, and nothing in
any package's `.install` enabling them. So the defaults are right, and this page
exists because a user who enables one gets no explanation of what they just
turned on.

| Package | Reachable via |
|---|---|
| `cloudflared` | Cloudflare relays, no port forward, no static address |
| `tailscale` | a mesh VPN, via DERP relays when direct paths fail |
| `wireguard-tools` | peer-to-peer, which needs a reachable address |
| `opensssh` | remote shell and port forwarding (Remote Access) |
| `caddy` | listens on a port; serves or reverse-proxies |
| `rclone` | its `serve` modes listen, and can expose local files |

**Inbound access services can be enabled or disabled** - toggling them starts or
stops the service immediately. Configuration (tunnel tokens, auth keys, etc.)
must still be done externally via the appropriate CLI or config files.

**No secret is read or shown.** A tunnel token and an auth key are credentials.
This reports that a configuration exists, never what is in it.
"""

from __future__ import annotations

import logging
from gi.repository import Adw, GLib, Gtk  # type: ignore
from shani_cassini import system_status as ss

logger = logging.getLogger(__name__)

SUMMARY_NOTE = (
    "Six installed packages can make this machine reachable from the network. "
    "This reports which are on. It can also enable or disable them."
)

WHY_NOTE = (
    "Most home and mobile connections have a dynamic address behind "
    "carrier-grade NAT: there is nothing to point a DNS record at, and no port "
    "forward to open. That is why these tools exist.\n"
    "It is also why the default matters. On a stock Shanios install none of "
    "them is enabled and none is configured, so nothing can reach this machine "
    "until you deliberately decide that something should."
)

ON_NOTE = (
    "Something below is active, which means a path into this machine exists "
    "now. Anything listening on 0.0.0.0 rather than 127.0.0.1 is reachable "
    "from the local network as well as from wherever the tunnel leads."
)


def _row(title: str, subtitle: str = "") -> Adw.ActionRow:
    return Adw.ActionRow(title=title, subtitle=subtitle)


class InboundAccessTab(Gtk.Box):
    def __init__(self, state=None, auth_manager=None) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self._state = state
        self._auth_manager = auth_manager
        self._page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        # A ToastOverlay, because _show_error() used to walk the widget tree
        # looking for one: there was none, so every failure reverted the switch
        # in silence and told the user nothing. A failure with no message is
        # indistinguishable from a click that did nothing.
        self._toasts = Adw.ToastOverlay()
        self._toasts.set_child(self._page)
        self.append(self._toasts)
        self._build()
        GLib.idle_add(self.load)

    def _build(self) -> None:
        self._summary = Adw.PreferencesGroup(
            title="Inbound Access", description=SUMMARY_NOTE)
        self._row_state = _row("Nothing is exposed", "Reading…")
        self._summary.add(self._row_state)
        self._page.append(self._summary)

        self._why = Adw.PreferencesGroup(
            title="Why this is a page", description=WHY_NOTE)
        self._page.append(self._why)

        self._on = Adw.PreferencesGroup(title="Active", description=ON_NOTE)
        self._on.set_visible(False)
        self._page.append(self._on)

        self._group = Adw.PreferencesGroup(
            title="Installed mechanisms",
            description="Each row reports what is installed and whether it is "
                        "running. Use the switch to enable or disable the "
                        "service: that asks systemd, which authorises it "
                        "through polkit and shows your own password dialog.")
        self._group.set_visible(False)
        self._page.append(self._group)
        self._rows: list[Adw.ActionRow] = []
        self._unit_for_row: dict[int, str] = {}

    def load(self) -> bool:
        ss.inbound_access_state(self._on_state)
        return False

    def _clear(self) -> None:
        for row in self._rows:
            self._group.remove(row)
        self._rows = []
        self._unit_for_row.clear()

    def _on_state(self, state: dict, err: str) -> None:
        rows = [r for r in (state.get("rows") or []) if r.get("installed")]
        active = [r for r in rows
                  if r.get("service") in ("active", "activating")]

        if active:
            names = ", ".join(r["label"] for r in active)
            self._row_state.set_subtitle(f"Active: {names}")
            self._on.set_visible(True)
        elif rows:
            self._row_state.set_subtitle(
                "No inbound path is active - nothing can reach this machine "
                "until you turn one on")
            self._on.set_visible(False)
        else:
            # Nothing installed is a different answer from "installed and
            # off": there is nothing here to switch on, and the summary
            # above must not promise a turn-on that does not exist. Measured
            # on a development host where none of the shipped mechanisms is
            # present - the render showed the mechanisms heading over an
            # empty group beside a subtitle telling the user to turn one on.
            self._row_state.set_subtitle(
                "No inbound path is active, and none of the mechanisms this "
                "page manages is installed, so there is nothing to switch on")
            self._on.set_visible(False)
        # The mechanisms group has no other content, so with no rows it is a
        # dangling heading over an empty group - the same hide-when-empty
        # rule the pages fixed in this pass follow.
        self._group.set_visible(bool(rows))

        self._clear()
        for r in rows:
            label = r["label"]
            unit = r.get("unit", "")
            service = r.get("service")
            config_present = r.get("config_present", False)
            
            # Determine subtitle and switch state
            if service in ("active", "activating"):
                sub = "Running - this machine is reachable"
                switch_active = True
            elif service == "failed":
                sub = "Failed to start"
                switch_active = False
            elif service == "configured":
                sub = "Configured, not running"
                switch_active = False
            elif config_present:
                sub = "Not running; configuration present"
                switch_active = False
            else:
                sub = "Installed, not enabled"
                switch_active = False
            
            # Skip WireGuard since it has its own dedicated page with per-interface control
            if label == "WireGuard":
                # For WireGuard, just show the config status without switch
                row = _row(label, f"{sub}. {r['effect']}")
                self._group.add(row)
                self._rows.append(row)
                continue
                
            # For other services, add enable/disable switch
            row = Adw.ActionRow(title=label)
            row.set_subtitle(f"{sub}. {r['effect']}")
            
            if unit:  # Only add switch if there's a systemd unit
                sw = Gtk.Switch()
                sw.set_active(switch_active)
                # Pass both the unit and the current desired state
                sw.connect("state-set", self._on_service_switch, unit)
                row.add_suffix(sw)
            
            if service in ("active", "activating"):
                row.add_css_class("warning")
                
            self._group.add(row)
            self._rows.append(row)
            self._unit_for_row[id(row)] = unit

    def _on_service_switch(self, sw, state, unit) -> bool:
        """Enable or disable one unit.

        **No comparison against a remembered state.** The first version took a
        `current_state` captured when the switch was connected and compared
        every click to it. That value is from page load and is never refreshed,
        so the guard silently stopped meaning anything after the first change:
        it was either always or never true, depending on how the page was
        found. `systemctl` is the only thing that knows the real state, and the
        re-read after the call is what corrects the switch.
        """
        verb = "enable" if state else "disable"
        # Use --now to also start/stop immediately
        argv = ["systemctl", verb, "--now", unit]
        
        def done(rc, err=""):
            if rc != 0:
                # 126 is a dismissed polkit dialog and 127 is a refusal. Saying
                # "could not enable" for either tells a user who cancelled a
                # dialog that something is wrong.
                if rc == 126:
                    message = "Cancelled at the password prompt, so nothing changed"
                elif rc == 127:
                    message = "Not authorised, so nothing changed"
                else:
                    message = " ".join(
                        line for line in (err or "").splitlines()
                        if line.strip())[-240:] or f"systemctl exited {rc}"
                self._show_error(message, sw, not state)
            # Refresh to show updated state
            GLib.timeout_add(1000, lambda: (self.refresh(), False)[1])
            
        ss.run_streaming(argv, lambda _: None, done)
        return False
        
    def _show_error(self, message: str, sw: Gtk.Switch, expected_state: bool) -> None:
        """Show the message, and put the switch back.

        `systemctl` is the authority on whether the unit is enabled, so on
        failure the switch is restored rather than left showing a state that did
        not happen. **The message must also actually appear:** this used to walk
        the widget tree looking for a ToastOverlay, and the page had none, so
        every failure reverted the switch and told the user nothing - a failure
        with no message is indistinguishable from a click that did nothing.
        `tests/test_service_toggle_pages.py` constructs this page for real to
        prove a toast arrives.
        """
        self._toasts.add_toast(Adw.Toast(
            title=GLib.markup_escape_text(message), timeout=5))
        # `expected_state` is the state to GO BACK TO, and it arrives as `not
        # state` from `done()`, where `state` is what the user asked for - so the
        # parameter already holds the OLD state. A first version wrote
        # `not expected_state` here and double-negated it, which left a failed
        # enable showing "enabled" and a failed disable showing "disabled": the
        # exact lie this method exists to prevent, and it survived every earlier
        # test because none of them drove a real failure through a real switch.
        sw.handler_block_by_func(self._on_service_switch)
        sw.set_active(expected_state)
        sw.handler_unblock_by_func(self._on_service_switch)
        
    def refresh(self) -> None:
        """Refresh the inbound access state."""
        self._clear()
        ss.inbound_access_state(self._on_state)
