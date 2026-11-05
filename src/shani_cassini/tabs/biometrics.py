# Enrichment 2026-10-25: shani-health / matrix binary reference; read-only / privileged button per AGENTS.md.
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
import shutil

from gi.repository import Adw, GLib, Gtk  # type: ignore

from shani_cassini.shell_bridge import in_shani_shell
from shani_cassini import system_status as ss
from shani_cassini.plain import Details, Summary, explain_error, settings_row
from shani_cassini.widgets import reserve_leading_column

logger = logging.getLogger(__name__)

# What a fingerprint or face can unlock, per edition, in plain words. The
# technical answer (which PAM file) is EDITION_LOGIN, shown under For experts.
EDITION_PLAIN = {
    "niri": ("At the sign-in screen and the lock screen. At sign-in your face is "
             "tried first; to use a finger, press Enter without typing a password.",
             "ok"),
    "gnome": ("At the sign-in screen and the lock screen.", "ok"),
    "plasma": ("At the lock screen only, once it is switched on in the lock screen's "
               "settings. The sign-in screen always asks for your password.", "warning"),
    "cosmic": ("Not on this edition - its sign-in screen does not support it yet.",
               "warning"),
}

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


# The modules whose login methods have a page of their own. Kept here rather
# than in system_status so the list of what this page skips is visible next to
# the page that skips it.
PAGE_BACKED_MODULES = frozenset({"pam_pkcs11.so", "pam_u2f.so", "pam_yubico.so",
                                 "pam_krb5.so"})

# The one module whose rows belong on this page rather than beside it: this IS
# the fingerprint page, so the PAM service that makes a finger usable at login
# is this page's own business and not one of the "other ways to sign in".
FINGERPRINT_MODULE = "pam_fprintd.so"
# Face sign-in (linux-hello) is this page's business too: its PAM rows go to
# the same group as the fingerprint's.
OWN_MODULES = frozenset({FINGERPRINT_MODULE, ss.FACE_MODULE})


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


def _clear_group(group: Adw.PreferencesGroup) -> None:
    """Take every row back out of a group, leaving its header alone.

    An AdwPreferencesGroup does not hold its rows directly. Measured on
    libadwaita here, the tree is group -> Box -> Box -> ListBox -> ActionRow,
    so get_first_child() hands back the outer Box, and remove() on that is
    refused ("tried to remove non-child ... of type 'GtkBox'") and does
    nothing. The old loop walked siblings of that Box - of which there are
    none - so it ran once, cleared nothing, and a refresh accumulated rows
    instead. The rows are the ActionRow leaves, and the group's own remove()
    does reach them, so those are what get taken back out.
    """
    rows: list[Gtk.Widget] = []

    def collect(widget: Gtk.Widget) -> None:
        child = widget.get_first_child()
        while child is not None:
            if isinstance(child, Adw.PreferencesRow):
                rows.append(child)
            else:
                collect(child)
            child = child.get_next_sibling()

    collect(group)
    for row in rows:
        group.remove(row)


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
        self._offered: list[str] = list(ss.FINGER_NAMES)

        self._build()
        self.refresh()
        self._load_edition()

    # ------------------------------------------------------------- building
    def _build(self) -> None:
        # 1. What the page is for, and where things stand, in plain words.
        self._summary = Summary(
            "Fingerprint and Face Sign-in",
            "Sign in by touching the fingerprint reader or looking at the camera, "
            "instead of typing your password.")
        self._btn_retry = self._summary.add_action("Check Again", self.refresh)
        self._btn_retry.set_visible(False)
        self._row_face = _row("Face sign-in")
        self._set(self._row_face, "Face sign-in", "Checking…", None)
        self._summary.add(self._row_face)
        self._page.append(self._summary)

        # Inside shani-shell, fingers and the face are set up in the desktop's
        # own Settings (Account > Sign in faster) - Cassini repeats no desktop
        # setting. Everywhere else this page enrols fingers itself.
        self._in_shell = in_shani_shell()
        self._settings = settings_row(
            "account", "Set up your fingerprint and face",
            "Settings › Account › Sign in faster")
        self._page.append(self._settings)

        self._fingers_group = self._fingers_group_new(None)
        self._page.append(self._fingers_group)

        add = Adw.PreferencesGroup(
            title="Add a Fingerprint",
            description="Choose a finger, press Add, then touch the reader each time "
                        "it asks. Your password is asked for once.")
        # EnrollStart takes one of fprintd's ten finger names and rejects
        # anything else ("any" included), so this offers exactly those. Which
        # of the ten narrows to the ones fprintd has not stored yet, refilled
        # from _on_status.
        self._picker = Adw.ComboRow(
            title="Finger", model=Gtk.StringList.new([_finger_label(f) for f in self._offered]))
        if "right-index-finger" in self._offered:
            self._picker.set_selected(self._offered.index("right-index-finger"))
        add.add(self._picker)
        self._row_enroll = _row("Add this finger", "Needs a reader")
        self._btn_enroll = Gtk.Button(label="Add…", valign=Gtk.Align.CENTER, sensitive=False)
        self._btn_enroll.add_css_class("suggested-action")
        self._btn_enroll.connect("clicked", lambda *_: self._start_enroll())
        self._btn_cancel = Gtk.Button(label="Cancel", valign=Gtk.Align.CENTER, visible=False)
        self._btn_cancel.add_css_class("destructive-action")
        self._btn_cancel.connect("clicked", lambda *_: self.cancel_enroll())
        self._row_enroll.add_suffix(self._btn_cancel)
        self._row_enroll.add_suffix(self._btn_enroll)
        add.add(self._row_enroll)
        self._progress = Gtk.ProgressBar(valign=Gtk.Align.CENTER, visible=False,
                                         show_text=True)
        add.add(self._progress)
        self._add_group = add
        self._page.append(add)
        if self._in_shell:
            add.set_visible(False)

        # 2. Where it works, in plain words. The PAM wiring behind each answer
        #    is under For experts.
        where = Adw.PreferencesGroup(title="Where You Can Use It")
        self._row_where = _row("This computer")
        self._set(self._row_where, "This computer", "Checking…", None)
        where.add(self._row_where)
        where.add(_row("Admin passwords",
                       "Commands that need administrator rights (sudo) always ask "
                       "for your password. That is on purpose.",
                       "dialog-information-symbolic"))
        self._page.append(where)

        # 3. Everything technical, folded away.
        details = Details()
        self._details = details
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
        details.append(reader)

        face = Adw.PreferencesGroup(
            title="Face (linux-hello)",
            description=f"linux-hello recognises a face with an infrared camera. Its daemon "
                        f"is {ss.FACE_UNIT} and its PAM module {ss.FACE_MODULE}.")
        self._row_face_service = _row(ss.FACE_UNIT, "Asking it…")
        face.add(self._row_face_service)
        self._row_face_pam = _row(ss.FACE_MODULE, "Reading…")
        face.add(self._row_face_pam)
        details.append(face)

        wiring = Adw.PreferencesGroup(
            title="Where a Fingerprint Works",
            description="The PAM service that makes an enrolled finger or face usable ships "
                        "with the display manager, not with fprintd, so this differs per "
                        "edition.")
        self._row_edition = _row("This edition")
        # A status icon from the start - the rows beside it carry icons. (It
        # used to reserve an empty column AND get an icon from _set, which drew
        # this one title a column further in than its neighbours.)
        self._set(self._row_edition, "This edition", "Reading it…", None)
        wiring.add(self._row_edition)
        head, detail = ss.SUDO_NEVER
        wiring.add(_row(head, detail, "dialog-information-symbolic"))
        # An inner group so the PAM rows can be refilled on every refresh
        # without taking "This edition" and the sudo note out with them:
        # _clear_group takes every row, which is right for a group that holds
        # nothing else and wrong for one that does.
        self._where_pam = Adw.PreferencesGroup()
        wiring.add(self._where_pam)
        details.append(wiring)

        cli = Adw.PreferencesGroup(
            title="From a Terminal",
            description="The same tools, if you would rather do it by hand. All of these "
                        "ship in the image — nothing here needs installing:")
        for cmd, what in (("fprintd-enroll", "enroll a finger"),
                          ("fprintd-list", "list the enrolled ones"),
                          ("fprintd-verify", "test a scan"),
                          ("fprintd-delete", "delete one"),
                          ("ykman", "FIDO2/U2F security key"),
                          ("pcsc_scan", "list a smartcard or NFC reader"),
                          ("oathtool", "TOTP/HOTP two-factor codes")):
            present = shutil.which(cmd) is not None
            r = _row(cmd, what if present else f"{what} — not installed")
            if not present:
                r.set_subtitle_selectable(True)
                img = Gtk.Image.new_from_icon_name("dialog-warning-symbolic")
                img.add_css_class("warning")
                r.add_prefix(img)
            else:
                # **Reserve the leading column even when there is no verdict.**
                # Found by rendering (2026-10-17): the icon was added only for a
                # missing tool, so on a machine with all seven installed every row
                # was flush and consistent - and on one missing three, those three
                # sat in a column of their own with the other four ragged beside
                # them. The list must not change shape with the machine.
                reserve_leading_column(r)
            cli.add(r)
        details.append(cli)

        # Other hardware-auth paths, reported from the image's own PAM config
        # rather than assumed. A login method whose module is missing is called
        # out explicitly instead of being quietly absent from this page.
        self._auth_group = Adw.PreferencesGroup(title="Other ways to sign in", visible=False)
        details.append(self._auth_group)
        self._page.append(details)

    def _on_face(self, state: dict, err: str) -> None:
        """Face sign-in in plain words, and linux-hello's own answer under
        For experts."""
        stacks = state.get("stacks") or []
        service = state.get("service") or ""
        if not state.get("installed"):
            self._set(self._row_face, "Face sign-in",
                      "Not available on this computer - it needs linux-hello and an "
                      "infrared camera", None)
            self._row_face_service.set_subtitle("Not installed")
            self._row_face_pam.set_subtitle("Not installed")
            return
        self._row_face_service.set_subtitle(_esc(service or err or "systemctl did not answer"))
        self._row_face_pam.set_subtitle(
            _esc("Loaded by " + ", ".join(stacks)) if stacks
            else "Installed, but no sign-in service loads it")
        if service == "failed":
            self._set(self._row_face, "Face sign-in",
                      "The face recognition service stopped working. Restart the "
                      "computer; if it keeps happening, see For experts.", "warning")
        elif not stacks:
            self._set(self._row_face, "Face sign-in",
                      "Installed, but not switched on for signing in on this edition", None)
        else:
            how = ("Set up your face in Settings › Account › Sign in faster"
                   if self._in_shell else "Look at the camera when you sign in")
            self._set(self._row_face, "Face sign-in", f"Available. {how}.", "ok")

    def _on_hardware_auth(self, rows: list) -> None:
        """The sign-in methods that have no page of their own.

        Smartcard, security keys and Kerberos each got their own page, so they
        are dropped here rather than shown twice: two lists of the same claim
        drift apart, and the one on this page would be the stale one. What is
        left is exactly the set with nowhere else to go - face, iris, voice and
        the rest - which is why this group still matters and is not simply
        deleted. A silent omission would read as "nobody has heard of face
        login", which is its own kind of wrong.

        pam_fprintd is the exception and is routed to "Where a Fingerprint
        Works" instead. It has no page of its own because this is its page, and
        filing its login wiring under "other" put the one row that is about
        this page under a heading saying it was about something else.
        """
        mine = [r for r in rows if r.get("module") in OWN_MODULES]
        theirs = [r for r in rows
                  if r.get("module") not in OWN_MODULES
                  and r.get("module") not in PAGE_BACKED_MODULES]
        _clear_group(self._where_pam)
        for row in mine:
            self._where_pam.add(self._auth_row(row))
        self._where_pam.set_visible(bool(mine))
        g = self._auth_group
        _clear_group(g)
        if not theirs:
            g.set_visible(False)
            return
        g.set_description("Reported from this system's own PAM configuration.")
        for row in theirs:
            g.add(self._auth_row(row))
        g.set_visible(True)

    @staticmethod
    def _auth_row(row: dict) -> Adw.ActionRow:
        r = _row(row.get("title", ""), row.get("detail", ""))
        r.set_subtitle_selectable(True)
        icon, css = {
            "ok": ("object-select-symbolic", "success"),
            "inactive": ("dialog-information-symbolic", "dim-label"),
        }.get(row.get("state"), ("dialog-warning-symbolic", "warning"))
        img = Gtk.Image.new_from_icon_name(icon)
        img.add_css_class(css)
        r.add_prefix(img)
        return r

    def _fingers_group_new(self, fingers: list | None) -> Adw.PreferencesGroup:
        g = Adw.PreferencesGroup(title="Enrolled Fingers", visible=bool(fingers),
                                 description=FINGERS_HELP)
        for f in fingers or []:
            r = _row(_esc(_finger_label(f)), "Enrolled on this device")
            if not getattr(self, "_in_shell", False):     # in the shell: Settings removes them
                b = Gtk.Button(label="Delete…", valign=Gtk.Align.CENTER)
                b.add_css_class("destructive-action")
                b.connect("clicked", lambda _b, finger=f: self._delete(finger))
                r.add_suffix(b)
            g.add(r)
        return g

    # ------------------------------------------------------------------ data
    def refresh(self) -> None:
        self._on_hardware_auth(ss.hardware_auth_status())
        ss.face_status(self._on_face)
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
            if not ss.fprintd_installed():
                self._summary.set_state(
                    "error", "Fingerprint support is not installed",
                    "The fprintd service is missing. Updating the system brings it back.")
            else:
                what, todo = explain_error(err, "the fingerprint service")
                self._summary.set_state("warning", what, todo)
            self._btn_retry.set_visible(True)
            self._set(self._row_device, "Reader", "Not known - fprintd did not answer", None)
            self._set(self._row_fingers, "Enrolled fingers", "Not known - fprintd did not answer",
                      None)
            self._set_enrollable(False)
            self._replace_fingers(None)
            return

        self._status = status
        self._btn_retry.set_visible(False)
        self._set(self._row_daemon, "fprintd", "Running", "ok")

        if not status["device_present"]:
            self._summary.set_state(
                "info", "No fingerprint reader found",
                "This computer does not seem to have one. If you plug one in, "
                "press Check Again.")
            self._btn_retry.set_visible(True)
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
        count = status.get("device_count", 1)
        many = f" · {count} readers attached" if isinstance(count, int) and count > 1 else ""
        self._set(self._row_device, "Reader", f"{name} · {scan}{how}{many}", "ok")

        fingers = status["fingers"]
        enrolled = len(fingers)
        self._set(self._row_fingers, "Enrolled fingers",
                  f"{enrolled} enrolled" if enrolled else "None - add one below to use a fingerprint",
                  "ok" if enrolled else None)
        if enrolled:
            self._summary.set_state(
                "ok", "Your fingerprint reader is ready",
                f"{enrolled} finger{'s' * (enrolled != 1)} saved. Touch the reader "
                f"when you sign in.")
        else:
            self._summary.set_state(
                "info", "Your fingerprint reader has no fingerprints yet",
                "Set one up in Settings to sign in with your finger." if self._in_shell
                else "Add one below to sign in with your finger.")
        self._refill_picker(fingers)
        self._set_enrollable(bool(self._offered))
        if not self._offered:
            self._row_enroll.set_subtitle(
                "Every finger fprintd accepts is already enrolled - delete one above first")
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

    def _refill_picker(self, fingers: list[str] | None) -> None:
        stored = {str(f) for f in (fingers or [])}
        self._offered = [f for f in ss.FINGER_NAMES if f not in stored]
        self._picker.set_model(
            Gtk.StringList.new([_finger_label(f) for f in self._offered]))
        if "right-index-finger" in self._offered:
            self._picker.set_selected(self._offered.index("right-index-finger"))
        else:
            self._picker.set_selected(0 if self._offered else Gtk.INVALID_LIST_POSITION)

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
                self._set(self._row_where, "This computer",
                          "Not known - Cassini could not tell which edition of Shanios "
                          "this is", "unknown")
                self._set(self._row_edition, "This edition",
                          "Not known - Shanios's own status could not be read, so what a "
                          "fingerprint can unlock here is not known", "unknown")
                return
            profile = str(st.get("profile") or "")
            head, detail = ss.edition_login(profile)
            title = f"This edition: {_esc(profile)}" if profile else "This edition"
            self._set(self._row_edition, title, f"{head}. {detail}",
                      "ok" if profile.lower() in ss.EDITION_LOGIN else "unknown")
            plain, state = EDITION_PLAIN.get(profile.lower(), (
                "Not known for this edition", "unknown"))
            self._set(self._row_where, "This computer", plain, state)
        ss.deploy_status(got)

    # ------------------------------------------------------------ enrolling
    def _chosen_finger(self) -> str:
        index = self._picker.get_selected()
        if not 0 <= index < len(self._offered):
            return ""
        return self._offered[index]

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
        self._paint_progress()
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
        self._paint_progress()
        if e["busy"]:
            return
        e["busy"] = True
        ss.fprintd_properties(e["path"], self._on_live)

    def _paint_progress(self) -> None:
        """The bar, only while there is a total to be a fraction of.

        A device that reports no num-enroll-stages gets no bar: a progress
        indicator with an invented total is worse than the count in the
        subtitle.
        """
        e = self._enroll
        if e is None:
            self._progress.set_visible(False)
            return
        stages = self._status.get("num_enroll_stages") if self._status else None
        if not isinstance(stages, int) or stages <= 0:
            self._progress.set_visible(False)
            return
        self._progress.set_text(f"{e['stages']}/{stages}")
        self._progress.set_fraction(min(1.0, e["stages"] / stages))
        self._progress.set_visible(True)

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
        self._progress.set_visible(False)
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
