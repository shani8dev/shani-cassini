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
| `openssh` | remote shell and port forwarding (Remote Access) |
| `caddy` | listens on a port; serves or reverse-proxies |
| `rclone` | its `serve` modes listen, and can expose local files |

**Read-only, and it will not switch any of them on.** Enabling an inbound path is
not a decision a settings panel should make on the user's behalf, and the input
each of these needs - a Cloudflare tunnel token, a Tailscale auth key, a peer
private key - does not belong in a generic settings window either.

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
    "This reports which are on. It does not switch any of them on."
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
                        "running. Nothing here is switched on by this page.")
        self._page.append(self._group)
        self._rows: list[Adw.ActionRow] = []

    def load(self) -> bool:
        ss.inbound_access_state(self._on_state)
        return False

    def _clear(self) -> None:
        for row in self._rows:
            self._group.remove(row)
        self._rows = []

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
            service = r.get("service")
            if service in ("active", "activating"):
                sub = "Running - this machine is reachable"
            elif service == "failed":
                sub = "Failed to start"
            elif service == "configured":
                sub = "Configured, not running"
            elif r.get("config_present"):
                sub = "Not running; configuration present"
            else:
                sub = "Installed, not enabled"
            row = _row(r["label"], f"{sub}. {r['effect']}")
            if service in ("active", "activating"):
                row.add_css_class("warning")
            self._group.add(row)
            self._rows.append(row)
