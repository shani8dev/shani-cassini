# Enrichment 2026-10-30: voltkit alignment (hosts & environment editor pattern).
"""Caddy: the reverse proxy and static file server this machine may be running.

**Caddy is not configured here.** Caddy's own configuration is a ``Caddyfile`` —
a small declarative language with its own validator (``caddy validate``) and
its own reload semantics (``caddy reload``). Cassini's rule is that there is
only ever one place a setting is edited, and for a Caddyfile that place is the
file itself or ``caddy``'s own CLI. A second editor here would be a second
place to keep honest about the same bytes, and the file format is rich enough
that a partial editor would be worse than none.

What this page does instead is **report**: what Caddyfile is in force, whether
it parses, which sites it declares, and what ``caddy`` itself says about it.
Nothing here writes, nothing here restarts the service, and nothing here reads
a credential — a Caddyfile can carry a TLS certificate path and a token, and
this page names the file and reports its shape, never its contents' secrets.

**Three possible Caddyfiles, in order of precedence** (Caddy's own rule):

1. ``/etc/caddy/Caddyfile`` — the system-wide one, read when caddy runs as a
   service. This is the one this page reports.
2. ``./Caddyfile`` in the current working directory — what ``caddy run`` uses
   when started by hand. This page does not look for it; a service started
   from a shell is not a service this page can describe.
3. A file named with ``--config`` — invisible to this page by construction.

**What "valid" means here.** ``caddy validate`` is the authority, and this page
runs it (read-only, no privileges) against the file it found. A file that
parses is reported as valid; a file that does not is reported with caddy's own
error text, which names the line. A missing file is reported as missing rather
than as empty, because an empty Caddyfile and an absent one are different
facts: caddy with no file refuses to start, while caddy with an empty file
starts and serves nothing.

**What this page will not claim: that any of it is in effect.** Caddy's
configuration is reloaded on ``caddy reload`` and only then; a file edited on
disk while caddy is running is not what caddy is serving until that reload
happens. This page cannot see the running config, so it reports what is written
and names ``caddy reload`` as the command that applies it.
"""

from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
from pathlib import Path

from gi.repository import Adw, Gtk  # type: ignore

from shani_cassini import system_status as ss

logger = logging.getLogger(__name__)

SUMMARY_NOTE = (
    "What the Caddyfile on this machine declares, and whether caddy agrees "
    "with it. Read-only: caddy's own CLI is the editor and the validator."
)

CADDYFILE: str = "/etc/caddy/Caddyfile"
CADDY: str = "caddy"


def _row(title: str, subtitle: str = "") -> Adw.ActionRow:
    return Adw.ActionRow(title=title, subtitle=subtitle)


class CaddyTab(Gtk.Box):
    """Caddy: reported, never configured here."""

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
        self._page.append(self._file_card())
        self._page.append(self._sites_card())
        self._page.append(self._how_to_edit_card())

    def _file_card(self) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup()
        group.set_title("Caddyfile")
        group.set_description(
            "The system-wide file caddy reads when it runs as a service. "
            "Caddy's own validator is the authority on whether it parses."
        )
        path = Path(CADDYFILE)
        if not path.is_file():
            row = _row(
                "No Caddyfile",
                f"{CADDYFILE} does not exist. Caddy with no file refuses to "
                "start; create one with 'caddy init' or write it by hand.",
            )
            group.add(row)
            return group

        # Size and mtime, so a person can tell a file that has not changed
        # from one that has.
        try:
            st = path.stat()
            import datetime
            mtime = datetime.datetime.fromtimestamp(st.st_mtime).strftime(
                "%Y-%m-%d %H:%M")
            size = st.st_size
        except OSError:
            mtime, size = "unknown", 0
        row = _row("File", f"{CADDYFILE}  ({size} bytes, last modified {mtime})")
        group.add(row)

        # Validate with caddy's own validator. This is read-only: it parses
        # and reports, it does not start or reload anything.
        if shutil.which(CADDY) is None:
            row = _row(
                "caddy is not installed",
                "Nothing to validate against. Install the caddy package, "
                "then re-open this page.",
            )
            group.add(row)
            return group

        try:
            result = subprocess.run(
                [CADDY, "validate", "--config", CADDYFILE],
                capture_output=True, text=True, timeout=30,
            )
        except (subprocess.TimeoutExpired, OSError) as exc:
            row = _row("Validation did not complete", str(exc))
            group.add(row)
            return group

        if result.returncode == 0:
            row = _row("Valid", "caddy agrees with the file")
            row.add_css_class("success")
        else:
            msg = (result.stderr or result.stdout or "").strip()
            if not msg:
                msg = f"caddy exited {result.returncode} with no message"
            row = _row("Does not parse", msg)
            row.add_css_class("error")
        group.add(row)
        return group

    def _sites_card(self) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup()
        group.set_title("Sites declared")
        group.set_description(
            "Site blocks (hostnames or addresses) the Caddyfile names. "
            "Read by parsing the file's own text, not by asking caddy, so a "
            "file caddy refuses to validate still shows what it tried to say."
        )
        path = Path(CADDYFILE)
        if not path.is_file():
            row = _row("No file", "Nothing to read")
            group.add(row)
            return group
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            row = _row("Could not read", str(exc))
            group.add(row)
            return group

        # A site block is a hostname or address followed by `{` on the same
        # line or the next. This is a deliberately shallow read: it names what
        # the file talks about, it does not evaluate matchers or imports.
        sites: list[str] = []
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if "{" in line:
                head = line.split("{", 1)[0].strip()
                if head:
                    sites.append(head)
            elif line.endswith("{"):
                head = line[:-1].strip()
                if head:
                    sites.append(head)

        if not sites:
            row = _row("No site blocks found",
                       "The file has no hostnames or addresses with a block")
            group.add(row)
            return group
        for site in sites:
            row = _row(site, "declared site")
            group.add(row)
        return group

    def _how_to_edit_card(self) -> Adw.PreferencesGroup:
        group = Adw.PreferencesGroup()
        group.set_title("How to change it")
        group.set_description(
            "Edit /etc/caddy/Caddyfile directly (it is root-owned), then "
            "apply with 'caddy validate --config /etc/caddy/Caddyfile' and "
            "'caddy reload --config /etc/caddy/Caddyfile'. Cassini reports "
            "what is written; it does not write it, because caddy's own "
            "validator is the authority on its own syntax and a second "
            "editor here would be a second place to keep honest about the "
            "same bytes."
        )
        return group