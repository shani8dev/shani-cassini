"""Fingerprint: fprintd's own answer about this machine's reader and fingers.

Everything here comes from fprintd over D-Bus
(``net.reactivated.fprint``), which is the same interface ``pam_fprintd``
itself talks to, so what the page says is what a login attempt would see.
No pkexec and no helper binary: ``shani-settings``' 99-shani.rules already
grants ``net.reactivated.fprint.device.enroll`` / ``.delete`` as
``polkit.Result.AUTH_SELF``, so fprintd asks polkit over D-Bus and the
desktop password dialog appears on its own - exactly how ``services.py``
drives systemctl. (Cassini ships no policy of its own on purpose: an
``org.freedesktop.policykit.exec.path`` action would override the system
rules for every caller.)

The page never guesses. A daemon that does not answer, a reader that is not
attached and a reader with nothing enrolled are three different answers,
and only the last one is "no fingerprints".
"""

from __future__ import annotations

import logging
import os
import time

from gi.repository import Adw, GLib, Gtk  # type: ignore

from shani_cassini import system_status as ss

logger = logging.getLogger(__name__)

# How often the enrollment loop looks at fprintd's Action property, and how
# long it may go on: a person who walks away mid-enrollment must not leave
# the reader claimed (a claimed reader is unusable by anything else,
# including the lock screen).
ENROLL_POLL_MS = 700
ENROLL_TIMEOUT_S = 90

# state -> (icon, css class), as in health.py's STATUS
STATE_ICONS = {
    "ok": ("object-select-symbolic", "success"),
    "problem": ("dialog-warning-symbolic", "warning"),
    "error": ("dialog-error-symbolic", "error"),
    "unknown": ("dialog-information-symbolic", None),
}

FINGERS_HELP = ("Each one is a scan template, not an image. Deleting one asks for your "
                "password through polkit.")


def _row(title: str, subtitle: str = "", icon: str | None = None,
         cls: str | None = None) -> Adw.ActionRow:
    r = Adw.ActionRow(title=title, subtitle=subtitle)
    if icon:
        img = Gtk.Image.new_from_icon_name(icon)
        if cls:
            img.add_css_class(cls)
        r.add_prefix(img)
    return r


def _finger_label(finger: str) -> str:
    """fprintd's "right-index-finger" -> "Right index finger"."""
    return " ".join(p.capitalize() for p in str(finger).split("-") if p)


def _esc(value: object) -> str:
    """Every string that came out of fprintd is escaped before it is markup."""
    return GLib.markup_escape_text(str(value))


class BiometricsTab(Gtk.Box):
    def __init__(self, state=None, auth_manager=None) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self._state = state
        self._auth_manager = auth_manager
        self._toasts = Adw.ToastOverlay()
        self.append(self._toasts)
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self._toasts.set_child(page)
        self._page = page

        self._status: dict | None = None
        self._enroll: dict | None = None
        self._uid = os.getuid()
        self._icons: dict[Adw.ActionRow, Gtk.Image] = {}

        self._build()
        self.refresh()
        self._load_edition()

    # ------------------------------------------------------------- building
    def _build(self) -> None:
        reader = Adw.PreferencesGroup(
            title="Fingerprint reader",
            description="Read by fprintd (net.reactivated.fprint) on this system's own bus. "
                        "fprintd ships with every Shanios edition, in shani-peripherals.")
        self._row_daemon = _row("fprintd", "Asking it…")
        reader.add(self._row_daemon)
        self._row_device = _row("Reader", "Asking it…")
        reader.add(self._row_device)
        self._row_fingers = _row("Enrolled fingers", "Asking it…")
        self._btn_refresh = Gtk.Button(label="Refresh", valign=Gtk.Align.CENTER)
        self._btn_refresh.connect("clicked", lambda *_: self.refresh())
        self._row_fingers.add_suffix(self._btn_refresh)
        reader.add(self._row_fingers)
        self._page.append(reader)

        self._fingers_group = self._fingers_group_new(None)
        self._page.append(self._fingers_group)

        add = Adw.PreferencesGroup(
            title="Add a Fingerprint",
            description="Scan the same finger several times as asked. fprintd asks polkit for "
                        "your password once, then the reader belongs to it until you cancel or "
                        "it finishes.")
        self._entry_name = Adw.EntryRow(title="Name this finger", text="Right index finger")
        add.add(self._entry_name)
        self._row_enroll = _row("Enroll", "Needs a reader")
        self._btn_enroll = Gtk.Button(label="Enroll…", valign=Gtk.Align.CENTER, sensitive=False)
        self._btn_enroll.add_css_class("suggested-action")
        self._btn_enroll.connect("clicked", lambda *_: self._start_enroll())
        self._btn_cancel = Gtk.Button(label="Cancel", valign=Gtk.Align.CENTER, visible=False)
        self._btn_cancel.add_css_class("destructive-action")
        self._btn_cancel.connect("clicked", lambda *_: self.cancel_enroll())
        self._row_enroll.add_suffix(self._btn_cancel)
        self._row_enroll.add_suffix(self._btn_enroll)
        add.add(self._row_enroll)
        self._page.append(add)

        where = Adw.PreferencesGroup(
            title="Where a Fingerprint Works",
            description="The PAM service that makes an enrolled finger usable ships with the "
                        "display manager, not with fprintd, so this differs per edition.")
        self._row_edition = _row("This edition", "Reading it…")
        where.add(self._row_edition)
        head, detail = ss.SUDO_NEVER
        where.add(_row(head, detail, "dialog-information-symbolic"))
        self._page.append(where)

        cli = Adw.PreferencesGroup(
            title="From a Terminal",
            description="The same fprintd, if you would rather do it by hand (all four are in "
                        "/usr/sbin):")
        for cmd, what in (("fprintd-enroll", "enroll a finger"),
                          ("fprintd-list", "list the enrolled ones"),
                          ("fprintd-verify", "test a scan"),
                          ("fprintd-delete", "delete one")):
            cli.add(_row(cmd, what))
        self._page.append(cli)

    def _fingers_group_new(self, fingers: list | None) -> Adw.PreferencesGroup:
        g = Adw.PreferencesGroup(title="Enrolled Fingers", visible=bool(fingers),
                                 description=FINGERS_HELP)
        for f in fingers or []:
            r = _row(_esc(f["nickname"]),
                     f"{_esc(_finger_label(f['finger']))} · {_esc(f['state'])}")
            b = Gtk.Button(label="Delete…", valign=Gtk.Align.CENTER)
            b.add_css_class("destructive-action")
            b.connect("clicked", lambda _b, uid=f["uid"]: self._delete(uid))
            r.add_suffix(b)
            g.add(r)
        return g

    # ------------------------------------------------------------------ data
    def refresh(self) -> None:
        self._btn_refresh.set_sensitive(False)
        ss.fprintd_status(self._on_status, timeout_s=5.0)

    def _on_status(self, status, err: str) -> None:
        self._btn_refresh.set_sensitive(True)
        if status is None:
            self._status = None
            if not ss.fprintd_installed():
                self._set(self._row_daemon, "fprintd",
                          "Not installed - fprintd is missing (it ships in shani-peripherals)",
                          "error")
            else:
                self._set(self._row_daemon, "fprintd", _esc(err or "fprintd did not answer"),
                          "error")
            self._set(self._row_device, "Reader", "Not known - fprintd did not answer", None)
            self._set(self._row_fingers, "Enrolled fingers", "Not known - fprintd did not answer",
                      None)
            self._set_enrollable(False)
            self._replace_fingers(None)
            return

        self._status = status
        self._set(self._row_daemon, "fprintd", "Running", "ok")

        if not status["device_present"]:
            self._set(self._row_device, "Reader", "No reader found - attach one and refresh",
                      "warning")
            self._set(self._row_fingers, "Enrolled fingers", "Not known - no reader to ask",
                      None)
            self._set_enrollable(False)
            self._replace_fingers(None)
            return

        name = _esc(status["device_name"] or "Unnamed reader")
        driver = _esc(status["driver"] or "driver not reported")
        off = "" if status["enabled"] is not False else " · switched off in fprintd"
        self._set(self._row_device, "Reader", f"{name} · {driver}{off}", "ok")

        fingers = status["fingers"]
        enrolled = len(fingers)
        self._set(self._row_fingers, "Enrolled fingers",
                  f"{enrolled} enrolled" if enrolled else "None - add one below to use a fingerprint",
                  "ok" if enrolled else None)
        self._set_enrollable(True)
        self._replace_fingers(fingers)

    def _set(self, row: Adw.ActionRow, title: str, subtitle: str, state: str | None) -> None:
        """Set a status row's text and its leading icon, from STATE_ICONS.

        `title` and `subtitle` must already be escaped by the caller: they
        carry fprintd's own strings."""
        row.set_title(title)
        row.set_subtitle(subtitle)
        icon, cls = STATE_ICONS.get(state or "unknown", STATE_ICONS["unknown"])
        old = self._icons.pop(row, None)
        if old is not None:
            row.remove(old)
        img = Gtk.Image.new_from_icon_name(icon)
        if cls:
            img.add_css_class(cls)
        row.add_prefix(img)
        self._icons[row] = img

    def _set_enrollable(self, ok: bool) -> None:
        self._btn_enroll.set_sensitive(bool(ok))

    def _replace_fingers(self, fingers: list | None) -> None:
        parent = self._fingers_group.get_parent()
        parent.remove(self._fingers_group)
        self._fingers_group = self._fingers_group_new(fingers)
        parent.append(self._fingers_group)

    def _load_edition(self) -> None:
        """The edition is the only thing that decides what a finger can unlock,
        so it is read from shani-deploy's own status, not guessed from the
        running desktop."""
        def got(st, err):
            if st is None:
                self._set(self._row_edition, "This edition",
                          "Not known - Shanios's own status could not be read, so what a "
                          "fingerprint can unlock here is not known", "unknown")
                return
            profile = str(st.get("profile") or "")
            head, detail = ss.edition_login(profile)
            title = f"This edition: {_esc(profile)}" if profile else "This edition"
            self._set(self._row_edition, title, f"{head}. {detail}",
                      "ok" if profile.lower() in ss.EDITION_LOGIN else "unknown")
        ss.deploy_status(got)

    # ------------------------------------------------------------ enrolling
    def _start_enroll(self) -> None:
        if self._enroll is not None:
            return
        if self._status is None or not self._status.get("device_present"):
            self._toast("No reader to enroll on - attach one first")
            return
        path = self._status.get("path") or ""
        nickname = self._entry_name.get_text().strip()
        if not path or not nickname:
            self._toast("The reader or the finger's name is missing")
            return
        self._enroll = {"path": path, "nickname": nickname, "busy": False, "scans": 0,
                        "deadline": time.monotonic() + ENROLL_TIMEOUT_S, "timer": 0}
        self._enrolling(True, "Asking fprintd to start…")
        ss.fprintd_enroll_start(path, nickname, self._on_enroll_start)

    def _on_enroll_start(self, _res, err: str) -> None:
        if self._enroll is None:
            return
        if err:
            self._end_enroll(err)
            return
        self._enrolling(True, f"Touch the reader with {_esc(self._enroll['nickname'])}")
        self._enroll["timer"] = GLib.timeout_add(ENROLL_POLL_MS, self._enroll_tick)

    def _enroll_tick(self) -> bool:
        """One step of the loop: read fprintd's Action, and scan while it says
        "enroll". Returns False to drop the timeout - the only ways out are a
        finished, a cancelled and a timed-out enrollment, so the loop cannot
        outlive the page."""
        e = self._enroll
        if e is None:
            return False
        if time.monotonic() > e["deadline"]:
            e["timer"] = 0        # this source dies with this return
            self._end_enroll(f"No scan for {ENROLL_TIMEOUT_S} seconds - enrollment was stopped")
            return False
        if e["busy"]:
            return True           # a call is in flight; its callback re-arms us
        e["busy"] = True
        ss.fprintd_properties(e["path"], self._on_action)
        return True

    def _on_action(self, props, err: str) -> None:
        e = self._enroll
        if e is None:
            return
        e["busy"] = False
        if err or props is None:
            self._end_enroll(err or "fprintd did not answer")
            return
        action = str(props.get("Action") or "")
        if action != "enroll":
            # fprintd clears Action once the last scan is stored (FingerAdded)
            self._end_enroll("Enrollment finished" if action == "" and e["scans"]
                             else "fprintd stopped asking for scans")
            return
        self._enrolling(True, f"Touch the reader with {_esc(e['nickname'])}")
        ss.fprintd_enroll(e["path"], self._uid, self._on_enrolled)

    def _on_enrolled(self, res, err: str) -> None:
        e = self._enroll
        if e is None:
            return
        e["busy"] = False
        if err:
            self._end_enroll(err)
            return
        # Enroll() -> (bs), one argument of the reply, so the unpacked value is
        # [(accepted, reason)]. A rejected scan is a normal answer, not a
        # failure: the loop simply asks again.
        reply = res[0] if res else None
        accepted = bool(reply[0]) if reply else False
        reason = str(reply[1]) if reply and len(reply) > 1 else ""
        if accepted:
            e["scans"] += 1
            self._enrolling(True,
                            f"Scan stored ({e['scans']}) - lift your finger and touch it again")
        else:
            self._enrolling(True, f"Scan not accepted{': ' + _esc(reason) if reason else ''}")

    def cancel_enroll(self) -> None:
        if self._enroll is None:
            return
        self._end_enroll("Enrollment cancelled - nothing was changed")

    def _end_enroll(self, text: str) -> None:
        e, self._enroll = self._enroll, None
        self._enrolling(False)
        if e is None:
            return
        if e["timer"]:
            GLib.source_remove(e["timer"])
        # EnrollStop on every path: a reader left mid-enroll stays claimed and
        # unusable by the lock screen too.
        ss.fprintd_enroll_stop(e["path"], lambda _r, _err: self._enroll_finished(text))

    def _enroll_finished(self, text: str) -> None:
        self._toast(text)
        self.refresh()

    def _enrolling(self, on: bool, message: str | None = None) -> None:
        self._btn_enroll.set_visible(not on)
        self._btn_cancel.set_visible(on)
        self._entry_name.set_sensitive(not on)
        if message is not None:
            self._row_enroll.set_subtitle(message)
            return
        if on:
            return
        has_reader = self._status is not None and bool(self._status.get("device_present"))
        self._row_enroll.set_subtitle("Needs a reader" if not has_reader
                                      else "Scan the same finger several times as asked")
        self._set_enrollable(has_reader)

    # -------------------------------------------------------------- deleting
    def _delete(self, uid: int) -> None:
        status = self._status
        if status is None or not status.get("path"):
            self._toast("fprintd did not answer - nothing was deleted")
            return
        self._set_enrollable(False)

        def done(_res, err):
            self._set_enrollable(bool(status.get("device_present")))
            self._toast(err if err else "The finger was deleted")
            self.refresh()
        ss.fprintd_delete(status["path"], uid, done)

    def _toast(self, text: str) -> None:
        self._toasts.add_toast(Adw.Toast(title=GLib.markup_escape_text(text), timeout=6))
