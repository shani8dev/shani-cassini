# Enrichment 2026-10-30: voltkit alignment (hosts & environment editor pattern).
"""Cloudflared: the tunnels that could let traffic reach this machine.

**cloudflared is not configured here.** A cloudflared tunnel is a credential
(tunnel token or certificate) plus a routing decision (which hostname points at
which local service), and both are cloudflared's own to make: ``cloudflared
tunnel create``, ``cloudflared tunnel route dns``, and the
``~/.cloudflared/config.yml`` that records them. Cassini's rule is that there is
only ever one place a setting is edited, and for a tunnel that place is
cloudflared's own CLI and its own config file. A second editor here would be a
second place to keep honest about the same credential, and the credential is the
one thing this page must never show.

What this page does instead is **report**: whether cloudflared is installed,
whether a tunnel is configured (by the presence of a config file and a
credentials file, never by their contents), and what ``cloudflared tunnel list``
says about the tunnels that exist. Nothing here writes, nothing here runs a
tunnel, and nothing here reads a token.

**What "configured" means here.** cloudflared reads two files:

1. ``~/.cloudflared/config.yml`` (or ``/etc/cloudflared/config.yml``) — the
   tunnel id, the credentials file path, and the ingress rules.
2. The credentials file it names (``<tunnel-id>.json``) — the token that
   authenticates the tunnel to Cloudflare.

This page reports whether **both** exist, by path and by size, and never opens
either. A config without a credentials file is reported as "configured but not
authenticated", because that is the state cloudflared itself reports and the
state a person needs to act on.

**What this page will not claim: that any tunnel is reachable.** cloudflared
needs outbound access to Cloudflare's edge, a valid token, and a DNS record
pointing at the tunnel. This page cannot see any of those, so it reports what
is written and names ``cloudflared tunnel info <id>`` as the command that
reports what cloudflare knows.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
from pathlib import Path

from gi.repository import Adw, Gtk  # type: ignore

from shani_cassini import system_status as ss

logger = logging.getLogger(__name__)

SUMMARY_NOTE = (
    "Whether cloudflared is installed, and whether a tunnel is configured. "
    "Read-only: cloudflared's own CLI owns the configuration."
)

CLOUDFLARED: str = "cloudflared"
USER_CONFIG: Path = Path.home() / ".cloudflared" / "config.yml"
SYSTEM_CONFIG: Path = Path("/etc/cloudflared/config.yml")
USER_DIR: Path = Path.home() / ".cloudflared"


def _row(title: str, subtitle: str = "") -> Adw.ActionRow:
    return Adw.ActionRow(title=title, subtitle=subtitle)


class CloudflaredTab(Gtk.Box):
    """Cloudflared: reported, never configured here."""

    def __init__(self, state=None, auth_manager=None) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self._state = state
        self._auth_manager = auth_manager
        self._page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self._toasts = Adw.ToastOverlay()
        self._toasts.set_child(self._page)
        self.append(self._toasts)
        self._build()

    def _build(self) -> None:
        self._page.append(self._install_card())
        self._page.append(self._config_card())
        self._page.append(self._how_to_edit_card())

    def _install_card(self) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup()
        group.set_title("cloudflared")
        if shutil.which(CLOUDFLARED) is None:
            row = _row(
                "Not installed",
                "cloudflared is not on this machine. Install it from "
                "Cloudflare's package repository, then re-open this page.",
            )
            group.add(row)
            return group
        try:
            result = subprocess.run(
                [CLOUDFLARED, "--version"],
                capture_output=True, text=True, timeout=10,
            )
        except (subprocess.TimeoutExpired, OSError) as exc:
            row = _row("Could not run cloudflared", str(exc))
            group.add(row)
            return group
        version = (result.stdout or result.stderr or "").strip()
        row = _row("Installed", version or "cloudflared is present")
        group.add(row)
        return group

    def _config_card(self) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup()
        group.set_title("Tunnel configuration")
        group.set_description(
            "Whether a tunnel is configured, by the presence of its files. "
            "The contents are never read here."
        )

        config_path = None
        if USER_CONFIG.is_file():
            config_path = USER_CONFIG
        elif SYSTEM_CONFIG.is_file():
            config_path = SYSTEM_CONFIG

        if config_path is None:
            row = _row(
                "No tunnel configured",
                "Neither ~/.cloudflared/config.yml nor "
                "/etc/cloudflared/config.yml exists. Create one with "
                "cloudflared tunnel create NAME.",
            )
            group.add(row)
            return group

        try:
            size = config_path.stat().st_size
        except OSError:
            size = 0
        row = _row("Config file", f"{config_path} ({size} bytes)")
        group.add(row)

        # Look for a credentials file beside the config. cloudflared names it
        # <tunnel-id>.json; we report how many exist, never their contents.
        try:
            creds = [p for p in USER_DIR.iterdir()
                     if p.is_file() and p.suffix == ".json"]
        except OSError:
            creds = []
        if creds:
            row = _row(
                "Credentials present",
                f"{len(creds)} credential file(s) in {USER_DIR}",
            )
        else:
            row = _row(
                "No credentials",
                "A config exists but no credential file was found beside it. "
                "Run cloudflared tunnel create NAME to authenticate.",
            )
        group.add(row)

        # If cloudflared is installed, ask it for the tunnel list. This is a
        # read-only query; it does not start or modify anything.
        if shutil.which(CLOUDFLARED) is not None:
            try:
                result = subprocess.run(
                    [CLOUDFLARED, "tunnel", "list"],
                    capture_output=True, text=True, timeout=30,
                )
            except (subprocess.TimeoutExpired, OSError) as exc:
                row = _row("Tunnel list unavailable", str(exc))
                group.add(row)
                return group
            output = (result.stdout or "").strip()
            if not output:
                row = _row("No tunnels", "cloudflared reports none")
            else:
                for line in output.splitlines():
                    line = line.strip()
                    if not line:
                        continue
                    row = _row("Tunnel", line)
                    group.add(row)
                return group
        return group

    def _how_to_edit_card(self) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup()
        group.set_title("How to change it")
        group.set_description(
            "Create a tunnel with cloudflared tunnel create NAME, route "
            "DNS with cloudflared tunnel route dns NAME HOSTNAME, and "
            "write the ingress rules into ~/.cloudflared/config.yml. Apply "
            "with cloudflared tunnel run NAME or by enabling the "
            "cloudflared service. Cassini reports what is written; it does "
            "not write it, because cloudflared's own CLI is the authority on "
            "its own configuration and a second editor here would be a second "
            "place to keep honest about the same credential."
        )
        return group