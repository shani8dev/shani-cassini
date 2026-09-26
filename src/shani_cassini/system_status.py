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

from shani_cassini.config_io import (
    ConfigRefused,
    Document,
    Staged,
    parse_braces,
    parse_flat,
    parse_ini,
    read_document,
    stage,
    write_staged_privileged,
    write_staged_unprivileged,
)

# config_io calls the three grammars a parser and indexes them by identity;
# naming that callable is how a caller states which one a file is written in.
_Parser = Callable[..., Document]

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


# --- the sign-in configuration files --------------------------------------
#
# Five files decide how someone signs in, and every one of them can lock a
# machine out, so none of them is edited by re-rendering it: config_io
# rewrites the single line a page names and refuses anything it could not
# read back. Two rules hold for everything below.
#
# * A refusal is a message, not an exception. ConfigRefused is how the engine
#   says "nothing was written", and it must never reach the GTK main loop, so
#   every writer here reports it as done(message, "").
# * An absent file is a state, not a failure. pam_u2f falls back to its
#   built-in defaults, and a machine may simply have no krb5.conf - a reader
#   says so and invents nothing.

PKCS11_CONF = "/etc/pam_pkcs11/pam_pkcs11.conf"
SUBJECT_MAPPING = "/etc/pam_pkcs11/subject_mapping"
# Written by the distro's pam_pkcs11 packaging; one line, the path of the
# PC/SC provider opensc installs. Absent on Arch, where pam_pkcs11.conf names
# the module inline - so its absence is not reported as a fault.
PKCS11_MODULE_PATH = "/etc/pam_pkcs11/opensc-module-path"
PAM_YUBICO_CONF = "/etc/security/pam_yubico.conf"
KRB5_CONF = "/etc/krb5.conf"
# pam_yubico's own default, with its per-user mapping file format
# (username:first_public_id:second_public_id).
YUBICO_AUTHFILE_DEFAULT = "~/.yubico/authorized_yubikeys"

# The keys pam_yubico documents, and no others: a file holding a key outside
# this list is reported with known_only False rather than quietly rewritten.
PAM_YUBICO_KEYS = (
    "authfile", "id", "key", "alwaysok", "try_first_pass", "use_first_pass",
    "always_prompt", "nullok", "ldap_starttls", "ldap_bind_as_user",
    "urllist", "mode", "debug", "debug_file", "chalresp_path",
)

# The settings pam-u2f 1.4.0's own cfg.c accepts, and nothing else. Each is a
# bare flag or takes a value; there is no touchauth and no verbose, so a page
# must never offer them.
U2F_KEYS = (
    "authfile", "origin", "appid", "alwaysok", "nouserok", "interactive",
    "cue", "nodetect", "expand", "sshformat", "openasuser", "manual", "debug",
)

# A Kerberos realm is a name: letters, digits, dots and dashes.
_REALM_RE = re.compile(r"^[A-Za-z0-9.-]+$")

# krb5.conf is strictly sectioned, so a credential cache is only usable at an
# ordinary login when it is a file. KEYRING: needs the session keyring and
# KCM: a running KCM daemon, and a login that starts before either does gets
# no ticket at all.
_CACACHE_PREFIXES = ("FILE:", "DIR:", "KEYRING:", "KCM:")

# A flat line whose own separator is 'key = value' rather than 'key value'.
_KEY_EQUALS = re.compile(r"^\s*\S+\s*=")
# krb5.conf's own include forms, which parse_ini cannot represent and which
# _ini_pieces' pre-section whitelist therefore never gets to see.
_INCLUDE_RE = re.compile(r"^\s*(?:include|includedir)\s+\S")
# A pcsc_scan row starts with its reader number, which is what tells a reader
# from the table's own header and separator.
_PCSC_ROW_RE = re.compile(r"^\s*(\d+)\s+(\S.*?)\s*$")

# Every /etc file below is root-owned, and a save refuses one that is not: a
# config file that changed hands is not the file this page was written for.
# The user's own pam_u2f.conf is the exception and passes expect_owner=None.
CONFIG_OWNER: Optional[tuple[int, int]] = (0, 0)


def _unreadable(doc: Document) -> list[str]:
    """One message per line this engine could not read, for a page to show."""
    return [f"line {index + 1} cannot be read: {doc.lines[index].raw.strip()}"
            for index in doc.has_other()]


def _open(path: str, parser: _Parser) -> Optional[Document]:
    """A config file to read, or None with the reason in the log.

    Ownership is deliberately not checked: these are readers, and a file this
    process cannot edit is still a file it can report on.
    """
    try:
        return read_document(path, parser, expect_owner=None)
    except ConfigRefused as refused:
        logger.warning("%s: %s", path, refused)
        return None


def _unmarked(value: str) -> str:
    """A flat value without the optional '=' parse_flat leaves in front of it.

    Both flat formats are `key value` and `key = value`, and parse_flat's
    separator is the whitespace, so an '=' lands in the value it reads. The
    reader drops it and the writer puts back the one the line being edited
    already had - see _set_value.
    """
    return value[1:].strip() if value.startswith("=") else value


def _unmapped_setting(raw: str) -> Optional[tuple[str, str]]:
    """A single-token flat line read as (key, value), or None.

    parse_flat needs a run of whitespace to find a key, so both forms these
    two modules accept - `key=value` and a bare flag - come back as ``other``.
    config_io's own docstring makes ``Line.raw`` the authoritative text and
    says a caller must split a shape the grammar cannot model itself, so this
    is that split, and only for a line with no whitespace in it at all.
    """
    body = raw.strip()
    if not body or body.startswith("#"):
        return None
    key, equals, value = body.partition("=")
    key = key.strip()
    if not key or any(character.isspace() for character in key):
        return None
    return key, (value.strip() if equals else "")


def _flat_settings(path: str, known: tuple[str, ...]) -> dict:
    """The settings a flat module config holds, and whether all are known.

    A presence-only flag reads as an empty value, so the page can tell "this
    is on" from "this has been given something".
    """
    conf = {"exists": os.path.exists(path), "values": {}, "known_only": True,
            "path": path}
    if not conf["exists"]:
        return conf
    doc = _open(path, parse_flat)
    if doc is None:
        return conf
    for line in doc.lines:
        if line.kind == "directive":
            key, value = line.key, _unmarked(line.value)
        elif line.kind == "other":
            unmapped = _unmapped_setting(line.raw)
            if unmapped is None:
                continue
            key, value = unmapped
        else:
            continue
        if key not in known:
            conf["known_only"] = False
        conf["values"][key] = value
    return conf


def pam_pkcs11_state() -> dict:
    """The smartcard login path: the module, its mappers, its provider.

    ``mappers`` is ``Document.mappers()`` - the block header text to its
    directives - so a page can show the ``mapper subject`` block that decides
    who a card signs in as, and the ``mapper openssh`` / ``mapper opensc``
    blocks that match $HOME/.ssh/authorized_keys and
    $HOME/.eid/authorized_certificates. Never raises: a conf that is missing
    or unreadable is a ``problems`` entry, not a traceback.
    """
    state = {"installed": _pam_module_installed("pam_pkcs11.so"),
             "conf_exists": os.path.exists(PKCS11_CONF), "mappers": {},
             "provider": _read_text(PKCS11_MODULE_PATH).strip(), "problems": []}
    if not state["conf_exists"]:
        state["problems"].append(
            f"{PKCS11_CONF} is missing - the module has no configuration to use")
        return state
    doc = _open(PKCS11_CONF, parse_braces)
    if doc is None:
        state["problems"].append(f"{PKCS11_CONF} could not be read")
        return state
    state["mappers"] = doc.mappers()
    state["problems"] = _unreadable(doc)
    return state


def _mapping_lines(doc: Document) -> tuple[list[dict], list[dict]]:
    """(entries, problems) for one parsed subject_mapping.

    Each line is split on the LAST '->', because a DN may contain one and the
    separator is the last one on the line. ``lineno`` is the 0-based index of
    the line, which is what a later edit needs to rewrite that exact line.
    """
    entries: list[dict] = []
    problems: list[dict] = []
    for index, line in enumerate(doc.lines):
        if line.kind in ("blank", "comment"):
            continue
        cut = line.raw.rfind("->")
        if cut < 0:
            problems.append({"lineno": index, "raw": line.raw,
                             "why": "there is no '->' in it"})
            continue
        subject, login = line.raw[:cut].strip(), line.raw[cut + 2:].strip()
        if not subject or not login:
            problems.append({"lineno": index, "raw": line.raw,
                             "why": "a certificate subject and a login name are both needed"})
            continue
        entries.append({"subject": subject, "login": login, "lineno": index})
    return entries, problems


def subject_mappings() -> dict:
    """Who each smartcard signs in as, read from the live subject_mapping.

    The file pam_pkcs11 installs is a comment-only template, so ``entries == []``
    with no problems is the normal state of a fresh machine and not a fault.
    A non-blank line with no '->', or with only one side of one, is a problem
    with its line number, and a write refuses the whole file rather than
    rewriting a line it could not read. Never raises; a ``lineno`` below zero
    means the file as a whole could not be read.
    """
    state = {"exists": os.path.exists(SUBJECT_MAPPING), "entries": [],
             "problems": [], "path": SUBJECT_MAPPING}
    if not state["exists"]:
        return state
    doc = _open(SUBJECT_MAPPING, parse_flat)
    if doc is None:
        state["problems"].append({"lineno": -1, "raw": "",
                                  "why": f"{SUBJECT_MAPPING} could not be read"})
        return state
    state["entries"], state["problems"] = _mapping_lines(doc)
    return state


def pam_yubico_config() -> dict:
    """The Yubico OTP settings, as pam_yubico.conf holds them.

    ``known_only`` is False when the file holds a key this version of the
    module does not document, so a page can say so instead of dropping it on
    the next save.
    """
    return _flat_settings(PAM_YUBICO_CONF, PAM_YUBICO_KEYS)


def u2f_conf_path() -> str:
    """Where pam-u2f looks for its per-user config."""
    base = os.environ.get("XDG_CONFIG_HOME") or \
        os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "Yubico", "pam_u2f.conf")


def u2f_config() -> dict:
    """The FIDO2/U2F settings, as ~/.config/Yubico/pam_u2f.conf holds them.

    An absent file yields ``exists: False`` and no values: that is the module
    running on its built-in defaults, and rendering anything else would be
    inventing settings nobody wrote.
    """
    return _flat_settings(u2f_conf_path(), U2F_KEYS)


def krb5_config() -> dict:
    """What /etc/krb5.conf says, with the includes named but not followed.

    ``default_realm`` and ``default_ccache_name`` are read from
    [libdefaults] and nowhere else: krb5.conf is strictly sectioned, so a
    top-level one is not a setting it would honour. ``includes`` lists the
    include/includedir lines Cassini deliberately does not follow - they can
    pull in a whole directory tree, and a page that showed their contents as
    this file's would be reporting a file the user never opened. Everything
    else is ``other``, as (section, key, value).
    """
    conf = {"exists": os.path.exists(KRB5_CONF), "default_realm": "",
            "default_ccache_name": "", "domain_realm": {}, "other": [],
            "includes": [], "problems": []}
    if not conf["exists"]:
        return conf
    doc = _open(KRB5_CONF, parse_ini)
    if doc is None:
        conf["problems"].append(f"{KRB5_CONF} could not be read")
        return conf
    conf["default_realm"] = doc.get("default_realm", "libdefaults") or ""
    conf["default_ccache_name"] = doc.get("default_ccache_name", "libdefaults") or ""
    for index, line in enumerate(doc.lines):
        if _INCLUDE_RE.match(line.raw):
            conf["includes"].append(line.raw.strip())
        elif line.kind != "directive":
            if line.kind == "other":
                conf["problems"].append(
                    f"line {index + 1} cannot be read: {line.raw.strip()}")
        elif line.section == "domain_realm":
            conf["domain_realm"][line.key] = line.value
        elif line.section == "libdefaults" and \
                line.key in ("default_realm", "default_ccache_name"):
            continue
        else:
            conf["other"].append((line.section, line.key, line.value))
    return conf


def pcsc_readers(done: Callable[[Optional[list], str], None]) -> None:
    """The smartcard and NFC readers pcsc-lite can see, unprivileged.

    done(readers_or_None, error) on the main loop, the shape every other
    reader here uses. An empty list means pcsc_scan answered and no reader is
    attached; None means it did not answer at all, and a page must be able to
    tell those apart rather than showing "no reader" for a daemon that is not
    running.

    pcsc-lite prints a free-text card column that may be two words wide, so
    the row is reported as its number and the rest of the line rather than
    guessed into card and features.
    """
    lines: list[str] = []

    def scanned(status: int) -> None:
        if status != 0:
            tail = next((line for line in reversed(lines) if line.strip()), "")
            GLib.idle_add(done, None, tail or f"pcsc_scan exited {status}")
            return
        readers = []
        for line in lines:
            row = _PCSC_ROW_RE.match(line)
            if row:
                readers.append({"nr": int(row.group(1)), "text": row.group(2)})
        GLib.idle_add(done, readers, "")

    run_streaming(["pcsc_scan", "-n"], lines.append, scanned)


# --- writing them ---------------------------------------------------------
#
# Every writer here is synchronous and may block: a privileged save runs
# install(1) under pkexec, and config_io's own docstring says the caller runs
# it off the main loop. A page that calls these from a Gio.Thread and hands the
# callback back to the main loop keeps the window alive.


def _set_value(doc: Document, key: str, value: str, section: str) -> None:
    """doc.set(), keeping the '=' marker the line being edited already used.

    A flat line's separator is the whitespace, so an '=' belongs to the value
    parse_flat reads back; the reader drops it, and this puts back the one
    that line had rather than the one its neighbours use.
    """
    found = doc.find(key, section)
    marked = found and doc.syntax == "flat" and \
        _KEY_EQUALS.match(doc.lines[found[0]].raw) is not None
    doc.set(key, f"= {value}" if marked else value, section=section)


def _confirm(path: str, key: str, value: str, section: str, parser: _Parser,
             done: Callable[[str, str], None]) -> None:
    """Read the file back and check the setting is what was asked for.

    A save that reports success has been confirmed by whoever wrote it - by
    install(1) for a privileged file, by os.replace for our own. What this
    catches is the one thing neither can: a page that then renders a value the
    file does not hold.
    """
    doc = _open(path, parser)
    if doc is None:
        done(f"{path} was saved but cannot be read back to check it", "")
        return
    if _unmarked(doc.get(key, section) or "") != value:
        done(f"{path} was saved, but {key} does not hold the new value - "
             "check the file by hand", "")
        return
    done("", f"Saved {path}")


def _install(staged: Staged, done: Callable[[str, str], None],
             on_saved: Callable[[], None]) -> None:
    """Write staged with the writer the file's owner calls for, then on_saved."""
    if not staged.privileged:
        try:
            write_staged_unprivileged(staged)
        except OSError as exc:
            done(f"{staged.path} could not be saved: {exc.strerror or exc}", "")
            return
        on_saved()
        return
    write_staged_privileged(staged, lambda error, note: done(error, note) if error
                            else on_saved())


def set_config_value(path: str, key: str, value: str, *, section: str = "",
                     parser: _Parser, must_contain: tuple[str, ...] = (),
                     done: Callable[[str, str], None],
                     validator: Optional[Callable[[str], None]] = None,
                     expect_owner: Optional[tuple[int, int]] = CONFIG_OWNER) -> None:
    """Set one setting in one config file, and report done(error, note).

    ``parser`` and ``must_contain`` are arguments rather than guesses here:
    the caller states which grammar the file is written in and which marker
    proves the file on disk is the one this page means, and the engine refuses
    when neither holds. ``expect_owner`` defaults to CONFIG_OWNER - root, the
    owner of every /etc file below - and a file of the user's own passes None
    and is then written unprivileged, without a polkit dialog.

    ``validator`` is handed the text that would be written and raises anything
    to refuse it; the refusal arrives as done(message, "") like every other.
    Never raises: nothing here leaves this function as an exception.
    """
    try:
        doc = read_document(path, parser, must_contain=must_contain,
                            expect_owner=expect_owner)
        _set_value(doc, key, value, section)
        staged = stage(doc, validator=validator)
    except ConfigRefused as refused:
        done(str(refused), "")
        return
    _install(staged, done, lambda: _confirm(path, key, value, section, parser, done))


def _mapping_grammar(subject: str, login: str) -> str:
    """Why this pair cannot be written, or "" when it can.

    A '->' inside either side is refused even though the reader copes with one,
    because that is the module's own line format to define and not Cassini's.
    """
    if not subject.strip() or not login.strip():
        return "a certificate subject and a login name are both needed"
    for side, what in ((subject, "certificate subject"), (login, "login name")):
        if "->" in side:
            return f"a '->' inside the {what} cannot be written - the mapfile's own "
            "format has no way to say which one separates"
    return ""


def _mapping_document() -> tuple[Optional[Document], list[dict], str]:
    """The live subject_mapping, its entries, and the reason it is unusable.

    Returns (None, [], why) rather than raising, so a caller only has to hand
    ``why`` to done.
    """
    try:
        doc = read_document(SUBJECT_MAPPING, parse_flat, expect_owner=CONFIG_OWNER)
    except ConfigRefused as refused:
        return None, [], str(refused)
    entries, problems = _mapping_lines(doc)
    if problems:
        return None, [], (f"{SUBJECT_MAPPING} has a line that cannot be read "
                          f"(line {problems[0]['lineno'] + 1}) - fix it by hand, "
                          "nothing was changed")
    return doc, entries, ""


def set_mapping(subject: str, login: str, *, done: Callable[[str, str], None]) -> None:
    """Point one certificate subject at one login name.

    A subject that is already mapped is rewritten on its own line, so a
    certificate never ends up on two lines and the comments and blank lines
    around it are untouched. A file with a line Cassini could not read is never
    rewritten at all. done(error, note) - never an exception.
    """
    why = _mapping_grammar(subject, login)
    if why:
        done(why, "")
        return
    doc, entries, why = _mapping_document()
    if doc is None:
        done(why, "")
        return
    mapped = [entry for entry in entries if entry["subject"] == subject]
    if mapped:
        doc.replace_line(mapped[0]["lineno"], f"{subject} -> {login}")
    else:
        done(f"{SUBJECT_MAPPING} has no entry for this certificate, and Cassini "
             "cannot add a line to it - add it in a terminal, then set its login "
             "name here", "")
        return
    _save_mapping(doc, done)


def remove_mapping(subject: str, *, done: Callable[[str, str], None]) -> None:
    """Take one subject's mapping away. Its line is emptied, not deleted, so
    every other line keeps its place. done(error, note)."""
    doc, entries, why = _mapping_document()
    if doc is None:
        done(why, "")
        return
    mapped = [entry for entry in entries if entry["subject"] == subject]
    if not mapped:
        done(f"{SUBJECT_MAPPING} has no entry for that certificate", "")
        return
    doc.remove_line(mapped[0]["lineno"])
    _save_mapping(doc, done)


def _save_mapping(doc: Document, done: Callable[[str, str], None]) -> None:
    try:
        staged = stage(doc)
    except ConfigRefused as refused:
        done(str(refused), "")
        return
    _install(staged, done, lambda: done("", f"Saved {SUBJECT_MAPPING}"))


def _krb5_valid(text: str) -> None:
    """Refuse a realm that is not a name, and a cache an ordinary login
    cannot read. Raises; stage() turns that into one refusal."""
    doc = parse_ini(text, path=KRB5_CONF)
    realm = doc.get("default_realm", "libdefaults")
    if realm is not None and not _REALM_RE.match(realm):
        raise ValueError(f"a Kerberos realm is a name like SHANI.LAN - "
                         f"{realm!r} is not one")
    ccache = doc.get("default_ccache_name", "libdefaults")
    if ccache is not None and ccache:
        kind = next((prefix for prefix in _CACACHE_PREFIXES
                     if ccache.upper().startswith(prefix)), "")
        if not kind:
            raise ValueError(f"{ccache!r} is not a credential cache type krb5 "
                             "knows - use FILE: for an ordinary login")
        if kind != "FILE:":
            raise ValueError(f"a {kind} credential cache cannot be used for an "
                             "ordinary login - it needs a running keyring or KCM "
                             "daemon that a login at this machine does not have. "
                             "Use FILE:")


def krb5_set(key: str, value: str, *, done: Callable[[str, str], None]) -> None:
    """Set one [libdefaults] setting in /etc/krb5.conf, root save.

    default_realm must be a realm name and default_ccache_name a FILE: cache -
    see _krb5_valid. done(error, note), never an exception.
    """
    set_config_value(KRB5_CONF, key, value, section="libdefaults", parser=parse_ini,
                     must_contain=("[libdefaults]",), done=done, validator=_krb5_valid,
                     expect_owner=CONFIG_OWNER)

