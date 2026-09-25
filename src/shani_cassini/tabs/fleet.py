"""Fleet: this device's enrollment, from the fleet agent itself.

`shani-fleet-agent status` (root: it reads /etc/shani-fleet.conf) prints
"key: value" lines - shown as they are. Enrolling needs the
organisation's token and stays with its administrators
(`shani-fleet-agent enroll`); the page never invents a fleet state.
"""

from __future__ import annotations

import logging

from gi.repository import Adw, GLib, Gtk  # type: ignore

from shani_cassini import system_status as ss

logger = logging.getLogger(__name__)
AGENT = "shani-fleet-agent"


class FleetTab(Gtk.Box):
    def __init__(self, state=None, auth_manager=None) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self._state = state
        self._auth_manager = auth_manager
        self._toasts = Adw.ToastOverlay()
        self.append(self._toasts)
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self._toasts.set_child(page)

        g = Adw.PreferencesGroup(
            title="Fleet Management",
            description="This device's organisation can see its inventory and health and send it "
                        "signed update and rollback commands. Enrollment is done by the organisation.")
        row = Adw.ActionRow(title="Agent status", subtitle="Reading it needs your password")
        self._btn = Gtk.Button(label="Show", valign=Gtk.Align.CENTER)
        self._btn.connect("clicked", lambda *_: self._load())
        row.add_suffix(self._btn)
        g.add(row)
        page.append(g)
        self._status = Adw.PreferencesGroup(title="Status", visible=False)
        page.append(self._status)

    def _load(self) -> None:
        self._btn.set_sensitive(False)
        lines: list[str] = []

        def done(rc):
            self._btn.set_sensitive(True)
            if rc in (126, 127):
                self._toasts.add_toast(Adw.Toast(title="Authorization was cancelled"))
                return
            self._show(lines, rc)
        ss.run_streaming(["pkexec", AGENT, "status"], lines.append, done)

    def _show(self, lines: list[str], rc: int) -> None:
        parent = self._status.get_parent()
        new = Adw.PreferencesGroup(title="Status")
        for l in lines:
            if ": " not in l:
                if l.strip():
                    new.set_description(GLib.markup_escape_text(l.strip()))  # the version line
                continue
            key, val = l.split(": ", 1)
            bad = any(w in val for w in ("NO", "NOT", "never", "fail"))
            r = Adw.ActionRow(title=GLib.markup_escape_text(key.strip().capitalize()),
                              subtitle=GLib.markup_escape_text(val.strip()))
            r.set_subtitle_selectable(True)
            if bad:
                img = Gtk.Image.new_from_icon_name("dialog-warning-symbolic"); img.add_css_class("warning")
                r.add_prefix(img)
            new.add(r)
        if rc != 0 and not lines:
            new.set_description("The agent did not answer")
        parent.remove(self._status)
        parent.append(new)
        self._status = new
