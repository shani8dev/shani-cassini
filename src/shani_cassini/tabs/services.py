"""Services: the system services a person can switch on and off.

Straight from systemd: ``systemctl list-unit-files -o json`` (enabled /
disabled) merged with ``systemctl list-units -o json`` (running or not).
Only units with an enabled/disabled unit file are listed - static,
generated and template units cannot be toggled, so they are noise here.
Changes go through ``systemctl`` itself: systemd asks polkit over D-Bus,
so the desktop's own password dialog appears; no pkexec.
"""

from __future__ import annotations

import logging
import time

from gi.repository import Adw, Gio, GLib, Gtk  # type: ignore

from shani_cassini import system_status as ss

logger = logging.getLogger(__name__)
TOGGLEABLE = ("enabled", "disabled")


class ServicesTab(Gtk.Box):
    def __init__(self, state=None, auth_manager=None) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        self._state = state
        self._auth_manager = auth_manager
        self._files: dict | None = None
        self._units: dict | None = None
        self._rows: list[tuple[Adw.ActionRow, str]] = []

        self._toasts = Adw.ToastOverlay()
        self.append(self._toasts)
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        self._toasts.set_child(page)

        self._search = Gtk.SearchEntry(placeholder_text="Search services")
        self._search.connect("search-changed", lambda *_: self._filter())
        page.append(self._search)
        self._running = Adw.PreferencesGroup(title="Running")
        self._stopped = Adw.PreferencesGroup(title="Not Running")
        self._spinner = Gtk.Spinner(spinning=True, halign=Gtk.Align.CENTER, margin_top=24)
        page.append(self._spinner)
        page.append(self._running)
        page.append(self._stopped)
        self.refresh()

    # ----------------------------------------------------------------- data
    def refresh(self) -> None:
        self._files = self._units = None
        ss.run_json(["systemctl", "list-unit-files", "--type=service", "-o", "json", "--no-pager"],
                    lambda d, e: self._got("files", d, e))
        ss.run_json(["systemctl", "list-units", "--type=service", "--all", "-o", "json", "--no-pager"],
                    lambda d, e: self._got("units", d, e))

    def _got(self, which, data, err) -> None:
        if data is None:
            self._spinner.set_visible(False)
            self._running.set_description(f"systemd did not answer: {err}")
            return
        if which == "files":
            self._files = {f["unit_file"]: f for f in data}
        else:
            self._units = {u["unit"]: u for u in data}
        if self._files is not None and self._units is not None:
            self._populate()

    def _populate(self) -> None:
        self._spinner.set_visible(False)
        for row, _ in self._rows:
            row.get_parent() and row.get_ancestor(Adw.PreferencesGroup).remove(row)
        self._rows.clear()
        n_run = n_stop = 0
        for name, f in sorted(self._files.items()):
            if f.get("state") not in TOGGLEABLE or "@" in name:
                continue
            u = self._units.get(name, {})
            active = u.get("active") == "active"
            desc = u.get("description") or name.removesuffix(".service")
            row = Adw.ActionRow(title=GLib.markup_escape_text(desc),
                                subtitle=GLib.markup_escape_text(
                                    f"{name} · {u.get('sub') or 'inactive'}"
                                    + (" · failed" if u.get("active") == "failed" else "")))
            if u.get("active") == "failed":
                img = Gtk.Image.new_from_icon_name("dialog-error-symbolic"); img.add_css_class("error")
                row.add_prefix(img)
            sw = Gtk.Switch(active=f.get("state") == "enabled", valign=Gtk.Align.CENTER,
                            tooltip_text="Start with the system (and now)")
            sw.connect("state-set", self._on_switch, name)
            row.add_suffix(sw)
            row.add_suffix(self._menu(name, active))
            (self._running if active else self._stopped).add(row)
            self._rows.append((row, f"{name} {desc}".lower()))
            n_run += active
            n_stop += not active
        self._running.set_title(f"Running ({n_run})")
        self._stopped.set_title(f"Not Running ({n_stop})")
        self._filter()

    def _filter(self) -> None:
        q = self._search.get_text().lower().strip()
        for row, hay in self._rows:
            row.set_visible(not q or q in hay)

    # -------------------------------------------------------------- actions
    def _menu(self, unit: str, active: bool) -> Gtk.MenuButton:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2, margin_top=6,
                      margin_bottom=6, margin_start=6, margin_end=6)
        pop = Gtk.Popover(child=box)
        items = [("Restart", "restart"), ("Stop", "stop")] if active else [("Start", "start")]
        for label, verb in items + [("Show Log", "log")]:
            b = Gtk.Button(label=label, has_frame=False)
            b.connect("clicked", lambda _b, v=verb: (pop.popdown(), self._do(unit, v)))
            box.append(b)
        return Gtk.MenuButton(icon_name="view-more-symbolic", popover=pop, valign=Gtk.Align.CENTER,
                              has_frame=False, tooltip_text="More")

    def _on_switch(self, sw, state, unit) -> bool:
        self._do(unit, "enable" if state else "disable", sw)
        return False

    def _do(self, unit: str, verb: str, sw: Gtk.Switch | None = None) -> None:
        if verb == "log":
            return self._show_log(unit)
        argv = ["systemctl", verb] + (["--now"] if verb in ("enable", "disable") else []) + [unit]

        def done(rc):
            if rc != 0:
                self._toasts.add_toast(Adw.Toast(title=GLib.markup_escape_text(
                    f"Could not {verb} {unit}" + (": " + out[-1] if out else ""))))
                if sw is not None:
                    sw.handler_block_by_func(self._on_switch)
                    sw.set_active(verb == "disable")
                    sw.handler_unblock_by_func(self._on_switch)
            GLib.timeout_add(400, lambda: (self.refresh(), False)[1])
        out: list[str] = []
        ss.run_streaming(argv, out.append, done)

    def _show_log(self, unit: str) -> None:
        dialog = Adw.Dialog(title=unit, content_width=760, content_height=520)
        view = Adw.ToolbarView()
        view.add_top_bar(Adw.HeaderBar())
        buf = Gtk.TextBuffer()
        tv = Gtk.TextView(buffer=buf, editable=False, monospace=True, wrap_mode=Gtk.WrapMode.WORD_CHAR,
                          top_margin=12, bottom_margin=12, left_margin=12, right_margin=12)
        sc = Gtk.ScrolledWindow(child=tv, vexpand=True)
        view.set_content(sc)
        dialog.set_child(view)

        def got(items, err):
            if items is None:
                buf.set_text(err)
                return
            lines = []
            for e in items:
                t = int(e.get("__REALTIME_TIMESTAMP", 0)) // 1_000_000
                msg = e.get("MESSAGE")
                if isinstance(msg, list):
                    msg = bytes(msg).decode(errors="replace")
                lines.append(f"{time.strftime('%b %d %H:%M:%S', time.localtime(t))}  {msg}")
            buf.set_text("\n".join(lines) or "No log entries.")
            GLib.idle_add(lambda: sc.get_vadjustment().set_value(sc.get_vadjustment().get_upper()))

        ss.run_json_lines(["journalctl", "-u", unit, "-n", "200", "-o", "json", "--no-pager"], got)
        dialog.present(self.get_root())
