"""Maintenance: disk space and clean-up, a diagnostic report, factory reset.

* ``shani-deploy --cleanup`` / ``--optimize`` (old downloads and backups;
  Btrfs deduplication)
* ``shani-health --export-logs DIR`` (a report bundle for bug reports)
* ``shani-reset --yes [--home] [--keep-downloads]`` (wipes /data state,
  keeps /home unless asked, reboots) - confirmed here by typing, as the CLI
  itself asks
All through pkexec; long ones show their output.
"""

from __future__ import annotations

import logging
import os

from gi.repository import Adw, Gio, GLib, Gtk  # type: ignore

from shani_cassini import system_status as ss

logger = logging.getLogger(__name__)


def _fs(path: str):
    try:
        info = Gio.File.new_for_path(path).query_filesystem_info("filesystem::size,filesystem::free", None)
        return info.get_attribute_uint64("filesystem::size"), info.get_attribute_uint64("filesystem::free")
    except GLib.Error:
        return None


class MaintenanceTab(Gtk.Box):
    def __init__(self, state=None, auth_manager=None) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self._state = state
        self._auth_manager = auth_manager
        self._busy = False
        self._toasts = Adw.ToastOverlay()
        self.append(self._toasts)
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self._toasts.set_child(page)

        # --- storage
        st = Adw.PreferencesGroup(title="Storage",
                                  description="Both system slots, your files and app data share one disk.")
        self._space = Adw.ActionRow(title="System disk")
        self._bar = Gtk.LevelBar(min_value=0, max_value=1, valign=Gtk.Align.CENTER, width_request=180)
        # disk USE: fine (green) to 80 %, getting full (orange) to 90 %, then
        # red - the default offsets paint "low" as a warning
        for name in ("low", "high", "full"):
            self._bar.remove_offset_value(name)
        self._bar.add_offset_value("high", 0.8)
        self._bar.add_offset_value("low", 0.9)
        self._bar.add_offset_value("disk-full", 1.0)
        self._space.add_suffix(self._bar)
        st.add(self._space)
        self._cleanup = self._action_row(st, "Clean up", "Removes downloaded update images and old backups",
                                         "Clean Up", ["pkexec", ss.DEPLOY, "--cleanup"])
        self._optimize = self._action_row(st, "Deduplicate", "Stores identical data once (Btrfs); can take a while",
                                          "Optimize", ["pkexec", ss.DEPLOY, "--optimize"])
        page.append(st)

        # --- diagnostics
        dg = Adw.PreferencesGroup(title="Diagnostics")
        row = Adw.ActionRow(title="Create a diagnostic report",
                            subtitle="Logs and system state in one file, for a bug report. Saved in your home folder.")
        self._btn_report = Gtk.Button(label="Create", valign=Gtk.Align.CENTER)
        self._btn_report.connect("clicked", lambda *_: self._report())
        row.add_suffix(self._btn_report)
        dg.add(row)
        page.append(dg)

        # --- reset
        rs = Adw.PreferencesGroup(title="Reset")
        row = Adw.ActionRow(title="Reset this computer",
                            subtitle="Back to a freshly installed state. Your files are kept unless you choose otherwise.")
        btn = Gtk.Button(label="Reset…", valign=Gtk.Align.CENTER)
        btn.add_css_class("destructive-action")
        btn.connect("clicked", lambda *_: self._reset_dialog())
        row.add_suffix(btn)
        rs.add(row)
        page.append(rs)

        # --- output of a running job
        self._out_group = Adw.PreferencesGroup(title="Progress", visible=False)
        self._out = Gtk.TextBuffer()
        tv = Gtk.TextView(buffer=self._out, editable=False, monospace=True, wrap_mode=Gtk.WrapMode.WORD_CHAR,
                          top_margin=10, bottom_margin=10, left_margin=12, right_margin=12)
        tv.add_css_class("card")
        self._out_scroll = Gtk.ScrolledWindow(child=tv, min_content_height=200, max_content_height=340,
                                              hscrollbar_policy=Gtk.PolicyType.NEVER)
        self._out_group.add(self._out_scroll)
        page.append(self._out_group)

        self._update_space()

    def _action_row(self, group, title, sub, label, argv):
        row = Adw.ActionRow(title=title, subtitle=sub)
        b = Gtk.Button(label=label, valign=Gtk.Align.CENTER)
        b.connect("clicked", lambda *_: self._run(argv, title))
        row.add_suffix(b)
        group.add(row)
        return b

    def _update_space(self) -> None:
        fs = _fs("/data") or _fs("/")
        if not fs or not fs[0]:
            self._space.set_subtitle("Unknown")
            return
        size, free = fs
        used = (size - free) / size
        self._bar.set_value(used)
        self._space.set_subtitle(f"{GLib.format_size(free)} free of {GLib.format_size(size)}"
                                 + (" - running low, updates need about 10 GB" if free < 10 * 1024**3 else ""))

    def _run(self, argv, what, inhibit: bool = True) -> None:
        if self._busy:
            return
        self._busy = True
        for b in (self._cleanup, self._optimize, self._btn_report):
            b.set_sensitive(False)
        self._out.set_text(f"{what}…\n")
        self._out_group.set_visible(True)

        def line(t):
            self._out.insert(self._out.get_end_iter(), t + "\n")
            adj = self._out_scroll.get_vadjustment()
            GLib.idle_add(lambda: adj.set_value(adj.get_upper()))

        def done(rc):
            self._busy = False
            for b in (self._cleanup, self._optimize, self._btn_report):
                b.set_sensitive(True)
            self._update_space()
            self._toasts.add_toast(Adw.Toast(title="Authorization was cancelled" if rc in (126, 127)
                                             else f"{what}: done" if rc == 0 else f"{what} did not complete"))
        ss.run_streaming(ss.inhibited(argv, what) if inhibit else argv, line, done)

    def _report(self) -> None:
        home = GLib.get_home_dir()
        self._btn_report.set_sensitive(False)
        out: list[str] = []

        def done(rc):
            self._btn_report.set_sensitive(True)
            if rc != 0:
                self._toasts.add_toast(Adw.Toast(title="Authorization was cancelled" if rc in (126, 127)
                                                 else "The report could not be created"))
                return
            t = Adw.Toast(title="Report saved in your home folder", button_label="Open Folder")
            t.connect("button-clicked", lambda *_: Gio.AppInfo.launch_default_for_uri(
                GLib.filename_to_uri(home, None), None))
            self._toasts.add_toast(t)
        ss.run_streaming(["pkexec", ss.HEALTH, "--export-logs", home], out.append, done)

    def _reset_dialog(self) -> None:
        d = Adw.AlertDialog(
            heading="Reset this computer?",
            body="Erased: settings and user accounts, Wi-Fi and Bluetooth pairings, service data "
                 "and scheduled jobs. Kept: both system slots and the boot setup. The computer restarts "
                 "when it is done.\n\nType reset to confirm.")
        grp = Adw.PreferencesGroup()
        home_sw = Adw.SwitchRow(title="Also erase all files in /home",
                                subtitle="Documents, photos, downloads - this cannot be undone")
        keep_sw = Adw.SwitchRow(title="Keep downloaded updates", subtitle="Saves downloading them again", active=True)
        typed = Adw.EntryRow(title="Type reset")
        typed_home = Adw.EntryRow(title="Type wipe home", visible=False)
        for w in (home_sw, keep_sw, typed, typed_home):
            grp.add(w)
        d.set_extra_child(grp)
        d.add_response("cancel", "Cancel")
        d.add_response("reset", "Reset and Restart")
        d.set_response_appearance("reset", Adw.ResponseAppearance.DESTRUCTIVE)
        d.set_default_response("cancel")
        d.set_close_response("cancel")

        def check(*_):
            typed_home.set_visible(home_sw.get_active())
            d.set_response_enabled("reset", typed.get_text().strip() == "reset" and
                                   (not home_sw.get_active() or typed_home.get_text().strip() == "wipe home"))
        for w in (typed, typed_home):
            w.connect("changed", check)
        home_sw.connect("notify::active", check)
        check()

        def resp(_d, r):
            if r != "reset":
                return
            argv = ["pkexec", "shani-reset", "--yes"] + (["--home"] if home_sw.get_active() else []) \
                + (["--keep-downloads"] if keep_sw.get_active() else [])
            self._run(argv, "Resetting", inhibit=False)  # it reboots when done
        d.connect("response", resp)
        d.present(self.get_root())
