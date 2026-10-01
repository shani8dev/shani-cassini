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

        # --- pending reboot, before anything else on the page.
        #
        # A finished deploy that is waiting for a restart is the single most
        # actionable fact this page has, and it outranks everything below it: a
        # user who reads "your system is up to date" on a machine holding an
        # installed-but-not-started update has been told the opposite of the
        # truth. So it is its own group at the top, not a subtitle on a row
        # further down.
        self._pending = Adw.PreferencesGroup(visible=False)
        self._row_reboot = Adw.ActionRow(
            title="An update is installed and waiting to start",
            subtitle="Restart to switch to it. The system you are running now "
                     "stays available to go back to.")
        self._btn_reboot = Gtk.Button(label="Restart", valign=Gtk.Align.CENTER)
        self._btn_reboot.add_css_class("suggested-action")
        self._btn_reboot.connect("clicked", lambda *_: self._restart())
        self._row_reboot.add_suffix(self._btn_reboot)
        self._pending.add(self._row_reboot)
        page.append(self._pending)

        # --- this system
        sysg = Adw.PreferencesGroup(title="This System")
        self._row_version = Adw.ActionRow(title="Version", subtitle="…")
        self._row_slot = Adw.ActionRow(title="Running from", subtitle="…")
        self._row_prev = Adw.ActionRow(title="Previous system", subtitle="…")
        for row in (self._row_version, self._row_slot, self._row_prev):
            row.set_subtitle_selectable(True)
            # Inside the loop, and named for what it is. `sysg.add(r)` sat
            # *outside* it until 2026-10-01, so only the last row was ever
            # added: "Version" and "Running from" were built, assigned to
            # attributes, updated on every status read - and never shown. Every
            # value they carried went to a widget with no parent, which is why
            # reading them back out of the tree found nothing while the code
            # looked correct and the row objects existed.
            sysg.add(row)

        # The slot the bootloader will actually start next, which is not always
        # the slot being run - after a failed boot, or after a rollback has
        # already moved the default, they differ and the difference is the whole
        # reason a user needs this page.
        self._row_default = Adw.ActionRow(title="Will start next from", subtitle="…")
        self._row_default.set_subtitle_selectable(True)
        sysg.add(self._row_default)
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

        # --- what the update is doing, and its own log
        #
        # Two widgets answering two different questions. The phase bar answers
        # "how far along is this", which the phase names alone can answer and a
        # wall of log text cannot: the deploy script's phases are a fixed,
        # ordered list, so the phase it has reached is real progress. The log
        # answers "what exactly did it say", for when the answer matters.
        self._out_group = Adw.PreferencesGroup(title="Update in progress", visible=False)
        self._phase_bar = Gtk.ProgressBar(show_text=True, valign=Gtk.Align.CENTER,
                                          hexpand=True)
        self._phase_bar.set_valign(Gtk.Align.CENTER)
        phase_row = Adw.ActionRow(title="Stage")
        phase_row.add_suffix(self._phase_bar)
        self._out_group.add(phase_row)

        self._out_buf = Gtk.TextBuffer()
        view = Gtk.TextView(buffer=self._out_buf, editable=False, monospace=True,
                            wrap_mode=Gtk.WrapMode.WORD_CHAR, cursor_visible=False)
        view.add_css_class("card")
        view.set_top_margin(10); view.set_bottom_margin(10)
        view.set_left_margin(12); view.set_right_margin(12)
        self._out_scroll = Gtk.ScrolledWindow(min_content_height=180, max_content_height=340,
                                              hscrollbar_policy=Gtk.PolicyType.NEVER)
        self._out_scroll.set_child(view)
        self._out_group.add(self._out_scroll)
        page.append(self._out_group)

        self._phase_index = -1
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
        booted = st.get("booted_slot") or ""
        cur = st.get("current_slot") or ""
        prev = st.get("previous_slot") or ""
        self._row_slot.set_subtitle(f"Slot @{booted}" if booted else "Unknown")
        self._row_prev.set_subtitle(f"Slot @{prev}" if prev else "None yet - appears after the first update")
        self._btn_rollback.set_sensitive(bool(prev) and not self._busy)

        # Which slot the bootloader will start next, which is `current_slot` -
        # the deploy script's own name for the slot whose UKI the loader points
        # at. It is not `booted_slot`: after a failed boot, or after a rollback
        # has already moved the default, the two disagree, and *that* is what
        # makes a failed boot legible. Rendering it as the same row as the booted
        # slot would hide the only fact that distinguishes the two states.
        self._row_default.set_subtitle(
            f"Slot @{cur}" if cur else "Unknown - shani-deploy did not report one")

        self._render_pending(st)
        self._render_health(st, booted, cur)

        idx = next((i for i, c in enumerate(CHANNELS) if c[0] == st.get("channel")), 0)
        self._channel.handler_block(self._channel_handler)
        self._channel.set_selected(idx)
        self._channel.set_subtitle(CHANNELS[idx][2])
        self._channel.handler_unblock(self._channel_handler)

        self._render_update_row(st, ver)

    def _render_pending(self, st: dict) -> None:
        """The waiting-for-a-restart group, or nothing.

        Shown when `reboot_needed` names a version, which finalize_update writes
        once a deploy has finished and every rollback path removes. It is the one
        state where this page has something to *do* about the system rather than
        merely report it, and it is placed above everything else for that reason.

        `candidate_boot` is not consulted here, deliberately: the deploy script
        derives it from the reboot marker *plus* both slot markers, and its own
        comment says it must not be inferred from `booted != current` - which is
        equally true after a bootloader fallback, where nothing is pending. A
        restart offered on that basis would be offered for a failure, so the
        narrower marker is what gates this.
        """
        waiting = str(st.get("reboot_needed") or "")
        if not waiting:
            self._pending.set_visible(False)
            return
        self._row_reboot.set_subtitle(
            f"Shanios {ss.pretty_version(waiting)} is installed and will start on "
            f"the next restart. The system you are running now stays available "
            f"to go back to.")
        self._pending.set_visible(True)

    def _render_health(self, st: dict, booted: str, cur: str) -> None:
        """Boot failure, hard boot failure, or neither - said plainly.

        The hard marker takes priority because the dracut hook writes it before
        the root mount is even attempted, so it is the earlier and the worse
        fact. Both are read from files the boot machinery really wrote.

        A boot failure outranks the pending-reboot group, and the pending group
        outranks everything else - so this yields to it rather than the two
        saying the same thing in two places. Found by rendering the page against
        a status carrying *both* markers, which is exactly the state after a
        failed boot of a slot an update had just written: the screenshot showed
        "the last boot of @green failed" directly above "restart to switch to
        it", which is two alarms for one situation and reads as noise.
        """
        hard = str(st.get("boot_hard_failure") or "")
        soft = str(st.get("boot_failure") or "")
        if hard:
            self._banner.set_title(
                f"The last boot of @{hard} failed before it could mount the system")
            self._banner.set_button_label("")
            self._banner.set_revealed(True)
            return
        if soft:
            where = (f" - you are running @{booted}" if booted and booted != soft
                     else "")
            self._banner.set_title(f"The last boot of @{soft} failed{where}")
            self._banner.set_button_label("")
            self._banner.set_revealed(True)
            return
        if self._pending.get_visible():
            # A reboot is waiting and nothing has failed: the group above says
            # it with a button attached, so a banner repeating it adds nothing.
            self._banner.set_revealed(False)
            return
        if not self._busy:
            # A banner left up from a previous read would keep claiming a failure
            # that has since been cleared or acknowledged.
            self._banner.set_revealed(False)

    def _render_update_row(self, st: dict, ver: str) -> None:
        """The one row that answers "is there anything to install".

        Three answers, not two: `update_available` is null when the check could
        not reach the server, and that is not the same as "up to date". The
        previous version of this collapsed null into false in its wording
        elsewhere; here null gets its own line because it is the state a user on
        a plane needs told apart from "there is nothing new".
        """
        channel = st.get("channel") or "stable"
        remote = (st.get("remote") or {}).get(channel, "")
        ua = st.get("update_available")
        if ua is True:
            self._row_update.set_title(f"Shanios {ss.pretty_version(remote)} is available")
            self._row_update.set_subtitle(f"You have {ss.pretty_version(ver)} · {channel}")
            self._btn_update.set_visible(True)
        elif ua is False:
            self._row_update.set_title("Your system is up to date")
            self._row_update.set_subtitle(f"Newest on {channel}: {ss.pretty_version(remote)}")
            self._btn_update.set_visible(False)
        else:
            self._row_update.set_title("Update check did not complete")
            self._row_update.set_subtitle(
                f"You have {ss.pretty_version(ver)} - the update server did not "
                f"answer, so this is not a claim that you are up to date")
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
                  after=self._after_deploy, show_output=True, phases=ss.DEPLOY_PHASES)

    def _confirm_rollback(self) -> None:
        prev = self._status.get("previous_slot") or "the other slot"
        # Name the version that will actually be booted, not just the slot name.
        # A slot is an internal label; "2026.09.30" is the thing the user is
        # deciding about, and the deploy script's own listing is the only place
        # a slot's version exists. Asked for when the dialog opens rather than
        # on page load, because that listing is a root call.
        d = Adw.AlertDialog(heading="Go back to the previous system?",
                            body=f"Shanios will start from @{prev} after a restart. The current system "
                                 "stays installed. Your files and settings are not affected.")
        d.add_response("cancel", "Cancel")
        d.add_response("rollback", "Roll Back")
        d.set_response_appearance("rollback", Adw.ResponseAppearance.DESTRUCTIVE)
        d.set_default_response("cancel")
        d.set_close_response("cancel")

        def responded(_d, r):
            if r != "rollback":
                return
            self._run(ss.inhibited(["pkexec", ss.DEPLOY, "--rollback"], "Rolling back Shanios"),
                      "Rolling back", after=self._after_deploy, show_output=True,
                      phases=ss.ROLLBACK_PHASES)

        d.connect("response", responded)
        d.present(self.get_root())

    def _after_deploy(self, ok: bool) -> None:
        if ok:
            # The reboot marker is what actually proves an update is waiting, and
            # the refresh below reads it - so this banner is a prompt, not the
            # claim. Left up only until that read lands, and _render_health takes
            # it down again when there is nothing to report.
            self._banner.set_title("Restart to start the new system")
            self._banner.set_button_label("Restart")
            self._banner.set_revealed(True)
        else:
            self._toast("It did not complete - see the log below for details")
        self.refresh(check=False)

    # --------------------------------------------------------------- progress
    def _start_progress(self, what: str, phases: tuple[str, ...]) -> None:
        """Show the stage bar, empty, and clear the log from the last run.

        The bar starts at zero and no text, rather than at the first phase: a
        bar that reads "Download Phase" before the script has printed anything
        is a phase this page guessed, and the whole point of the bar is that it
        is not a guess.
        """
        self._phases = phases
        self._phase_index = -1
        self._phase_bar.set_fraction(0.0)
        self._phase_bar.set_text("starting…")
        self._out_buf.set_text(f"{what}…\n")
        self._out_group.set_visible(True)

    def _on_line(self, raw: str) -> None:
        """One line of the deploy script's own output.

        Kept in the log verbatim - with the deploy script's own timestamp prefix
        stripped, because a column of near-identical dates is noise - and the
        phase bar is driven from whichever phase the line belongs to. A progress
        redraw is not a log line: it would append hundreds of near-identical
        rows, so it moves the bar and says nothing.
        """
        for kind, _level, message in ss.parse_deploy_line(raw):
            if kind == "progress":
                self._on_progress(message)
            elif kind == "phase":
                self._on_phase(message)
            else:
                self._append(message)

    def _on_phase(self, name: str) -> None:
        self._phase_bar.set_text(name)
        if name in self._phases:
            self._phase_index = self._phases.index(name)
        else:
            # A phase this build does not know about - the script gained one, or
            # a rollback logs a section the table lacks. Shown as text and the
            # bar left where it is: inventing a fraction for an unknown phase
            # would be the one number on this page Cassini made up.
            self._append(f"— {name} —")
            return
        self._phase_bar.set_fraction((self._phase_index + 1) / len(self._phases))
        self._append(f"— {name} —")

    def _on_progress(self, percent: str) -> None:
        """A download percentage: the bar itself, while the phase is download.

        Outside the download phase a percentage means nothing Cassini can place -
        and a btrfs balance or a copy also prints percentages - so it is not
        allowed to move the stage bar outside it.
        """
        if self._phase_index < 0 or self._phases[self._phase_index] != "Download Phase":
            return
        try:
            value = float(percent.rstrip("%"))
        except ValueError:
            return
        # The stage bar shows the whole update; the download's own share of it is
        # too useful to lose, so it is reported as the bar's text instead of
        # being drawn over the stage fraction.
        self._phase_bar.set_text(f"{percent} downloaded")

    def _append(self, text: str) -> None:
        if not text:
            return
        self._out_buf.insert(self._out_buf.get_end_iter(), text + "\n")
        adj = self._out_scroll.get_vadjustment()
        GLib.idle_add(lambda: adj.set_value(adj.get_upper()))

    def _run(self, argv, what, after, show_output=False, phases=()) -> None:
        if self._busy:
            return
        self._busy = True
        for b in (self._btn_update, self._btn_rollback, self._btn_check,
                  self._btn_reboot):
            b.set_sensitive(False)
        self._channel.set_sensitive(False)
        if show_output:
            self._start_progress(what, phases or ("",))

        def line(t):
            if show_output:
                self._on_line(t)

        def exited(rc):
            self._busy = False
            self._channel.set_sensitive(True)
            self._btn_check.set_sensitive(True)
            # systemd-inhibit passes the child's exit status through
            if rc in (126, 127) and "pkexec" in argv:
                self._toast("Authorization was cancelled")
                self.refresh(check=False)
                return
            if show_output and rc == 0:
                self._phase_bar.set_fraction(1.0)
                self._phase_bar.set_text("done")
            after(rc == 0)

        self._proc = ss.run_streaming(argv, line, exited)

    def _restart(self) -> None:
        ss.run_streaming(["systemctl", "reboot"], lambda _l: None,
                         lambda rc: rc and self._toast("Could not restart - restart from the system menu"))

    def _toast(self, text: str) -> None:
        self._toasts.add_toast(Adw.Toast(title=text))
