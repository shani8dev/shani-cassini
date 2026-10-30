# Enrichment 2026-10-30: voltkit alignment (hosts & environment editor).
"""Hosts and session environment: what names resolve to, and what every desktop
app inherits — and the controls to change them.

Two files, two different owners.

* ``/etc/hosts`` — the static name table. Entries can be toggled (commented
  and uncommented), added and removed. The save goes through
  ``pkexec shani-cassini-save --target hosts``: the content travels on stdin,
  the helper validates it as a hosts file, commits with ``mv -f``, reads back
  what it wrote, and rolls back on any new complaint. System entries (localhost,
  the machine's own name, the IPv6 loopback) are reported and never offered
  for removal — a button that removes ``127.0.0.1 localhost`` is a button that
  breaks name resolution on this machine.
* ``~/.config/environment.d/*.conf`` (and the system-wide
  ``/etc/environment.d``) — the variables every systemd user service and
  every app launched from the session inherits. Reported per file, per
  variable, with the value and the source file named. A variable set twice
  is reported twice rather than merged, because the second definition is
  the one that wins and a silent merge would hide that.

**What this page will not claim: that any of it is in effect.** ``/etc/hosts``
is consulted by the resolver only when the resolver is configured to use it,
and ``environment.d`` is read only by systemd user sessions — a variable set
in a file a non-systemd session never reads is a variable that does nothing.
This page cannot see either of those, so it reports what is written and names
``getent hosts NAME`` for a name and ``systemctl --user show-environment`` for
a variable.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
from pathlib import Path

from gi.repository import Adw, GLib, Gtk  # type: ignore

from shani_cassini import config_io
from shani_cassini.config_io import ConfigRefused, Document, Line, Staged

logger = logging.getLogger(__name__)

SUMMARY_NOTE = (
    "What /etc/hosts carries, and what environment.d variables this "
    "session inherits. Entries can be toggled, added and removed."
)

HOSTS_FILE: str = "/etc/hosts"
HELPER: str = "/usr/local/bin/shani-cassini-save"
PKEXEC: str = "pkexec"
TARGET: str = "hosts"


def _row(title: str, subtitle: str = "") -> Adw.ActionRow:
    return Adw.ActionRow(title=title, subtitle=subtitle)


def _looks_like_ip(tok: str) -> bool:
    if ":" in tok:
        return tok.count(":") >= 2
    parts = tok.split(".")
    return len(parts) == 4 and all(p.isdigit() for p in parts)


_SYSTEM_IPS: set[str] = {"127.0.0.1", "127.0.1.1", "::1", "0.0.0.0"}


def _parse_hosts(text: str) -> list[dict]:
    """Parse /etc/hosts into a list of entry dicts.

    Each dict has: ip, names (str), comment (str), enabled (bool),
    system (bool), raw (str).
    """
    out: list[dict] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        # Commented-out (disabled) entry
        enabled = True
        working = line
        if line.startswith("#"):
            body = line.lstrip("#").strip()
            if not body:
                continue
            working = body
            enabled = False
        parts = working.split()
        if len(parts) < 2 or not _looks_like_ip(parts[0]):
            continue
        ip = parts[0]
        # Strip inline comment from names
        comment = ""
        if "#" in working:
            idx = working.index("#")
            comment = working[idx:]
            working = working[:idx].rstrip()
            parts = working.split()
        names = " ".join(parts[1:]) if len(parts) > 1 else ""
        out.append({
            "ip": ip,
            "names": names,
            "comment": comment,
            "enabled": enabled,
            "system": ip in _SYSTEM_IPS,
            "raw": raw,
        })
    return out


def _hosts_text(entries: list[dict]) -> str:
    """Rebuild /etc/hosts text from entries, preserving system entries."""
    lines: list[str] = []
    for e in entries:
        if e["enabled"]:
            line = f"{e['ip']} {e['names']}"
        else:
            line = f"# {e['ip']} {e['names']}"
        if e.get("comment"):
            line += f"  {e['comment']}"
        lines.append(line)
    return "\n".join(lines) + "\n"


def _env_dirs() -> list:
    dirs = []
    sys_dir = Path("/etc/environment.d")
    if sys_dir.is_dir():
        dirs.append(sys_dir)
    user_dir = Path(os.path.expanduser("~/.config/environment.d"))
    if user_dir.is_dir():
        dirs.append(user_dir)
    return dirs


def _parse_env(text: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if not key or any(c in key for c in " \t"):
            continue
        out.append((key, value))
    return out


class HostsEnvTab(Gtk.Box):
    """Hosts and session environment: reported and editable."""

    def __init__(self, state=None, auth_manager=None) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        self._state = state
        self._auth_manager = auth_manager
        self._page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self._toasts = Adw.ToastOverlay()
        self._toasts.set_child(self._page)
        self.append(self._toasts)
        self._entries: list[dict] = []
        self._build()

    def _build(self) -> None:
        self._page.append(self._hosts_card())
        self._page.append(self._env_card())
        self._page.append(self._how_to_edit_card())

    def _refresh_hosts(self) -> None:
        """Re-read /etc/hosts and rebuild the card."""
        # Remove old hosts card (first child)
        child = self._page.get_first_child()
        if child:
            self._page.remove(child)
        self._page.prepend(self._hosts_card())

    def _hosts_card(self) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup()
        group.set_title("Hosts (/etc/hosts)")
        group.set_description(
            "Static names this machine resolves before it asks a DNS server. "
            "Toggle, add or remove entries. System entries cannot be removed."
        )
        try:
            text = Path(HOSTS_FILE).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            row = _row("Could not read /etc/hosts", str(exc))
            group.add(row)
            return group
        self._entries = _parse_hosts(text)
        if not self._entries:
            row = _row("No entries", "The file is empty or unreadable")
            group.add(row)
            return group
        for i, e in enumerate(self._entries):
            title = e["names"] if e["enabled"] else f"{e['names']}  (disabled)"
            subtitle = e["ip"]
            if e["comment"]:
                subtitle = f"{e['ip']}  {e['comment']}"
            row = _row(title, subtitle)
            if not e["enabled"]:
                row.add_css_class("dim-label")
            if not e["system"]:
                # Toggle switch for user-added entries
                sw = Gtk.Switch()
                sw.set_active(e["enabled"])
                sw.connect("state-set", self._on_toggle, i)
                row.add_suffix(sw)
                # Remove button
                btn = Gtk.Button(label="Remove")
                btn.add_css_class("destructive-action")
                btn.connect("clicked", self._on_remove, i)
                row.add_suffix(btn)
            group.add(row)

        # Add new entry form
        add_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        add_box.set_margin_top(8)
        ip_entry = Gtk.Entry()
        ip_entry.set_placeholder_text("IP address")
        ip_entry.set_hexpand(True)
        name_entry = Gtk.Entry()
        name_entry.set_placeholder_text("hostname")
        name_entry.set_hexpand(True)
        add_btn = Gtk.Button(label="Add")
        add_btn.add_css_class("suggested-action")
        add_btn.connect("clicked", self._on_add, ip_entry, name_entry)
        add_box.append(ip_entry)
        add_box.append(name_entry)
        add_box.append(add_btn)
        group.add(add_box)
        return group

    def _on_toggle(self, sw, state, index) -> bool:
        if index >= len(self._entries):
            return False
        self._entries[index]["enabled"] = state
        self._save_hosts()
        return False

    def _on_remove(self, btn, index) -> None:
        if index >= len(self._entries):
            return
        if self._entries[index]["system"]:
            return
        del self._entries[index]
        self._save_hosts()

    def _on_add(self, btn, ip_entry, name_entry) -> None:
        ip = ip_entry.get_text().strip()
        name = name_entry.get_text().strip()
        if not ip or not name:
            return
        if not _looks_like_ip(ip):
            return
        self._entries.append({
            "ip": ip, "names": name, "comment": "", "enabled": True,
            "system": False, "raw": "",
        })
        ip_entry.set_text("")
        name_entry.set_text("")
        self._save_hosts()

    def _save_hosts(self) -> None:
        """Save /etc/hosts through the privileged helper."""
        text = _hosts_text(self._entries)
        try:
            import hashlib
            digest = hashlib.sha256(text.encode()).hexdigest()
            proc = subprocess.run(
                [PKEXEC, HELPER, "--target", TARGET, "--expect-sha256", digest],
                input=text, capture_output=True, text=True, timeout=60,
            )
            if proc.returncode == 0:
                toast = Adw.Toast.new("Hosts file updated")
                self._toasts.add_toast(toast)
            else:
                msg = proc.stderr.strip() or "save failed"
                toast = Adw.Toast.new(f"Could not save: {msg}")
                self._toasts.add_toast(toast)
        except (subprocess.TimeoutExpired, OSError) as exc:
            toast = Adw.Toast.new(f"Could not save: {exc}")
            self._toasts.add_toast(toast)
        self._refresh_hosts()

    def _env_card(self) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup()
        group.set_title("Session environment (environment.d)")
        group.set_description(
            "Variables every systemd user service and every app launched from "
            "the session inherits. Reported per file; a variable set twice is "
            "reported twice, because the second definition is the one that wins."
        )
        found = False
        for d in _env_dirs():
            try:
                files = sorted(p for p in d.iterdir() if p.is_file())
            except OSError:
                continue
            for f in files:
                try:
                    text = f.read_text(encoding="utf-8")
                except (OSError, UnicodeDecodeError):
                    continue
                vars_ = _parse_env(text)
                if not vars_:
                    continue
                found = True
                sub = Adw.PreferencesGroup()
                sub.set_title(str(f))
                sub.set_description("Variables this file sets")
                for key, value in vars_:
                    row = Adw.ActionRow(title=key, subtitle=value)
                    sub.add(row)
                group.add(sub)
        if not found:
            row = Adw.ActionRow(
                title="No environment.d files found",
                subtitle="Neither /etc/environment.d nor ~/.config/environment.d has any",
            )
            group.add(row)
        return group

    def _how_to_edit_card(self) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup()
        group.set_title("How to change these")
        group.set_description(
            "Hosts entries can be toggled, added and removed above; the save "
            "goes through the privileged helper, which validates the file "
            "before installing it. Environment variables are edited directly "
            "in ~/.config/environment.d/*.conf (a line like EDITOR=nano), "
            "then 'systemctl --user import-environment' or a re-login to "
            "apply. Cassini reports what is written; it does not write "
            "environment.d, because systemd's own parser is the authority."
        )
        return group