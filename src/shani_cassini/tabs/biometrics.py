"""Fingerprint: fprintd's own answer about this machine's reader and fingers.

Everything here comes from fprintd over D-Bus
(``net.reactivated.fprint``), which is the same interface ``pam_fprintd``
itself talks to, so what the page says is what a login attempt would see.
The calls are the ten methods the daemon's own interface description lists,
in the order its reference client uses them: Claim, EnrollStart, wait for
EnrollStatus, EnrollStop, Release. There is no per-scan Enroll() call and no
Delete(): the Device interface has neither, and it has no Action or
DevicePresent property either - a reader is attached exactly when GetDevices
returns a path.

No pkexec and no helper binary: ``shani-settings``' 99-shani.rules already
grants ``net.reactivated.fprint.device.enroll`` / ``.delete`` as
``polkit.Result.AUTH_SELF`` and ``.verify`` / ``.identify`` as ``YES``, so
fprintd asks polkit over D-Bus and the desktop password dialog appears on its
own - exactly how ``services.py`` drives systemctl. (Cassini ships no policy
of its own on purpose: an ``org.freedesktop.policykit.exec.path`` action
would override the system rules for every caller.)

The page never guesses. A daemon that does not answer, a reader that is not
attached and a reader with nothing enrolled are three different answers, and
only the last one is "no fingerprints".
"""

from __future__ import annotations

import logging

from gi.repository import Adw, GLib, Gtk  # type: ignore

from shani_cassini import system_status as ss

logger = logging.getLogger(__name__)

# How long one enrollment may run before the page stops it. A person who walks
# away must not leave the reader claimed: a claimed reader is unusable by
# anything else, including the lock screen, until Release().
ENROLL_TIMEOUT_S = 120

# state -> (icon, css class), as in health.py's STATUS
STATE_ICONS = {
    "ok": ("object-select-symbolic", "success"),
    "problem": ("dialog-warning-symbolic", "warning"),
    "error": ("dialog-error-symbolic", "error"),
    "unknown": ("dialog-information-symbolic", None),
}

FINGERS_HELP = ("Each one is a stored scan of that finger, not an image. Deleting one asks for "
                "your password through polkit.")


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
            description="fprintd claims the reader for you, so nothing else can use it until "
                        "this finishes. It asks for your password once, then it waits for the "
                        "scans.")
        # EnrollStart takes one of fprintd's ten finger names and rejects
        # anything else ("any" included), so this offers exactly those.
        self._picker = Adw.ComboRow(
            title="Finger", model=Gtk.StringList.new([_finger_label(f) for f in ss.FINGER_NAMES]))
        self._picker.set_selected(list(ss.FINGER_NAMES).index("right-index-finger"))
        add.add(self._picker)
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
            r = _row(_esc(_finger_label(f)), "Enrolled on this device")
            b = Gtk.Button(label="Delete…", valign=Gtk.Align.CENTER)
            b.add_css_class("destructive-action")
            b.connect("clicked", lambda _b, finger=f: self._delete(finger))
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

        name = _esc(status["name"] or "Unnamed reader")
        scan = _esc(status["scan_type"] or "scan type not reported")
        stages = status["num_enroll_stages"]
        how = f" · {stages} scans per finger" if isinstance(stages, int) and stages > 0 else ""
        self._set(self._row_device, "Reader", f"{name} · {scan}{how}", "ok")

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
    def _chosen_finger(self) -> str:
        index = self._picker.get_selected()
        if not 0 <= index < len(ss.FINGER_NAMES):
            return ""
        return ss.FINGER_NAMES[index]

    def _start_enroll(self) -> None:
        if self._enroll is not None:
            return
        if self._status is None or not self._status.get("device_present"):
            self._toast("No reader to enroll on - attach one first")
            return
        path = self._status.get("path") or ""
        finger = self._chosen_finger()
        if not path or not finger:
            self._toast("The reader or the finger is missing")
            return
        self._enroll = {"path": path, "finger": finger, "claimed": False, "started": False,
                        "stages": 0, "busy": False, "sub": None, "timer": 0}
        self._enrolling(True, "Asking fprintd for the reader…")
        ss.fprintd_claim(path, self._on_claimed)

    def _on_claimed(self, _res, err: str) -> None:
        if self._enroll is None:
            return
        if err:
            self._end_enroll(self._claim_error(err))
            return
        e = self._enroll
        e["claimed"] = True
        # Subscribe before EnrollStart: the first signal can arrive as soon as
        # it returns, exactly as fprintd's own client does.
        e["sub"] = ss.fprintd_subscribe_enroll_status(e["path"], self._on_enroll_status)
        self._enrolling(True, "Starting…")
        ss.fprintd_enroll_start(e["path"], e["finger"], self._on_enrolled)

    def _on_enrolled(self, _res, err: str) -> None:
        """EnrollStart's own answer: no per-scan reply exists, so all progress
        comes from EnrollStatus from here on."""
        if self._enroll is None:
            return
        if err:
            self._end_enroll(self._start_error(err))
            return
        self._enroll["started"] = True
        self._enrolling(True, f"Touch the reader with your {_esc(_finger_label(self._enroll['finger']))}")
        self._enroll["timer"] = GLib.timeout_add_seconds(ENROLL_TIMEOUT_S, self._enroll_deadline)

    def _enroll_deadline(self) -> bool:
        if self._enroll is not None:
            self._enroll["timer"] = 0
            self._end_enroll(f"No completed scan in {ENROLL_TIMEOUT_S} seconds - "
                             f"enrollment was stopped")
        return False

    def _on_enroll_status(self, reason: str, done: bool) -> None:
        e = self._enroll
        if e is None:
            return
        if reason in ("enroll-stage-passed", "enroll-completed"):
            e["stages"] += 1
        if done:
            ok = reason == "enroll-completed"
            self._end_enroll("Fingerprint stored" if ok
                             else f"Enrollment did not finish: {ss.enroll_status_text(reason)}")
            return
        self._show_progress(reason)

    def _show_progress(self, reason: str) -> None:
        """The signal's own words, plus the two live properties that say whether
        a finger is on the reader right now."""
        e = self._enroll
        text = ss.enroll_status_text(reason)
        stages = self._status.get("num_enroll_stages") if self._status else None
        if isinstance(stages, int) and stages > 0 and e["stages"]:
            text = f"({e['stages']}/{stages}) {text}"
        self._row_enroll.set_subtitle(_esc(text))
        if e["busy"]:
            return
        e["busy"] = True
        ss.fprintd_properties(e["path"], self._on_live)

    def _on_live(self, props, err: str) -> None:
        e = self._enroll
        if e is None:
            return
        e["busy"] = False
        if err or props is None:
            return
        if props.get("finger-present"):
            self._row_enroll.set_subtitle(f"{self._row_enroll.get_subtitle()} · finger detected")
        elif props.get("finger-needed"):
            self._row_enroll.set_subtitle(f"{self._row_enroll.get_subtitle()} · waiting for a finger")

    def cancel_enroll(self) -> None:
        if self._enroll is None:
            return
        self._end_enroll("Enrollment cancelled - nothing was changed")

    def _end_enroll(self, text: str) -> None:
        """Every way out of enrollment goes through here: stop the scans, drop
        the signal subscription and give the reader back, in that order, each
        step only if the previous one actually ran."""
        e, self._enroll = self._enroll, None
        self._enrolling(False)
        if e is None:
            return
        if e["timer"]:
            GLib.source_remove(e["timer"])
        ss.fprintd_unsubscribe(e["sub"])
        if not e["claimed"]:
            self._enroll_finished(text)
            return
        if not e["started"]:
            ss.fprintd_release(e["path"], lambda _r, err: self._enroll_finished(
                self._with_problem(text, err)))
            return
        ss.fprintd_enroll_stop(e["path"],
                               lambda _r, err: self._release(e, self._with_problem(text, err)))

    def _release(self, e: dict, text: str) -> None:
        ss.fprintd_release(e["path"], lambda _r, err: self._enroll_finished(
            self._with_problem(text, err)))

    @staticmethod
    def _with_problem(text: str, err: str) -> str:
        return f"{text} - fprintd could not close the reader: {err}" if err else text

    def _enroll_finished(self, text: str) -> None:
        self._toast(text)
        self.refresh()

    def _enrolling(self, on: bool, message: str | None = None) -> None:
        self._btn_enroll.set_visible(not on)
        self._btn_cancel.set_visible(on)
        self._picker.set_sensitive(not on)
        if message is not None:
            self._row_enroll.set_subtitle(message)
            return
        if on:
            return
        has_reader = self._status is not None and bool(self._status.get("device_present"))
        self._row_enroll.set_subtitle("Needs a reader" if not has_reader
                                      else "Scan the same finger as often as fprintd asks")
        self._set_enrollable(has_reader)

    def _claim_error(self, err: str) -> str:
        if "PermissionDenied" in err or "Not Authorized" in err:
            return "Authorization was cancelled"
        if "AlreadyInUse" in err:
            return "Another program is using the reader"
        return f"Could not take the reader: {err}"

    def _start_error(self, err: str) -> str:
        if "ClaimDevice" in err:
            return "fprintd did not hand over the reader"
        if "InvalidFingername" in err:
            return "fprintd does not accept that finger"
        if "AlreadyInUse" in err:
            return "Another program is using the reader"
        return f"Could not start enrolling: {err}"

    # -------------------------------------------------------------- deleting
    def _delete(self, finger: str) -> None:
        status = self._status
        if status is None or not status.get("path"):
            self._toast("fprintd did not answer - nothing was deleted")
            return
        self._set_enrollable(False)

        def done(_res, err):
            self._set_enrollable(bool(status.get("device_present")))
            self._toast(err if err else f"{_finger_label(finger)} was deleted")
            self.refresh()
        ss.fprintd_delete_finger(status["path"], finger, done)

    def _toast(self, text: str) -> None:
        self._toasts.add_toast(Adw.Toast(title=GLib.markup_escape_text(text), timeout=6))
