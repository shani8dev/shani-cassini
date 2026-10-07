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
        self.append(self._page)
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
        self._page.append(self._on)

        self._group = Adw.PreferencesGroup(
            title="Installed mechanisms",
            description="Each row reports what is installed and whether it is "
                        "running. Use the switch to enable or disable the service.")
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
        else:
            self._row_state.set_subtitle(
                "No inbound path is active - nothing can reach this machine "
                "until you turn one on")
            self._on.set_visible(False)

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
                sw.connect("state-set", self._on_service_switch, unit, switch_active)
                row.add_suffix(sw)
            
            if service in ("active", "activating"):
                row.add_css_class("warning")
                
            self._group.add(row)
            self._rows.append(row)
            self._unit_for_row[id(row)] = unit

    def _on_service_switch(self, sw, state, unit, current_state) -> bool:
        """Handle enable/disable switch for a service."""
        # If state didn't actually change (due to rapid clicks), ignore
        if bool(state) == current_state:
            return False
            
        verb = "enable" if state else "disable"
        # Use --now to also start/stop immediately
        argv = ["systemctl", verb, "--now", unit]
        
        def done(rc):
            if rc != 0:
                self._show_error(f"Could not {verb} {unit}", sw, not state)
            # Refresh to show updated state
            GLib.timeout_add(1000, lambda: (self.refresh(), False)[1])
            
        ss.run_streaming(argv, lambda _: None, done)
        return False
        
    def _show_error(self, message: str, sw: Gtk.Switch, expected_state: bool) -> None:
        """Show error toast and revert switch."""
        # Find the toast overlay - walk up the widget tree
        widget = sw
        while widget and not isinstance(widget, Adw.ToastOverlay):
            widget = widget.get_parent()
        if widget:
            toast = Adw.Toast(title=GLib.markup_escape_text(message))
            toast.set_timeout(5000)
            widget.add_toast(toast)
        # Revert switch
        sw.handler_block_by_func(self._on_service_switch)
        sw.set_active(not expected_state)
        sw.handler_unblock_by_func(self._on_service_switch)
        
    def refresh(self) -> None:
        """Refresh the inbound access state."""
        self._clear()
        ss.inbound_access_state(self._on_state)
