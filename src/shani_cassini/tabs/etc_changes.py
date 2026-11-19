"""System Changes: what this computer changed in /etc, and putting a file back.

On Shanios /etc is an overlay. Its lower layer is the booted slot's own /etc -
what the image ships - and its upper layer, /data/overlay/etc/upper, holds every
change made on this computer and keeps it across updates. That is the right
default, and also how a setting edited months ago goes on deciding how the
machine behaves after every update. This page shows those changes and lets one
file go back to the shipped version.

**Interface:** ``pkexec shani-etc-changes`` (shani-deploy), root because the
upper layer holds files only root may read:

* ``list --json`` - ``{changes: [{path, kind, protected, secret, pending}],
  pending: [path], done: [{at, path}]}``; ``kind`` is modified, permissions,
  added or removed.
* ``diff PATH`` - ``{diff, hidden, binary}``; ``hidden`` for secrets (password
  hashes, keys, saved Wi-Fi), whose content is never shown here.
* ``restore PATH`` / ``cancel PATH`` - queue a file, or take it off the queue.

**A restore is never done to the running system.** The upper layer must not be
changed under a mounted overlay, so the tool only queues the path and the
initramfs removes this computer's copy at the next start, before /etc is
mounted. The page says so on every queued row. Files the tool marks
``protected`` (accounts, machine-id, crypttab, the Secure Boot key) are shown
with the reason and never get a Restore button.

The list is behind a button: reading it asks for a password, and opening a page
must not. The idea is Ananta OS's "System changes" (Ananta Maintenance).
"""

from __future__ import annotations

import datetime as dt
import logging

from gi.repository import Adw, GLib, Gtk  # type: ignore

from shani_cassini import system_status as ss

logger = logging.getLogger(__name__)
TOOL = "shani-etc-changes"

KINDS = (
    ("modified", "Changed", "Edited on this computer"),
    ("permissions", "Changed", "Same content, different owner or permissions"),
    ("added", "Added", "Not part of Shanios - made on this computer"),
    ("removed", "Removed", "Shipped with Shanios, deleted on this computer"),
)
GROUPS = (
    ("Changed", "Files Shanios ships that this computer edited"),
    ("Added", "Files this computer made. Restoring one deletes it"),
    ("Removed", "Files Shanios ships that this computer deleted. Restoring one brings it back"),
)
RESTORE_EFFECT = {
    "modified": "goes back to the version Shanios ships",
    "permissions": "gets the owner and permissions Shanios ships",
    "added": "is deleted - Shanios does not ship it",
    "removed": "comes back as Shanios ships it",
}


class EtcChangesTab(Gtk.Box):
    def __init__(self, state=None, auth_manager=None) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self._state = state
        self._pending = 0
        self._toasts = Adw.ToastOverlay()
        self.append(self._toasts)
        self._page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self._toasts.set_child(self._page)
        self._rows: dict[str, Adw.ActionRow] = {}

        intro = Adw.PreferencesGroup(
            title="Changes to System Settings",
            description="Files in /etc this computer changed from what Shanios ships. "
                        "They are kept across every update. A file can go back to the "
                        "shipped version at the next start.")
        self._status_row = Adw.ActionRow(title="Changed files", subtitle="Showing them needs your password")
        self._btn_show = Gtk.Button(label="Show Changes", valign=Gtk.Align.CENTER)
        self._btn_show.add_css_class("suggested-action")
        self._btn_show.connect("clicked", lambda *_: self.load())
        self._status_row.add_suffix(self._btn_show)
        intro.add(self._status_row)
        self._page.append(intro)
        self._groups_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self._page.append(self._groups_box)

    # ---- reading ----------------------------------------------------------------------
    def load(self) -> None:
        self._btn_show.set_sensitive(False)
        self._status_row.set_subtitle("Reading…")
        self._pending += 1
        ss.run_json(["pkexec", TOOL, "list", "--json"], self._on_list)

    def _on_list(self, data, err) -> None:
        self._pending -= 1
        self._btn_show.set_sensitive(True)
        self._btn_show.set_label("Refresh")
        if not data or not data.get("ok"):
            why = (data or {}).get("error") or err or "no answer"
            self._status_row.set_subtitle(GLib.markup_escape_text(f"Could not read the changes: {why}"))
            return
        self._show(data)

    def _show(self, data) -> None:
        child = self._groups_box.get_first_child()
        while child:
            nxt = child.get_next_sibling()
            self._groups_box.remove(child)
            child = nxt
        self._rows = {}
        changes = data.get("changes") or []
        queued = [c for c in changes if c.get("pending")]
        n = len(changes)
        self._status_row.set_subtitle(
            ("No file in /etc differs from what Shanios ships" if n == 0 else
             f"{n} file{'s' if n != 1 else ''} differ from what Shanios ships")
            + (f" · {len(queued)} will go back at the next start" if queued else ""))

        label = {k: g for k, g, _ in KINDS}
        what = {k: d for k, _, d in KINDS}
        for title, desc in GROUPS:
            items = [c for c in changes if label.get(c.get("kind")) == title]
            if not items:
                continue
            g = Adw.PreferencesGroup(title=title, description=desc)
            for c in items:
                g.add(self._row(c, what.get(c.get("kind"), "")))
            self._groups_box.append(g)

        done = data.get("done") or []
        if done:
            g = Adw.PreferencesGroup(title="Restored Earlier",
                                     description="Put back to the shipped version at a start of this computer")
            for d in reversed(done[-10:]):
                when = dt.datetime.fromtimestamp(d.get("at") or 0).strftime("%-d %b %Y, %H:%M") if d.get("at") else ""
                g.add(Adw.ActionRow(title=GLib.markup_escape_text("/etc/" + d.get("path", "")),
                                    subtitle=when))
            self._groups_box.append(g)

    def _row(self, c, what) -> Adw.ActionRow:
        path = c["path"]
        row = Adw.ActionRow(title=GLib.markup_escape_text("/etc/" + path))
        row.set_title_lines(1)
        if c.get("protected"):
            row.set_subtitle(GLib.markup_escape_text(f"{what} · not restored here: {c['protected']}"))
        elif c.get("pending"):
            row.set_subtitle("Goes back to the shipped version at the next start")
        else:
            row.set_subtitle(what)

        if c.get("secret"):
            # No Difference button: the tool never shows a secret's content, so
            # the button would only cost a password prompt to say so.
            row.set_subtitle(row.get_subtitle() + " · content not shown: it holds secrets")
        elif c.get("kind") != "removed":
            diff = Gtk.Button(label="Difference", valign=Gtk.Align.CENTER)
            diff.connect("clicked", lambda *_: self._diff(path))
            row.add_suffix(diff)
        if not c.get("protected"):
            if c.get("pending"):
                b = Gtk.Button(label="Keep", valign=Gtk.Align.CENTER,
                               tooltip_text="Do not restore it at the next start")
                b.connect("clicked", lambda *_: self._run(["cancel", path], f"/etc/{path} stays as it is"))
            else:
                b = Gtk.Button(label="Restore…", valign=Gtk.Align.CENTER)
                b.connect("clicked", lambda *_: self._confirm(c))
            row.add_suffix(b)
        self._rows[path] = row
        return row

    # ---- the difference ---------------------------------------------------------------
    def _diff(self, path) -> None:
        self._pending += 1
        ss.run_json(["pkexec", TOOL, "diff", path], lambda d, e: self._on_diff(path, d, e))

    def _on_diff(self, path, data, err) -> None:
        self._pending -= 1
        if not data or not data.get("ok"):
            self._toast(f"Could not show the difference: {(data or {}).get('error') or err}")
            return
        if data.get("hidden"):
            text = "The content of this file is not shown: it holds secrets (passwords, keys or saved credentials)."
        elif data.get("binary"):
            text = "This is not a text file, so there is no difference to show."
        else:
            text = data.get("diff") or "(no difference in content)"
        view = Gtk.TextView(editable=False, cursor_visible=False, monospace=True,
                            wrap_mode=Gtk.WrapMode.NONE, top_margin=8, bottom_margin=8,
                            left_margin=8, right_margin=8)
        view.get_buffer().set_text(text)
        scroll = Gtk.ScrolledWindow(min_content_height=320, min_content_width=560, child=view)
        d = Adw.AlertDialog(heading=f"/etc/{path}",
                            body="- lines: as Shanios ships it · + lines: on this computer")
        d.set_extra_child(scroll)
        d.add_response("close", "Close")
        d.present(self.get_root())
        self._last_dialog = d

    # ---- restore ----------------------------------------------------------------------
    def _confirm(self, c) -> None:
        path = c["path"]
        d = Adw.AlertDialog(
            heading=f"Restore /etc/{path}?",
            body=f"At the next start this file {RESTORE_EFFECT.get(c.get('kind'), 'goes back')}. "
                 "Until then nothing changes, and you can still keep it as it is.")
        d.add_response("cancel", "Cancel")
        d.add_response("restore", "Restore at Next Start")
        d.set_response_appearance("restore", Adw.ResponseAppearance.DESTRUCTIVE)
        d.set_default_response("cancel")
        d.set_close_response("cancel")
        d.connect("response", lambda _d, r: r == "restore" and self._run(
            ["restore", path], f"/etc/{path} goes back at the next start"))
        d.present(self.get_root())
        self._last_dialog = d

    def _run(self, args, ok_text) -> None:
        self._pending += 1
        ss.run_json(["pkexec", TOOL, *args], lambda d, e: self._on_run(d, e, ok_text))

    def _on_run(self, data, err, ok_text) -> None:
        self._pending -= 1
        if data and data.get("ok"):
            self._toast(ok_text)
            self.load()
        else:
            self._toast(f"Not done: {(data or {}).get('error') or err}")

    def _toast(self, text: str) -> None:
        self._toasts.add_toast(Adw.Toast(title=GLib.markup_escape_text(text), timeout=6))
