"""The real interfaces Cassini reads and drives - nothing here is invented.

* ``shani-deploy --status [--check] --json`` - slots, version, channel,
  remote stable/latest, update_available. Read-only, no root.
* ``shani-health --verify --json`` - {"timestamp", "checks": [{section,
  key, status, message}]}. Needs root: run through pkexec, on request.
* ``shani-deploy`` / ``--rollback`` / ``--set-channel X`` - through pkexec,
  output streamed line by line.
* ``net.reactivated.fprint`` on the system bus - the fingerprint reader, the
  fingers enrolled on it, and enrolling/deleting one. No pkexec: fprintd
  asks polkit over D-Bus itself (shani-settings 99-shani.rules grants
  verify/identify as YES and enroll/delete as AUTH_SELF), so the desktop
  password dialog appears on its own.

Everything runs through Gio.Subprocess or Gio.DBus, so the window never
blocks.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
from typing import Callable, Optional

from gi.repository import Gio, GLib  # type: ignore

logger = logging.getLogger(__name__)

DEPLOY = "shani-deploy"
HEALTH = "shani-health"


def have(cmd: str) -> bool:
    return shutil.which(cmd) is not None


def run_json(argv: list[str], done: Callable[[Optional[dict], str], None]) -> None:
    """Run argv; call done(parsed_json_or_None, error_text) on the main loop."""
    if not have(argv[0]):
        GLib.idle_add(done, None, f"{argv[0]} is not installed")
        return
    try:
        proc = Gio.Subprocess.new(argv, Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_PIPE)
    except GLib.Error as e:
        GLib.idle_add(done, None, e.message)
        return

    def finish(p, res):
        try:
            _ok, out, err = p.communicate_utf8_finish(res)
        except GLib.Error as e:
            done(None, e.message)
            return
        status = p.get_exit_status() if p.get_if_exited() else -1
        # pkexec: 126 = dialog dismissed, 127 = not authorized
        if argv[0] == "pkexec" and status in (126, 127):
            done(None, "Authorization was cancelled")
            return
        # JSON on stdout wins over the exit status: shani-health --verify
        # exits 1 when a check fails and still prints its results
        try:
            done(json.loads(out), "")
            return
        except ValueError:
            pass
        text = _strip_ansi(err or out or f"exit status {status}").strip()
        logger.warning("%s: rc=%s, no JSON: %.200s", argv, status, text)
        if "Invalid option" in text or "invalid option" in text:
            # e.g. shani-deploy older than --status: the image's tools are
            # behind this app, not a broken system
            done(None, "This system's tools are older than Shani Cassini - update Shanios to see this")
            return
        lines = text.splitlines()
        last = re.sub(r"^\S+ \S+ \[\w+\]\s*", "", lines[-1]) if lines else f"exit status {status}"
        done(None, last)

    proc.communicate_utf8_async(None, None, finish)


def deploy_status(done, check: bool = False) -> None:
    argv = [DEPLOY, "--status", "--json"]
    if check:
        argv.insert(2, "--check")
    run_json(argv, done)


def health_verify(done) -> None:
    """{"ok", "errors", "checks": [{name, status: pass|warn|fail, message}]}"""
    run_json(["pkexec", HEALTH, "--verify", "--json"], done)


def health_report(mode: str, done) -> None:
    """--security / --boot / --hardware ...: {"timestamp", "checks":
    [{section, key, status: ok|warning|critical|info|..., message}]}"""
    run_json(["pkexec", HEALTH, f"--{mode}", "--json"], done)


def run_streaming(argv: list[str], on_line: Callable[[str], None],
                  on_exit: Callable[[int], None]) -> Optional[Gio.Subprocess]:
    """Run argv (merged stdout+stderr), feeding each line to on_line; then
    on_exit(exit_status). Returns the process (to cancel), or None."""
    try:
        proc = Gio.Subprocess.new(argv, Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_MERGE)
    except GLib.Error as e:
        on_line(e.message)
        GLib.idle_add(on_exit, 127)
        return None
    stream = Gio.DataInputStream.new(proc.get_stdout_pipe())

    def read_next():
        stream.read_line_async(GLib.PRIORITY_DEFAULT, None, got_line)

    def got_line(s, res):
        try:
            line, _len = s.read_line_finish_utf8(res)
        except GLib.Error:
            line = None
        if line is None:
            proc.wait_async(None, lambda p, r: (p.wait_finish(r), on_exit(p.get_exit_status())))
            return
        on_line(_strip_ansi(line))
        read_next()

    read_next()
    return proc


def _strip_ansi(s: str) -> str:
    import re
    return re.sub(r"\x1b\[[0-9;?]*[A-Za-z]", "", s)


def pretty_version(v: str) -> str:
    """20260925 -> 2026.09.25 (the release name on shani.dev)."""
    return f"{v[:4]}.{v[4:6]}.{v[6:8]}" if len(v) == 8 and v.isdigit() else (v or "Unknown")


# --- systemd's own JSON interfaces ---------------------------------------

def run_json_lines(argv: list[str], done: Callable[[Optional[list], str], None]) -> None:
    """For journalctl -o json: one JSON object per line."""
    if not have(argv[0]):
        GLib.idle_add(done, None, f"{argv[0]} is not installed")
        return
    try:
        proc = Gio.Subprocess.new(argv, Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_SILENCE)
    except GLib.Error as e:
        GLib.idle_add(done, None, e.message)
        return

    def finish(p, res):
        try:
            _ok, out, _err = p.communicate_utf8_finish(res)
        except GLib.Error as e:
            done(None, e.message)
            return
        items = []
        for line in (out or "").splitlines():
            try:
                items.append(json.loads(line))
            except ValueError:
                pass
        done(items, "")

    proc.communicate_utf8_async(None, None, finish)


def hostnamectl(done) -> None:
    run_json(["hostnamectl", "--json=short"], done)


def boot_entries(done) -> None:
    run_json(["bootctl", "list", "--json=short", "--no-pager"], done)


def boot_errors(done, limit: int = 50) -> None:
    """Priority err..emerg messages from this boot."""
    run_json_lines(["journalctl", "-b", "-p", "3", "-o", "json", "-n", str(limit), "--no-pager"], done)


def crashes(done) -> None:
    run_json(["coredumpctl", "list", "--json=short", "--no-pager", "--since=-7d"], done)


def inhibited(argv: list[str], why: str) -> list[str]:
    """Keep the machine awake while argv runs (updates, rollbacks). Not
    "shutdown": a block lock would also refuse the reboot the tool itself
    may request (shani-reset reboots when done)."""
    if not have("systemd-inhibit"):
        return argv
    return ["systemd-inhibit", "--what=sleep:idle:handle-lid-switch",
            "--who=Shani Cassini", f"--why={why}", "--mode=block"] + argv


def has_tpm2() -> Optional[bool]:
    """systemd-analyze has-tpm2: exit 0 = usable TPM2 (no root needed)."""
    if not have("systemd-analyze"):
        return None
    import subprocess
    try:
        return subprocess.run(["systemd-analyze", "has-tpm2", "-q"], capture_output=True, timeout=10).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return None


def tpm2_status(done) -> None:
    """gen-efi tpm2-status --json (root: it reads the LUKS header)."""
    run_json(["pkexec", "gen-efi", "tpm2-status", "--json"], done)


# --- fprintd: the fingerprint reader, over its own D-Bus API ---------------
#
# fprintd and libfprint ship in shani-peripherals (not in shani-cassini's
# dependencies) and shani-peripherals.install runs `systemctl enable fprintd`,
# so on a Shanios image the daemon is there and enabled - but a machine can
# have it absent or stopped, and both are reported as such, never as "no
# fingerprints" or "no reader".
#
# Everything below is transcribed from the installed daemon's own interface
# description, /usr/share/dbus-1/interfaces/net.reactivated.Fprint.{Manager,
# Device}.xml, and the call order from its reference client utils/enroll.c.
# In particular there is no Enroll() and no Delete(): the Device interface has
# exactly ten methods, and enrollment progress arrives as EnrollStatus
# signals, not as a per-scan reply.
FPRINTD_CLI = "fprintd-enroll"          # ships in /usr/sbin
FPRINTD_BUS = "net.reactivated.Fprint"
FPRINTD_PATH = "/net/reactivated/Fprint"
FPRINTD_MANAGER = "net.reactivated.Fprint.Manager"
FPRINTD_DEVICE = "net.reactivated.Fprint.Device"
FPRINTD_PROPERTIES = "org.freedesktop.DBus.Properties"
FPRINTD_ERROR = "net.reactivated.Fprint.Error."
SBIN_DIRS = ("/usr/sbin", "/usr/local/sbin")

# The ten names EnrollStart accepts (the XML's "Fingerprint names" list).
# "any" is valid for VerifyStart but its own doc rejects it for EnrollStart.
FINGER_NAMES = (
    "left-thumb", "left-index-finger", "left-middle-finger", "left-ring-finger",
    "left-little-finger", "right-thumb", "right-index-finger", "right-middle-finger",
    "right-ring-finger", "right-little-finger",
)

# The empty username means "the user the client is running as", which is the
# one form that provably never triggers fprintd's setusername polkit check
# (utils/enroll.c passes it too, and the XML recommends it).
FPRINTD_SELF_USER = ""

# EnrollStatus(reason, done) result strings, from the XML. A reason Cassini
# does not know is shown as fprintd sent it rather than guessed at.
ENROLL_STATUS_TEXT = {
    "enroll-completed": "Fingerprint stored",
    "enroll-stage-passed": "Scan stored - scan the same finger again",
    "enroll-retry-scan": "Scan not accepted - try again",
    "enroll-swipe-too-short": "The scan was too short - swipe again",
    "enroll-finger-not-centered": "The finger was not centered - try again",
    "enroll-remove-and-retry": "Take the finger off the reader, then touch it again",
    "enroll-data-full": "The reader has no space left for another finger",
    "enroll-duplicate": "This finger is already enrolled",
    "enroll-disconnected": "The reader was disconnected",
    "enroll-failed": "The scan failed - try again",
    "enroll-unknown-error": "fprintd reported an error it does not name",
}

# what an enrolled finger can actually unlock, per edition. Verified against
# the packages, not guessed: the PAM service that makes a finger usable ships
# with the DISPLAY MANAGER, not with fprintd (gdm ships
# /etc/pam.d/gdm-fingerprint, kscreenlocker /usr/lib/pam.d/kde-fingerprint,
# cosmic-greeter ships none), and /etc/pam.d/sudo includes system-auth, which
# has no pam_fprintd line - so sudo never takes a fingerprint on any edition.
EDITION_LOGIN = {
    "gnome": ("Works at the login screen",
              "gdm ships /etc/pam.d/gdm-fingerprint, so an enrolled finger unlocks this session "
              "at the login screen. Settings - Users - Fingerprint Login lists the same fingers."),
    "plasma": ("Lock screen only, and it must be switched on",
               "The KDE login screen (SDDM) has no fingerprint support at all. kscreenlocker "
               "ships /usr/lib/pam.d/kde-fingerprint for the lock screen, which must be enabled "
               "with: kwriteconfig6 --file kscreenlockerrc --group Authenticators "
               "--key Fingerprint true"),
    "cosmic": ("Not available on this edition",
               "cosmic-greeter ships no PAM fingerprint service, so an enrolled finger cannot "
               "unlock this session. The finger stays enrolled for the other things fprintd does."),
}
SUDO_NEVER = ("sudo never takes a fingerprint",
              "/etc/pam.d/sudo includes system-auth, which has no pam_fprintd line: a sudo "
              "prompt always asks for the password.")


def have_sbin(cmd: str) -> bool:
    """have(), and also look in the sbin directories.

    Cassini does not always run with /usr/sbin on PATH - a desktop session or
    a systemd user unit gets a PATH without it - while every fprintd tool
    lives there. A plain which() would then call an installed fprintd
    "missing", so callers that check for one of those tools use this.
    """
    if have(cmd):
        return True
    base = os.path.basename(cmd)
    return any(os.access(os.path.join(d, base), os.X_OK) for d in SBIN_DIRS)


def fprintd_installed() -> bool:
    """Is fprintd on this machine at all (the shani-peripherals package)?

    Best effort on purpose: fprintd-enroll is in /usr/sbin, so its absence
    from PATH says nothing, and it is not what the page actually talks to.
    A wrong answer here is not fatal - a failed D-Bus connection is reported
    as "not installed" too, so the two checks always agree.
    """
    return have_sbin(FPRINTD_CLI)


def edition_login(profile: str) -> tuple[str, str]:
    """(headline, detail) for what a fingerprint unlocks on this edition.

    An edition Cassini does not know gets an honest "cannot say" - never the
    most optimistic entry."""
    entry = EDITION_LOGIN.get((profile or "").strip().lower())
    if entry is None:
        return ("Unknown edition",
                "This system's edition could not be read, so what a fingerprint can unlock "
                "here is not known. fprintd itself is reported above.")
    return entry


def enroll_status_text(reason: str) -> str:
    """What an EnrollStatus reason means, or fprintd's own words if unknown."""
    return ENROLL_STATUS_TEXT.get(str(reason), str(reason))


def _system_bus(ready: Callable[[Optional[Gio.DBusConnection], str], None]) -> None:
    """ready(connection_or_None, error_text) on the main loop."""
    def got(_bus, res, _data=None):
        # GObject callback arity is fixed by the C signature and invisible at the
        # call site: bus_get passes (connection, result, user_data). Declaring two
        # parameters raises TypeError, and the test fakes cannot catch it.
        try:
            ready(Gio.bus_get_finish(res), "")
        except GLib.Error as e:
            ready(None, e.message)
    Gio.bus_get(Gio.BusType.SYSTEM, None, got, None)


def _s(value: str) -> GLib.Variant:
    """A string argument - the shape most of the Device methods take."""
    return GLib.Variant("s", str(value))


def _args(params: list) -> GLib.Variant:
    """A D-Bus method's arguments as the one tuple a call body is.

    The body is a tuple of the declared parameter types: "(s)" for a single
    string, "()" for a method that takes none. Wrapping the arguments in a
    variant instead would be rejected by the daemon as InvalidArgs.

    The signature comes from the variants, but the values handed to the
    Variant constructor are their unpacked selves: the constructor reads
    through them, so passing the variants themselves raises
    "Must be string, not Variant"."""
    if not params:
        return GLib.Variant("()", ())
    return GLib.Variant("(" + "".join(p.get_type_string() for p in params) + ")",
                        tuple(p.unpack() for p in params))


class _FailedCall:
    """Stands in for a reply that never arrived.

    D-Bus reports a refused or errored call by raising out of call_finish, not
    by returning a message. _unpack already converts a GLib.Error from
    get_reply() into the ValueError its callers handle, so re-raising the same
    error from a stand-in keeps one error path instead of two.
    """

    def __init__(self, err: GLib.Error) -> None:
        self._err = err

    def get_reply(self):
        raise self._err


def _reply_or_error(conn, res):
    try:
        return conn.call_finish(res)
    except GLib.Error as e:
        return _FailedCall(e)


def _dbus_call(conn: Gio.DBusConnection, path: str, iface: str, method: str,
               params: list, got: Callable[[Gio.AsyncResult, Gio.DBusConnection], None],
               reply_type: Optional[str] = "(v)") -> Gio.Cancellable:
    """One method call on a bus we already hold; got() runs on the main loop.

    reply_type=None for the seven methods that return nothing (Claim,
    Release, EnrollStart, EnrollStop, DeleteEnrolledFinger(s), VerifyStart,
    VerifyStop) - asking for a "(v)" reply there is an error, not an empty
    one. ALLOW_INTERACTIVE_AUTHORIZATION is what lets fprintd raise polkit's
    own dialog instead of failing the call outright.
    """
    return conn.call(FPRINTD_BUS, path, iface, method, _args(params),
                     GLib.VariantType(reply_type) if reply_type else None,
                     Gio.DBusCallFlags.ALLOW_INTERACTIVE_AUTHORIZATION, 25000, None,
                     lambda _conn, res, _d=None: got(_reply_or_error(_conn, res), _conn))


def _unpack(message: Gio.DBusMessage) -> list:
    try:
        reply = message.get_reply()   # a D-Bus error is raised here, not returned
        if reply is None:             # a method with no return value
            return []
        return list(reply.unpack())
    except (GLib.Error, TypeError, ValueError) as e:
        raise ValueError(str(e)) from e


def _plain(value):
    """The Python value of a possibly-wrapped variant.

    GLib.Variant.unpack() deep-unpacks, so an "a{sv}" reply normally arrives
    as a dict of plain values - but a child can still come back as a variant
    on other PyGObject versions, and str() of an object-path variant is
    "objectpath '/net/...'", not the path. Unwrap first, then stringify."""
    unpack = getattr(value, "unpack", None)
    return unpack() if callable(unpack) else value


def _properties(unpacked: list) -> dict:
    """A GetAll reply: the a{sv} is the single argument of the (v) reply."""
    values = _plain(unpacked[0]) if unpacked else {}
    if not isinstance(values, dict):
        logger.warning("fprintd: GetAll answered %r, not a{sv}", type(values).__name__)
        return {}
    return {str(k): _plain(v) for k, v in values.items()}


def fprintd_error(err: str) -> str:
    """The net.reactivated.Fprint.Error.* name in a D-Bus error, or "".

    fprintd reports "no fingers enrolled for this user" as
    NoEnrolledPrints, which is an answer rather than a failure."""
    found = re.search(r"net\.reactivated\.Fprint\.Error\.\w+", err or "")
    return found.group(0) if found else ""


def fprintd_status(done: Callable[[Optional[dict], str], None], timeout_s: float = 6.0) -> None:
    """Ask fprintd for the reader and the fingers enrolled on the caller.

    done(status_or_None, error_text) on the main loop. status is
    {"daemon": bool, "device_present": bool, "path": str, "name": str,
    "scan_type": str, "num_enroll_stages": int|None, "fingers": [str]}. A
    reader is present exactly when GetDevices returned at least one path -
    the Device interface has no DevicePresent property, and its five
    properties (name, num-enroll-stages, scan-type, finger-present,
    finger-needed) are all there is to read.

    A daemon that cannot be reached is (None, error): that is the difference
    between "no fingerprints are enrolled" and "nobody answered", and the
    page must not confuse them. timeout_s bounds the whole chain, so a reader
    that stops answering mid-call cannot leave the page spinning.
    """
    state = {"settled": False}
    guard = [0]

    def finish(status, error=""):
        if state["settled"]:
            return
        state["settled"] = True
        if guard[0]:
            GLib.source_remove(guard[0])
            guard[0] = 0
        GLib.idle_add(done, status, error)

    def expired():
        guard[0] = 0
        finish(None, "fprintd did not answer in time")
        return False
    guard[0] = GLib.timeout_add_seconds(max(1, int(timeout_s)), expired)

    def status_step(conn, err):
        if conn is None:
            finish(None, err or "the system bus is not available")
            return

        def devices(res, _c):
            try:
                paths = [str(_plain(p)) for p in _unpack(res)]
            except ValueError as e:
                finish(None, f"fprintd did not answer: {e}")
                return
            if not paths:
                finish({"daemon": True, "device_present": False, "path": "", "name": "",
                        "scan_type": "", "num_enroll_stages": None, "fingers": []})
                return
            _fprintd_device(conn, paths[0], finish)
        _dbus_call(conn, FPRINTD_PATH, FPRINTD_MANAGER, "GetDevices", [], devices)

    _system_bus(status_step)


def _fprintd_device(conn, path: str, finish) -> None:
    """One device's five properties and the fingers enrolled on the caller."""
    def props(res, _c):
        try:
            raw = _unpack(res)
        except ValueError as e:
            finish(None, f"fprintd did not answer: {e}")
            return
        values = _properties(raw)

        def fingers(res2, _c2):
            try:
                raw2 = _unpack(res2)
            except ValueError as e:
                # NoEnrolledPrints is fprintd's way of saying "none yet"
                if fprintd_error(str(e)).endswith("NoEnrolledPrints"):
                    finish(_status(path, values, []))
                    return
                finish(None, f"fprintd did not answer: {e}")
                return
            finish(_status(path, values, [str(x) for x in (raw2[0] if raw2 else [])]))
        _dbus_call(conn, path, FPRINTD_DEVICE, "ListEnrolledFingers",
                   [_s(FPRINTD_SELF_USER)], fingers)
    _dbus_call(conn, path, FPRINTD_PROPERTIES, "GetAll", [_s(FPRINTD_DEVICE)], props)


def _status(path: str, values: dict, fingers: list) -> dict:
    stages = values.get("num-enroll-stages")
    return {"daemon": True,
            "device_present": True,
            "path": path,
            "name": str(values.get("name") or ""),
            "scan_type": str(values.get("scan-type") or ""),
            "num_enroll_stages": int(stages) if isinstance(stages, int) else None,
            "fingers": fingers}


def fprintd_properties(path: str, done: Callable[[Optional[dict], str], None]) -> None:
    """One device's properties (name, num-enroll-stages, scan-type,
    finger-present, finger-needed). finger-present and finger-needed are the
    only honest way to show whether a finger is actually on the reader."""
    def props(res, _c):
        try:
            values = _properties(_unpack(res))
        except ValueError as e:
            done(None, f"fprintd did not answer: {e}")
            return
        done(values, "")
    _system_bus(lambda conn, err: done(None, err) if conn is None
                else _dbus_call(conn, path, FPRINTD_PROPERTIES, "GetAll", [_s(FPRINTD_DEVICE)], props))


def fprintd_action(path: str, method: str, params: list,
                   done: Callable[[Optional[list], str], None], note: str = "") -> None:
    """Call one of the Device methods that return nothing.

    method must be a real one: Claim, Release, EnrollStart, EnrollStop,
    DeleteEnrolledFinger, DeleteEnrolledFingers, DeleteEnrolledFingers2,
    VerifyStart or VerifyStop. done(undpacked_reply_or_None, error)."""
    def got(res, _c):
        try:
            done(_unpack(res), "")
        except ValueError as e:
            logger.warning("fprintd %s %s: %s", note or method, method, e)
            done(None, f"fprintd did not answer: {e}")
    _system_bus(lambda conn, err: done(None, err or "the system bus is not available")
                if conn is None
                else _dbus_call(conn, path, FPRINTD_DEVICE, method, params, got, None))


def fprintd_claim(path: str, done) -> None:
    """Claim(username): take exclusive use of the reader.

    Required before EnrollStart, whose own doc says so and which fails with
    ClaimDevice if you skip it. fprintd checks the verify and enroll polkit
    actions for a Claim, both of which shani-settings' 99-shani.rules grants.
    An empty username means the calling user and skips the setusername check.
    """
    fprintd_action(path, "Claim", [_s(FPRINTD_SELF_USER)], done, "claim")


def fprintd_release(path: str, done) -> None:
    """Release(): give the reader back. A claimed reader is unusable by
    anything else, including the lock screen, so every path out of enrollment
    must call this."""
    fprintd_action(path, "Release", [], done, "release")


def fprintd_enroll_start(path: str, finger: str, done) -> None:
    """EnrollStart(finger_name): start enrolling. finger must be one of
    FINGER_NAMES - the daemon rejects anything else, and "any" among them.
    Progress arrives as EnrollStatus signals, not as a reply."""
    fprintd_action(path, "EnrollStart", [_s(finger)], done, "enroll-start")


def fprintd_enroll_stop(path: str, done) -> None:
    """EnrollStop(): end an enrollment, however it ends. A reader left
    mid-enrollment stays claimed and busy."""
    fprintd_action(path, "EnrollStop", [], done, "enroll-stop")


def fprintd_delete_finger(path: str, finger: str, done) -> None:
    """DeleteEnrolledFinger(finger_name): forget one finger (polkit asks for
    the password)."""
    fprintd_action(path, "DeleteEnrolledFinger", [_s(finger)],
                   done, "delete-enrolled-finger")


class EnrollStatusSubscription:
    """A live EnrollStatus signal subscription that can be dropped at any
    moment - including before the bus connection has arrived, which is why
    the id may still be unknown when it is dropped."""

    def __init__(self) -> None:
        self.conn = None
        self.id = None
        self.dropped = False


def fprintd_subscribe_enroll_status(path: str, on_status) -> EnrollStatusSubscription:
    """Watch the device's EnrollStatus(reason, done) signal.

    on_status(reason_text, done) is called on the main loop. The caller must
    hand the returned subscription to fprintd_unsubscribe: a page that keeps
    one open keeps calling back after enrollment is over. Subscribe before
    EnrollStart, as fprintd's own client does - the first signal can arrive
    as soon as EnrollStart returns.
    """
    sub = EnrollStatusSubscription()

    def connect(conn, err):
        if conn is None:
            logger.warning("fprintd: no bus to watch EnrollStatus on: %s", err)
            return
        sub.conn = conn
        sub.id = conn.signal_subscribe(
            FPRINTD_BUS, FPRINTD_DEVICE, "EnrollStatus", path, None,
            Gio.DBusSignalFlags.NONE, lambda _c, _s, _m, _p, params: _emit(on_status, params))
        if sub.dropped:
            # dropped while the bus connection was still on its way
            sub.conn.signal_unsubscribe(sub.id)
            sub.id = None
    _system_bus(connect)
    return sub


def _emit(on_status, params) -> None:
    """EnrollStatus's (reason, done) body, unpacked, straight onto the loop."""
    try:
        reason, done = params.unpack()
    except (GLib.Error, TypeError, ValueError) as e:
        logger.warning("fprintd: unreadable EnrollStatus signal: %s", e)
        return
    on_status(str(reason), bool(done))


def fprintd_unsubscribe(sub) -> None:
    """Drop an EnrollStatus subscription, now or as soon as it exists."""
    if sub is None:
        return
    sub.dropped = True
    if sub.conn is not None and sub.id is not None:
        sub.conn.signal_unsubscribe(sub.id)
        sub.id = None


# --- other hardware-auth stacks -----------------------------------------
# The page above reports on fprintd. These are its sibling login methods, and
# the point of this table is to be honest about which ones can actually work.
#
# A PAM service that names a module the image does not ship can never
# succeed, and PAM is silent about it at install time - the stack only breaks
# when someone tries to log in. That is exactly the bug that left smartcard
# login dead on a stock image, so it is worth surfacing rather than hiding.
#
# Every row is derived from stat() on this machine. Nothing is assumed from
# what a desktop might normally provide.

# Arch puts PAM modules in /usr/lib/security. The multiarch and /lib64 paths
# are here so the probe cannot silently report "unavailable" for a module that
# is present under a different layout - a false "not available" is worse than
# a missing row, because it tells the user their hardware cannot work.
# Where PAM service files live: GDM's in /etc/pam.d, KScreenLocker's in
# /usr/lib/pam.d. Both must be scanned, because a module wired into a
# distribution-owned chokepoint like system-auth is offered by no gdm-* or
# kde-* file at all.
PAM_SERVICE_DIRS = ("/etc/pam.d", "/usr/lib/pam.d")

# A bracketed PAM control field, which may contain spaces: [success=2 default=ignore]
_PAM_CONTROL_RE = re.compile(r"\[[^\]]*\]")

_PAM_SEC_DIRS = (
    "/usr/lib/security",
    "/lib/security",
    "/usr/lib64/security",
    "/lib64/security",
    "/usr/lib/x86_64-linux-gnu/security",
    "/lib/x86_64-linux-gnu/security",
)

# PAM services that offer a login method, and the module each one loads.
# GDM ships these in /etc/pam.d, KScreenLocker in /usr/lib/pam.d.
_PAM_LOGIN_SERVICES = (
    ("/etc/pam.d/gdm-smartcard", "Smartcard (PIV) login", "pam_pkcs11.so"),
    ("/usr/lib/pam.d/kde-smartcard", "Smartcard (PIV) unlock", "pam_pkcs11.so"),
    ("/etc/pam.d/gdm-fingerprint", "Fingerprint login", "pam_fprintd.so"),
    ("/usr/lib/pam.d/kde-fingerprint", "Fingerprint unlock", "pam_fprintd.so"),
)

# Login methods that have a PAM module in the official Arch repositories.
# "extra" is where all of these live; none of them is in [core].
# Listed without a PAM service are installed but offered nowhere.
_LOGIN_MODULES = (
    ("Security key (FIDO2/U2F) login", "pam_u2f.so",
     "plug in the key and touch it when prompted"),
    ("Kerberos login", "pam_krb5.so",
     "needs a working realm and a keytab first"),
    ("Yubico OTP login", "pam_yubico.so",
     "legacy one-time-password keys, not FIDO2"),
)

# Biometric methods with no usable PAM module for Linux at all. These are
# reported as unavailable on purpose: a silent omission reads as "nobody has
# ever heard of face login", which is its own kind of wrong.
_NO_PAM_MODULE = (
    ("Face / webcam recognition", "howdy",
     "exists only as an unmaintained AUR package; its last tagged release was "
     "in 2020, and it is wired into no login screen"),
    ("Iris (eye) recognition", None,
     "no maintained Linux implementation with a PAM module exists"),
    ("Voice / speaker recognition", "pam_voiceprint",
     "the only implementation was a hackathon project last touched in 2022, "
     "packaged nowhere"),
    ("Retinal, palm, vein, gait, keystroke", None,
     "research-only; no PAM implementation exists for any of these"),
)


def _pam_module_installed(module: str) -> bool:
    """True if this PAM module is present in any standard module directory."""
    return any(os.path.exists(os.path.join(d, module)) for d in _PAM_SEC_DIRS)


def _pam_service_loading(text: str, module: str, depth: int = 0,
                         seen: set | None = None) -> bool:
    """Does this PAM service text load `module`?

    Honours the control prefixes PAM understands: a leading '-' means the line
    is present but disabled, a leading '@' means it is only evaluated when the
    module is *required* by the caller. Neither counts as "offered", so a
    commented or disabled reference cannot make a method look wired.
    """
    if depth > 3:
        return False
    seen = set() if seen is None else seen
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("@"):
            if line.startswith("@include"):
                target = line[len("@include"):].strip()
                if target and target not in seen:
                    seen.add(target)
                    for d in PAM_SERVICE_DIRS:
                        path = os.path.join(d, os.path.basename(target))
                        if os.path.exists(path) and _pam_service_loading(
                                _read_text(path), module, depth + 1, seen):
                            return True
            continue
        if line.startswith("-"):
            # Present but disabled. PAM will not use it, so it must not make a
            # method look wired - that would tell a user their security key
            # works when the line that would accept it is switched off.
            continue
        # PAM puts optional control fields between the type and the module:
        #   auth  [success=2 default=ignore]  pam_unix.so nullok
        # The bracket may contain spaces, so it has to be removed as a unit
        # before splitting - splitting first leaves "[success=2" and
        # "default=ignore]" as separate tokens and the module is never reached.
        rest = _PAM_CONTROL_RE.sub(" ", line)
        # The module is the first argument that looks like one - an absolute
        # path, or a name ending in .so. Indexing a fixed position does not
        # work: the line is "<type> <control> <module> [args]", so the module
        # is at index 2 normally but at index 1 when the control field was a
        # bracketed one and removing it collapsed the line.
        for field in rest.split()[1:]:
            if field.startswith("/") or field.endswith(".so"):
                if field == module:
                    return True
                # This line loads a different module. Move to the next line
                # rather than giving up on the whole file - returning here
                # missed every module that appears after an unrelated one.
                break
    return False


def _read_text(path: str) -> str:
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return ""


def pam_stacks_loading(module: str) -> list:
    """Names of the PAM service files on this system that load `module`.

    Scans the real files rather than trusting a hardcoded list, because Shanios
    wires pam_u2f into its own system-auth override, which no gdm-* or kde-*
    file mentions. A hardcoded list reported that as "installed but not
    offered" on every machine we ship.
    """
    found: list = []
    for d in PAM_SERVICE_DIRS:
        try:
            names = sorted(os.listdir(d))
        except OSError:
            continue
        for name in names:
            if name == "other":
                continue
            if any(n == name for n in found):
                continue
            if _pam_service_loading(_read_text(os.path.join(d, name)), module):
                found.append(name)
    return found


def _pam_service_offers(module: str) -> list:
    """Every PAM service that offers `module`: the real scan, unioned with the
    known gdm-*/kde-* files so a service outside the scanned directories is
    still reported."""
    offers = pam_stacks_loading(module)
    for path, _title, mod in _PAM_LOGIN_SERVICES:
        if mod == module and os.path.exists(path):
            name = os.path.basename(path)
            if name not in offers:
                offers.append(name)
    return offers


def hardware_auth_status() -> list:
    """Report every non-fingerprint login method this image can offer.

    Returns a list of {"title", "detail", "state", "module"} rows. "state" is
    "ok" (offered by a PAM service and its module is present), "inactive"
    (module present but no PAM service offers it, so it cannot be used until
    one does), or "unavailable" (no usable PAM module, so it cannot succeed).

    Synchronous by design: this is a handful of stat() calls, and a callback
    would only make it untestable.
    """
    rows: list = []

    for path, title, module in _PAM_LOGIN_SERVICES:
        if not os.path.exists(path):
            continue
        service = os.path.basename(path)
        if _pam_module_installed(module):
            rows.append({"title": title, "module": module, "state": "ok",
                         "detail": f"{service} — {module} present"})
        else:
            rows.append({"title": title, "module": module, "state": "unavailable",
                         "detail": f"{service} needs {module}, which this image "
                                   f"does not ship — this method cannot succeed"})

    for title, module, note in _LOGIN_MODULES:
        if not _pam_module_installed(module):
            rows.append({"title": title, "module": module, "state": "unavailable",
                         "detail": f"{module} is not installed"})
            continue
        services = _pam_service_offers(module)
        if services:
            rows.append({"title": title, "module": module, "state": "ok",
                         "detail": f"{module} — offered by {', '.join(services)}"})
        else:
            rows.append({"title": title, "module": module, "state": "inactive",
                         "detail": f"{module} is installed but no PAM service on "
                                   f"this system offers it — {note}"})

    for title, pkg, why in _NO_PAM_MODULE:
        rows.append({"title": title, "module": None, "state": "unavailable",
                     "detail": f"not available: {why}"})

    return rows
