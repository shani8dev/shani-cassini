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
FPRINTD_CLI = "fprintd-enroll"          # ships in /usr/sbin
FPRINTD_BUS = "net.reactivated.Fprint"
FPRINTD_PATH = "/net/reactivated/Fprint"
FPRINTD_MANAGER = "net.reactivated.Fprint.Manager"
FPRINTD_DEVICE = "net.reactivated.Fprint.Device"
FPRINTD_PROPERTIES = "org.freedesktop.DBus.Properties"
SBIN_DIRS = ("/usr/sbin", "/usr/local/sbin")

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
               "This edition logs in through Plasma's own login manager (plasmalogin), whose PAM "
               "services never reference pam_fprintd, so the login screen cannot take a "
               "fingerprint. kscreenlocker ships /usr/lib/pam.d/kde-fingerprint for the lock "
               "screen, which must be enabled with: kwriteconfig6 --file kscreenlockerrc "
               "--group Authenticators --key Fingerprint true"),
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


def _dbus_call(conn: Gio.DBusConnection, path: str, iface: str, method: str,
               params: list, got: Callable[[Gio.AsyncResult, Gio.DBusConnection], None],
               reply_type: Optional[str] = "(v)") -> Gio.Cancellable:
    """One method call on a bus we already hold; got() runs on the main loop.

    params are single-value Variants; conn.call wants them as the argument
    tuple, or None for a method that takes none. reply_type=None for the
    methods that return nothing (EnrollStart, EnrollStop, Delete) - asking for
    a "(v)" reply there is an error, not an empty one."""
    if params:
        sig = "(" + "".join(p.get_type_string() for p in params) + ")"
        args = GLib.Variant(sig, tuple(params))
    else:
        args = GLib.Variant("()", ())
    return conn.call(FPRINTD_BUS, path, iface, method, args,
                     GLib.VariantType(reply_type) if reply_type else None,
                     Gio.DBusCallFlags.NONE, 25000, None, lambda r, c: got(r, c))


def _unpack(message: Gio.DBusMessage) -> list:
    try:
        reply = message.get_reply()   # a D-Bus error is raised here, not returned
        if reply is None:             # a method with no return value
            return []
        return list(reply.unpack())
    except (GLib.Error, TypeError, ValueError) as e:
        raise ValueError(str(e)) from e


def _properties(unpacked: list) -> dict:
    """A GetAll reply: the a{sv} is the single argument of the (v) reply."""
    values = _plain(unpacked[0]) if unpacked else {}
    if not isinstance(values, dict):
        logger.warning("fprintd: GetAll answered %r, not a{sv}", type(values).__name__)
        return {}
    return {str(k): _plain(v) for k, v in values.items()}


def _plain(value):
    """The Python value of a possibly-wrapped variant.

    GLib.Variant.unpack() deep-unpacks, so an "a{sv}" reply normally arrives
    as a dict of plain values - but a child can still come back as a variant
    on other PyGObject versions, and str() of an object-path variant is
    "objectpath '/net/...'", not the path. Unwrap first, then stringify."""
    unpack = getattr(value, "unpack", None)
    return unpack() if callable(unpack) else value


def fprintd_status(done: Callable[[Optional[dict], str], None], timeout_s: float = 6.0) -> None:
    """Ask fprintd for the reader and the fingers enrolled on it.

    done(status_or_None, error_text) on the main loop. status is
    {"daemon": bool, "device_present": bool, "device_name": str, "driver": str,
    "enabled": bool|None, "action": str, "path": str, "fingers": [{uid,
    nickname, finger, state}]}. A daemon that cannot be reached is
    (None, error) - that is the difference between "no fingerprints are
    enrolled" and "nobody answered", and the page must not confuse them.
    timeout_s bounds the whole chain: a reader that stops answering mid-call
    must not leave the page spinning.
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
            _fprintd_device(conn, paths, finish)
        _dbus_call(conn, FPRINTD_PATH, FPRINTD_MANAGER, "GetDevices", [], devices)

    _system_bus(status_step)


def _fprintd_device(conn, paths: list[str], finish) -> None:
    """The first device's properties + its enrolled fingers, or the honest
    "daemon is up, no reader" answer when GetDevices came back empty."""
    if not paths:
        finish({"daemon": True, "device_present": False, "device_name": "", "driver": "",
                "enabled": None, "action": "", "path": "", "fingers": []})
        return
    path = paths[0]

    def props(res, _c):
        try:
            raw = _unpack(res)
        except ValueError as e:
            finish(None, f"fprintd did not answer: {e}")
            return
        # GetAll returns a{sv}
        props_ = _properties(raw)
        _fprintd_fingers(conn, path, props_, finish)
    _dbus_call(conn, path, FPRINTD_PROPERTIES, "GetAll", [GLib.Variant("s", FPRINTD_DEVICE)], props)


def _fprintd_fingers(conn, path: str, props: dict, finish) -> None:
    def fingers(res, _c):
        try:
            raw = _unpack(res)
        except ValueError as e:
            finish(None, f"fprintd did not answer: {e}")
            return
        # a(ssuss): finger, nickname, uid, scan type, state, date added
        parsed = []
        for entry in raw:
            try:
                finger, nickname, uid, _scan, state = entry[0], entry[1], int(entry[2]), entry[3], entry[4]
            except (TypeError, ValueError, IndexError):
                logger.warning("fprintd: unexpected ListEnrolledFingers entry %r", entry)
                continue
            parsed.append({"finger": str(finger), "nickname": str(nickname), "uid": uid,
                           "state": str(state)})
        finish({"daemon": True,
                "device_present": bool(props.get("DevicePresent")),
                "device_name": str(props.get("Name") or ""),
                "driver": str(props.get("Driver") or ""),
                "enabled": props.get("DeviceEnabled"),
                "action": str(props.get("Action") or ""),
                "path": path,
                "fingers": parsed})
    _dbus_call(conn, path, FPRINTD_DEVICE, "ListEnrolledFingers",
               [GLib.Variant("u", int(os.getuid()))], fingers)


def fprintd_properties(path: str, done: Callable[[Optional[dict], str], None]) -> None:
    """One device's net.reactivated.fprint.Device properties (Name, Driver,
    DevicePresent, DeviceEnabled, Action). Enrollment watches Action, which is
    the only honest way to know a scan is still being asked for."""
    def props(res, _c):
        try:
            raw = _unpack(res)
        except ValueError as e:
            done(None, f"fprintd did not answer: {e}")
            return
        done(_properties(raw), "")
    _system_bus(lambda conn, err: done(None, err) if conn is None
                else _dbus_call(conn, path, FPRINTD_PROPERTIES, "GetAll", [GLib.Variant("s", FPRINTD_DEVICE)], props))


def _fprintd_action(path: str, method: str, params: list,
                    done: Callable[[Optional[list], str], None], note: str) -> None:
    """EnrollStart / Enroll / EnrollStop / Delete. `method` names a
    net.reactivated.Fprint.Device method; done(undpacked_reply_or_None, error)."""
    def got(res, _c):
        try:
            done(_unpack(res), "")
        except ValueError as e:
            logger.warning("fprintd %s %s: %s", note, method, e)
            done(None, f"fprintd did not answer: {e}")
    # EnrollStart, EnrollStop and Delete return nothing; only Enroll answers.
    reply_type = "(v)" if method == "Enroll" else None
    _system_bus(lambda conn, err: done(None, err or "the system bus is not available")
                if conn is None
                else _dbus_call(conn, path, FPRINTD_DEVICE, method, params, got, reply_type))


def fprintd_enroll_start(path: str, nickname: str,
                         done: Callable[[Optional[list], str], None]) -> None:
    """EnrollStart(nickname): fprintd claims the reader and sets Action to
    "enroll". From here Enroll() is called once per accepted scan."""
    _fprintd_action(path, "EnrollStart", [GLib.Variant("s", nickname)], done, "enroll-start")


def fprintd_enroll(path: str, uid: int,
                   done: Callable[[Optional[list], str], None]) -> None:
    """Enroll(uid) -> (accepted, reason). False is a normal answer (a scan
    that was too fast, or a finger that is already enrolled), not an error."""
    _fprintd_action(path, "Enroll", [GLib.Variant("u", int(uid))], done, "enroll")


def fprintd_enroll_stop(path: str, done: Callable[[Optional[list], str], None]) -> None:
    """EnrollStop(): always called, on success, on cancel and on timeout -
    a reader left mid-enroll stays claimed and unusable."""
    _fprintd_action(path, "EnrollStop", [], done, "enroll-stop")


def fprintd_delete(path: str, uid: int,
                   done: Callable[[Optional[list], str], None]) -> None:
    """Delete(uid): remove one enrolled finger (polkit asks for the password)."""
    _fprintd_action(path, "Delete", [GLib.Variant("u", int(uid))], done, "delete")
