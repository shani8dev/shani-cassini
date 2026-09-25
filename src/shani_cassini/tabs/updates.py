"""Updates & Rollback: the blue/green system, its channel, updating and
going back - all through shani-deploy (see system_status.py)."""

from __future__ import annotations

import logging

from gi.repository import Adw, GLib, Gtk  # type: ignore

from shani_cassini import system_status as ss

logger = logging.getLogger(__name__)

CHANNELS = [("stable", "Stable", "Tested releases (recommended)"),
            ("latest", "Latest", "Newest builds, before they are promoted to stable")]


class UpdatesTab(Gtk.Box):
    def __init__(self, state=None, auth_manager=None) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._state = state
        self._auth_manager = auth_manager
        self._status: dict = {}
        self._busy = False
        self._proc = None

        self._toasts = Adw.ToastOverlay()
        self.append(self._toasts)
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self._toasts.set_child(page)

        self._banner = Adw.Banner(revealed=False)
        self._banner.connect("button-clicked", lambda *_: self._restart())
        page.append(self._banner)

        # --- this system
        sysg = Adw.PreferencesGroup(title="This System")
        self._row_version = Adw.ActionRow(title="Version", subtitle="…")
        self._row_slot = Adw.ActionRow(title="Running from", subtitle="…")
        self._row_prev = Adw.ActionRow(title="Previous system", subtitle="…")
        for r in (self._row_version, self._row_slot, self._row_prev):
            r.set_subtitle_selectable(True)
            sysg.add(r)
        page.append(sysg)

        # --- updates
        upd = Adw.PreferencesGroup(title="Updates")
        self._channel = Adw.ComboRow(title="Update channel")
        model = Gtk.StringList()
        for _id, name, _sub in CHANNELS:
            model.append(name)
        self._channel.set_model(model)
        self._channel_handler = self._channel.connect("notify::selected", self._on_channel_changed)
        upd.add(self._channel)

        self._row_update = Adw.ActionRow(title="Checking for updates…")
        self._spinner = Gtk.Spinner(spinning=True, valign=Gtk.Align.CENTER)
        self._btn_check = Gtk.Button(label="Check", valign=Gtk.Align.CENTER)
        self._btn_check.connect("clicked", lambda *_: self.refresh(check=True))
        self._btn_update = Gtk.Button(label="Update", valign=Gtk.Align.CENTER, visible=False)
        self._btn_update.add_css_class("suggested-action")
        self._btn_update.connect("clicked", lambda *_: self._start_update())
        for w in (self._spinner, self._btn_check, self._btn_update):
            self._row_update.add_suffix(w)
        upd.add(self._row_update)
        page.append(upd)

        # --- rollback
        rb = Adw.PreferencesGroup(title="Rollback",
                                  description="Every update installs into the other system slot, so the "
                                              "previous system stays available until the next update.")
        self._row_rollback = Adw.ActionRow(title="Go back to the previous system",
                                           subtitle="Your files and settings are kept")
        self._btn_rollback = Gtk.Button(label="Roll Back…", valign=Gtk.Align.CENTER)
        self._btn_rollback.add_css_class("destructive-action")
        self._btn_rollback.connect("clicked", lambda *_: self._confirm_rollback())
        self._row_rollback.add_suffix(self._btn_rollback)
        rb.add(self._row_rollback)
        page.append(rb)

        # --- output of a running update/rollback
        self._out_group = Adw.PreferencesGroup(title="Progress", visible=False)
        self._out_buf = Gtk.TextBuffer()
        view = Gtk.TextView(buffer=self._out_buf, editable=False, monospace=True,
                            wrap_mode=Gtk.WrapMode.WORD_CHAR, cursor_visible=False)
        view.add_css_class("card")
        view.set_top_margin(10); view.set_bottom_margin(10); view.set_left_margin(12); view.set_right_margin(12)
        self._out_scroll = Gtk.ScrolledWindow(min_content_height=220, max_content_height=360,
                                              hscrollbar_policy=Gtk.PolicyType.NEVER)
        self._out_scroll.set_child(view)
        self._out_group.add(self._out_scroll)
        page.append(self._out_group)

        self.refresh(check=True)

    # ------------------------------------------------------------------ data
    def refresh(self, check: bool = False) -> None:
        self._spinner.set_visible(True)
        self._btn_check.set_sensitive(False)
        if check:
            self._row_update.set_title("Checking for updates…")
            self._row_update.set_subtitle("")
        ss.deploy_status(self._on_status, check=check)

    def _on_status(self, st, err) -> None:
        self._spinner.set_visible(False)
        self._btn_check.set_sensitive(not self._busy)
        if st is None:
            self._row_version.set_subtitle("Unavailable")
            self._row_update.set_title("Cannot read the system state")
            self._row_update.set_subtitle(err)
            for b in (self._btn_update, self._btn_rollback):
                b.set_sensitive(False)
            return
        self._status = st
        ver = st.get("version", "")
        self._row_version.set_subtitle(f"{ss.pretty_version(ver)} · {st.get('profile') or 'unknown'} edition")
        booted, prev = st.get("booted_slot") or "?", st.get("previous_slot") or ""
        self._row_slot.set_subtitle(f"Slot @{booted}")
        self._row_prev.set_subtitle(f"Slot @{prev}" if prev else "None yet - appears after the first update")
        self._btn_rollback.set_sensitive(bool(prev) and not self._busy)

        failed = st.get("boot_failure") or ""
        if failed:
            self._banner.set_title(f"The last boot of @{failed} failed - you are running the previous system")
            self._banner.set_button_label("")
            self._banner.set_revealed(True)

        idx = next((i for i, c in enumerate(CHANNELS) if c[0] == st.get("channel")), 0)
        self._channel.handler_block(self._channel_handler)
        self._channel.set_selected(idx)
        self._channel.set_subtitle(CHANNELS[idx][2])
        self._channel.handler_unblock(self._channel_handler)

        ua = st.get("update_available")
        remote = (st.get("remote") or {}).get(st.get("channel") or "stable", "")
        if ua is True:
            self._row_update.set_title(f"Shanios {ss.pretty_version(remote)} is available")
            self._row_update.set_subtitle(f"You have {ss.pretty_version(ver)}")
            self._btn_update.set_visible(True)
        elif ua is False:
            self._row_update.set_title("Your system is up to date")
            self._row_update.set_subtitle(f"Newest on {st.get('channel')}: {ss.pretty_version(remote)}")
            self._btn_update.set_visible(False)
        else:
            self._row_update.set_title("Update check did not complete")
            self._row_update.set_subtitle("No connection to the update server?")
            self._btn_update.set_visible(False)

    # --------------------------------------------------------------- actions
    def _on_channel_changed(self, row, _pspec) -> None:
        cid, _name, sub = CHANNELS[row.get_selected()]
        if cid == self._status.get("channel"):
            return
        row.set_subtitle(sub)
        self._run(["pkexec", ss.DEPLOY, "--set-channel", cid], f"Switching to {cid}",
                  after=lambda ok: (self._toast(f"Update channel: {cid}" if ok else "The channel was not changed"),
                                    self.refresh(check=True)))

    def _start_update(self) -> None:
        self._run(ss.inhibited(["pkexec", ss.DEPLOY], "Installing a Shanios update"), "Updating",
                  after=self._after_deploy, show_output=True)

    def _confirm_rollback(self) -> None:
        prev = self._status.get("previous_slot") or "the other slot"
        d = Adw.AlertDialog(heading="Go back to the previous system?",
                            body=f"Shanios will start from @{prev} after a restart. The current system "
                                 "stays installed. Your files and settings are not affected.")
        d.add_response("cancel", "Cancel")
        d.add_response("rollback", "Roll Back")
        d.set_response_appearance("rollback", Adw.ResponseAppearance.DESTRUCTIVE)
        d.set_default_response("cancel")
        d.connect("response", lambda _d, r: r == "rollback" and self._run(
            ss.inhibited(["pkexec", ss.DEPLOY, "--rollback"], "Rolling back Shanios"), "Rolling back",
            after=self._after_deploy, show_output=True))
        d.present(self.get_root())

    def _after_deploy(self, ok: bool) -> None:
        if ok:
            self._banner.set_title("Restart to start the new system")
            self._banner.set_button_label("Restart")
            self._banner.set_revealed(True)
        else:
            self._toast("It did not complete - see Progress for details")
        self.refresh(check=False)

    def _run(self, argv, what, after, show_output=False) -> None:
        if self._busy:
            return
        self._busy = True
        for b in (self._btn_update, self._btn_rollback, self._btn_check):
            b.set_sensitive(False)
        self._channel.set_sensitive(False)
        if show_output:
            self._out_buf.set_text(f"{what}…\n")
            self._out_group.set_visible(True)

        def line(t):
            if show_output:
                self._out_buf.insert(self._out_buf.get_end_iter(), t + "\n")
                adj = self._out_scroll.get_vadjustment()
                GLib.idle_add(lambda: adj.set_value(adj.get_upper()))

        def exited(rc):
            self._busy = False
            self._channel.set_sensitive(True)
            self._btn_check.set_sensitive(True)
            # systemd-inhibit passes the child's exit status through
            if rc in (126, 127) and "pkexec" in argv:
                self._toast("Authorization was cancelled")
                self.refresh(check=False)
                return
            after(rc == 0)

        self._proc = ss.run_streaming(argv, line, exited)

    def _restart(self) -> None:
        ss.run_streaming(["systemctl", "reboot"], lambda _l: None,
                         lambda rc: rc and self._toast("Could not restart - restart from the system menu"))

    def _toast(self, text: str) -> None:
        self._toasts.add_toast(Adw.Toast(title=text))
