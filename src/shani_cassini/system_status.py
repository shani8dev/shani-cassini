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
from typing import Callable, Final, Optional

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


def run_text(argv: list[str], done: Callable[[Optional[str], str], None]) -> None:
    """Run argv; call done(stdout_text_or_None, error_text) on the main loop.

    The plain-text twin of run_json(), for tools that answer in text or
    Key=Value lines. stdout and stderr stay separate here as they do there, so
    a tool's diagnostics on stderr can never be read as its data -- which is
    why this is not run_streaming(), whose merged stream is right for showing a
    long read's progress and wrong for collecting a value.

    A non-zero exit is not an error here. `systemd-analyze time` can exit
    non-zero and still print the figure, and callers used to get whatever
    stdout said regardless of status.
    """
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
        if not out or not out.strip():
            done(None, _strip_ansi(err or "").strip() or f"{argv[0]} said nothing")
            return
        done(out, "")

    proc.communicate_utf8_async(None, None, finish)


def run_status(argv: list[str], done: Callable[[Optional[int], str], None]) -> None:
    """Run argv; call done(exit_status_or_None, error_text) on the main loop.

    The third reader, for a tool whose answer is its exit status rather than its
    output. `systemd-analyze has-tpm2 -q` prints nothing at all and answers 0
    for a usable TPM2, so run_text() would call the one case that matters
    "said nothing" and report it as a failure. Do not reach for this when the
    output is the answer -- run_text() or run_json() is the better fit there.
    """
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
            p.communicate_utf8_finish(res)
        except GLib.Error as e:
            done(None, e.message)
            return
        if not p.get_if_exited():
            done(None, f"{argv[0]} did not exit")
            return
        done(p.get_exit_status(), "")

    proc.communicate_utf8_async(None, None, finish)


def clock_summary(done) -> None:
    """The Device card's clock row: timezone and whether time is synced.

    Was read with a synchronous subprocess.run inside DeviceGroup.__init__,
    which put a 10s-timeout call on the GTK main thread while the page was
    being built. The rest of this page already runs through Gio.Subprocess.
    """
    def on_text(text, err):
        if not text:
            done("", err)
            return
        td = {}
        for line in text.splitlines():
            if "=" in line:
                key, _, value = line.partition("=")
                td[key.strip()] = value.strip()
        if not td:
            done("", err)
            return
        synced = "synchronized with network time" if td.get("NTPSynchronized") == "yes" else "not synchronized"
        done(f"{td.get('Timezone', '')} · {synced}", "")
    run_text(["timedatectl", "show"], on_text)


def boot_time_summary(done) -> None:
    """The Device card's 'Last boot took' row, from systemd-analyze time.

    Same synchronous-main-thread defect as clock_summary(); `systemd-analyze
    time` parses the whole boot journal, so on a large journal or a slow disk
    it is the more likely of the two to sit on that timeout.
    """
    def on_text(text, err):
        lines = text.splitlines() if text else []
        if not lines:
            done("", err)
            return
        done(lines[0].replace("Startup finished in ", "").split(" = ")[-1], "")
    run_text(["systemd-analyze", "time"], on_text)


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


def run_streaming_stdin(argv: list[str], data: str, on_line: Callable[[str], None],
                        on_exit: Callable[[int], None]) -> Optional[Gio.Subprocess]:
    """run_streaming(), and the tool may also read a secret from stdin.

    For the tools that prompt: `shani-fleet-agent enroll` does
    `read -rp "Enrollment token: "`, and there is no flag to answer it
    non-interactively. The prompt is written to stderr and the answer is read
    from stdin, so writing the answer to the child's stdin and leaving stderr
    merged into the same stream is what makes a GUI drive it.

    **The secret is written to stdin and never to argv**, which is the whole
    reason this exists rather than a shell string: argv is world-readable in
    /proc for the life of the process, and a token in it would be in every
    process listing on the machine for as long as the call ran.

    `data` is written once and stdin closed, so a tool that prompts twice gets
    EOF on the second rather than hanging forever on a pipe nobody will write
    to. Verified against a stand-in with the real agent's exact prompt shape.
    """
    try:
        proc = Gio.Subprocess.new(argv, Gio.SubprocessFlags.STDIN_PIPE
                                  | Gio.SubprocessFlags.STDOUT_PIPE
                                  | Gio.SubprocessFlags.STDERR_MERGE)
    except GLib.Error as e:
        on_line(e.message)
        GLib.idle_add(on_exit, 127)
        return None

    stdin = proc.get_stdin_pipe()

    def wrote(p, res):
        # A closed pipe is not a failure worth surfacing: the tool read what it
        # wanted and exited, which is the success case this exists to produce.
        try:
            p.close(None)
        except GLib.Error:
            pass

    # write_all_async, not write_all: the synchronous form returns
    # (ok, bytes_written) rather than taking a callback, and a blocking write on
    # the GTK main thread is the exact defect the rest of this module exists to
    # prevent.
    stdin.write_all_async(data.encode("utf-8"), GLib.PRIORITY_DEFAULT, None,
                          lambda _p, res: wrote(_p, res))

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


# --- reading shani-deploy's own progress output -----------------------------
#
# The deploy script writes everything to stderr and marks its phases with
# log_section, which is three lines: a rule, the phase name indented two spaces,
# and the rule again. Its own log lines are "<date> [TAG] message", with TAG one
# of INFO/DEBUG/SUCCESS/WARNING/ERROR/FATAL.
#
# So the phase a line belongs to is recoverable from the text alone, with no
# second channel and nothing added to the deploy script. That matters because
# the alternative - asking the script to emit machine-readable progress - is a
# change to a safety-critical file whose whole contract is that this app reads
# it. Parsed from a reproduction of the real log_section/log_* output, not from
# the shape it ought to have.

# The rule is 42 '=' in the script; matched by shape rather than by count so a
# cosmetic change to its width does not turn every phase into ordinary text.
_PHASE_LINE = re.compile(r"^={10,}\s*$")

# The phases a full deploy runs through, in the order main() calls them. Used to
# draw a progress bar, so a phase the script has not reached yet is drawn as
# pending rather than as failed. Anything not in this list is still shown as
# text: an unrecognised phase is a phase this list is stale about, and hiding
# it would be worse than drawing it at the end.
DEPLOY_PHASES: Final[tuple[str, ...]] = (
    "Boot Validation",
    "Update Check",
    "Disk Space Check",
    "Download Phase",
    "Deployment Phase",
    "Finalization",
)

# The rollback path logs its own single phase.
ROLLBACK_PHASES: Final[tuple[str, ...]] = ("System Rollback",)

_LEVELS: Final = {
    "INFO": "info",
    "DEBUG": "info",
    "STEP": "info",
    "SUCCESS": "success",
    "WARNING": "warning",
    "ERROR": "error",
    "FATAL": "error",
}

_LOG_LINE = re.compile(r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d \[(\w+)\] (.*)$")

# aria2c/wget/curl write a progress bar with \r, not \n, so it arrives as one
# long "line" whose last frame is the current one. Anything with a \r in it is a
# progress redraw rather than a message, and the page shows the last frame
# instead of appending hundreds of near-identical rows.
_PROGRESS = re.compile(r"(\d+(?:\.\d+)?)%")

# How long a coalesced "line" is allowed to grow before it is treated as junk
# rather than parsed. 64KiB is far past any real bar frame plus the log line
# that follows it, and far under a runaway.
_MAX_LINE = 65536


_LOG_PREFIX = re.compile(r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d \[[A-Z]+\] ")


def strip_log_prefix(text: str) -> str:
    """The message from one of the deploy script's own log lines.

    The prefix is "<date> [TAG] ", and a column of near-identical timestamps in
    a log pane is noise: the pane is a record of one run, so the date on every
    line tells the reader nothing they cannot see from the first one. Anything
    without the prefix is returned unchanged - a line the script did not write
    must not be edited to look as though it had.
    """
    return _LOG_PREFIX.sub("", text).strip()


def parse_deploy_line(line: str) -> list[tuple[str, str, str]]:
    """Everything in one line of shani-deploy output, as (kind, level, message).

    A **list**, because one "line" is not one event and that is not a detail:
    a downloader redraws its bar with `\\r` and no `\\n`, so a pipe hands over
    `#####  12% ...\\r#####  88% ...` followed by whatever the script logged next,
    all as a single string ending at the *next* newline. An earlier version of
    this function returned one event per line and classified that whole string
    as a progress redraw - which silently discarded every log line the tool
    printed during the download, and a missing log line reads as a tool that
    said nothing rather than as a reader that threw it away.

    kind is "phase", "level", "progress" or "text"; `level` is "" for the kinds
    that carry none. A pure function of its argument on purpose: the phase table
    and the format are both read from the deploy script's own source, and a test
    can hold this against a reproduction of that output without spawning
    anything.
    """
    if len(line) > _MAX_LINE:
        return []
    events: list[tuple[str, str, str]] = []
    if "\r" in line:
        # Split on the redraw character and treat each frame as its own line.
        # The last frame is the current one; every earlier one is superseded.
        frames = line.split("\r")
        for frame in frames[:-1]:
            events.extend(_one_event(frame))
        # The final frame is kept only when it is not the empty tail a trailing
        # \r leaves behind - `read_line_utf8` hands the \n-stripped remainder,
        # and a bar that ends on \r must not add a blank line to the log.
        last = frames[-1].strip()
        if last:
            events.extend(_one_event(last))
        return events
    return _one_event(line)


def _one_event(line: str) -> list[tuple[str, str, str]]:
    stripped = line.strip()
    if not stripped or _PHASE_LINE.match(stripped):
        return []
    match = _LOG_LINE.match(stripped)
    if match:
        tag, message = match.group(1), match.group(2).strip()
        return [("level", _LEVELS.get(tag, "info"), message)]
    # A phase name is the only line of the script's output that is a bare name
    # between two rules. Matched against the table rather than by its
    # indentation, because these lines reach the page already trimmed by the
    # reader and an indent-sensitive check would quietly stop matching - which
    # would leave the stage bar frozen on the first phase while the log looked
    # perfectly normal. An unrecognised bare name is text, and the page handles
    # that case explicitly rather than this function guessing.
    if stripped in DEPLOY_PHASES or stripped in ROLLBACK_PHASES:
        return [("phase", "", stripped)]
    if "\r" not in line:
        # A bar frame that reached _one_event without \r separators, e.g. the
        # last frame of a coalesced run. Recognised by the percentage so it does
        # not become a row of hashes in the log.
        matches = _PROGRESS.findall(stripped)
        if matches and stripped.lstrip("#").strip().startswith(matches[-1]):
            return [("progress", "", f"{matches[-1]}%")]
    return [("text", "", stripped)]


def deploy_backups(done) -> None:
    """shani-deploy --list-backups --json: {"ok", "slots": [{slot, version, backups}]}.

    Root: it mounts the subvolume table to read each slot's own
    /etc/shani-version, which is the only place a slot's version exists. That is
    also why a version cannot be folded into --status, and why this is a pkexec
    call the user must click for - never one that runs because a page opened.
    """
    run_json(["pkexec", DEPLOY, "--list-backups", "--json"], done)


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


# --- the System Info hardware and storage cards -------------------------------
#
# These used to be read inside tabs/system.py, which meant the parsing could
# not be tested without a real /proc and real tools on PATH. They live here so
# a fake-CLI test can drive them, like every other page's data source.
#
# One rule throughout, and it is the whole point: a reading that cannot be
# taken reports its own fallback and never raises into the caller. They were one
# try block, so a /proc/meminfo with no MemTotal line raised at the RAM row and
# the handler around the whole card then skipped battery, virtualisation and
# bluetooth, leaving three rows blank. A missing thermal zone is ordinary on a
# desktop and must not cost the reader the battery.

PROC_CPUINFO = "/proc/cpuinfo"
PROC_MEMINFO = "/proc/meminfo"
THERMAL_ZONE = "/sys/class/thermal/thermal_zone0/temp"
POWER_SUPPLY = "/sys/class/power_supply/BAT0"
HWMON_ROOT = "/sys/class/hwmon"


def _cpu_readings() -> tuple[str, str]:
    """Model and thread count, and whether the CPU says it can virtualise."""
    cpuinfo = _read_text(PROC_CPUINFO)
    model = next((ln.split(":", 1)[1].strip() for ln in cpuinfo.split("\n")
                  if "model name" in ln), "Unknown")
    threads = len([ln for ln in cpuinfo.split("\n") if ln.startswith("processor")])
    virt = ("VT-x/AMD-V available" if ("vmx" in cpuinfo or "svm" in cpuinfo)
            else "VT-x/AMD-V not available")
    return f"{model} ({threads} threads)", virt


def _cpu_temp() -> str:
    return f"{int(_read_text(THERMAL_ZONE).strip()) / 1000:.0f}°C"


def _parse_gpu(out: str) -> str:
    lines = [ln for ln in out.split("\n") if "VGA" in ln or "3D" in ln]
    return lines[0].split(":")[2].strip() if lines else "Unknown"


def _ram() -> str:
    kb: dict[str, int] = {}
    for line in _read_text(PROC_MEMINFO).split("\n"):
        if ":" in line:
            key, _, rest = line.partition(":")
            kb[key.strip()] = int(rest.split()[0])
    total = kb["MemTotal"] // 1024
    return f"{total} MB ({total - kb.get('MemAvailable', kb['MemTotal']) // 1024} MB used)"


def _battery() -> str:
    # _read_text answers "" for a file it could not open, so an absent BAT0
    # would otherwise render as "% ()" - a battery row that looks answered.
    # Raising is what lets the caller's fallback say N/A instead.
    capacity = _read_text(POWER_SUPPLY + "/capacity").strip()
    status = _read_text(POWER_SUPPLY + "/status").strip()
    if not capacity:
        raise OSError(f"no battery at {POWER_SUPPLY}")
    return f"{capacity}% ({status})" if status else f"{capacity}%"


def _parse_bluetooth(out: str) -> str:
    return "● Active" if "Powered: yes" in out else "○ Inactive"


def _parse_df(out: str) -> str:
    lines = out.strip().split("\n")
    if len(lines) < 2:
        return ""
    parts = lines[1].split()
    if len(parts) < 6:
        return ""
    return f"{parts[2]}/{parts[1]}"


def _parse_du(out: str) -> str:
    fields = out.split()
    return fields[0] if fields else ""


def _parse_free(out: str) -> str:
    for line in out.strip().split("\n"):
        if line.startswith("Swap"):
            parts = line.split()
            if len(parts) >= 4:
                return f"{parts[2]} used / {parts[1]} total"
    return ""


def _gather(*rows: tuple, done: Callable[[dict], None]) -> None:
    """Fan a card's tool reads out over run_text(), then call done once.

    Each positional row is (row_keys, argv, parse, fallback). `row_keys` is one
    key or a tuple of keys sharing a single read, because `storage-root` and
    `storage-root-usage` are both `df -h /` and spawning the tool twice for one
    answer is a cost with no information in it.

    done is called once, with every key present, so a caller still sees a whole
    card. A tool that is absent, exits badly or prints nothing a parser can use
    sets only its own keys to their fallback - one source is not the card's
    failure, and the async shape is exactly where a shared handler could
    quietly reintroduce that.
    """
    out: dict = {}
    left = len(rows)

    def report(keys, value, fallback):
        nonlocal left
        for key in keys:
            out[key] = value or fallback
        left -= 1
        if left == 0:
            done(out)

    for keys, argv, parse, fallback in rows:
        def finish(text, err, _keys=keys, _parse=parse, _fb=fallback, _argv=argv):
            if text is None:
                logger.debug("%s: %s", _argv[0], err)
            report(_keys, _parse(text) if text else "", _fb)
        run_text(argv, finish)


def power_profile(done: Callable[[str], None]) -> None:
    """The active power profile and the driver actually behind it, or N/A.

    powerprofilesctl ships and is enabled by shani-desktop-gnome, and nothing
    in Cassini read it, so a machine whose daemon was running - and quietly
    holding itself to power-saver - said so nowhere in the UI.

    `list` answers both halves in one call: the block prefixed with `*` is the
    active profile, and the CpuDriver/PlatformDriver lines under it name what is
    moving. Since 0.22 those are independent drivers, so the profile name alone
    no longer says whether the CPU governor or the platform profile is the
    thing that changed.

    `get` is asked alongside it because that is the documented way to read the
    active profile and does not depend on the `*` marker surviving a format
    change; `list` is only trusted for the driver names on top of it.

    Nothing here writes. Switching a profile is a state change on the running
    machine, so it belongs behind an explicit action in the page, not in a
    reader that runs on every refresh.
    """
    out: dict = {}

    def finish() -> None:
        profile = out.get("get") or ""
        if not profile:
            done("N/A")
            return
        drivers = out.get("drivers", "")
        done(f"{profile} ({drivers})" if drivers else profile)

    def got_list(text: Optional[str], err: str) -> None:
        if text is None:
            logger.debug("powerprofilesctl list: %s", err)
        out["drivers"] = _parse_power_drivers(text or "", profile=out.get("get", ""))
        finish()

    def got_get(text: Optional[str], err: str) -> None:
        if text is None:
            logger.debug("powerprofilesctl get: %s", err)
        out["get"] = (text or "").strip()
        run_text(["powerprofilesctl", "list"], got_list)

    run_text(["powerprofilesctl", "get"], got_get)


def _parse_power_drivers(out: str, *, profile: str) -> str:
    """Driver names from the `powerprofilesctl list` block for `profile`.

    Only the active block is read: listing every profile's drivers would put
    "intel_pstate, platform_profile" on the row whether or not that is what is
    driving the profile in force, which is the one thing the row is for.

    The block is found first and then read forward, because the active profile
    is usually *not* last in the output - `powerprofilesctl` prints them in
    power-saver, balanced, performance order and marks the active one with `*`.
    Resetting a running block on every header instead makes the parse succeed
    for whichever profile happens to come last and silently return nothing for
    the one in force, which is the only one that matters.
    """
    lines = out.split("\n")
    start = next((i for i, line in enumerate(lines)
                  if line.strip().lstrip("* ").strip() == f"{profile}:"), None)
    if start is None:
        return ""

    block = []
    for line in lines[start + 1:]:
        name = line.strip().lstrip("* ").strip()
        if name.endswith(":"):  # the next profile's header ends this block
            break
        # `Degraded: no` is a state flag, not a driver, and listing it beside
        # CpuDriver would report a boolean as if it named something driving the
        # profile. Everything else in the block is a driver line.
        if ":" in line and name.split(":", 1)[0].strip() not in ("Degraded",):
            block.append(line.strip())
    if not block:
        return ""
    return ", ".join(dict.fromkeys(b.split(":", 1)[0].strip() for b in block))


def sensors_card(done: Callable[[list], None]) -> None:
    """Every hwmon temperature and fan reading, as (label, value) rows.

    hwmon is the kernel's real sensor interface and is what lm-sensors itself
    reads. Cassini had no reader for it at all, so on a laptop the fan speeds
    and the per-core temperatures were simply not on screen anywhere, and the
    one temperature that was shown came from thermal_zone0 - a different driver,
    on a different machine often absent entirely.

    There is no fixed set of chips to look for: this host exposes 7 and the set
    is per-machine and per-driver, so the rows are whatever the machine really
    reports rather than a hardcoded list that would be wrong on most of them.

    A reading of 0 or less is dropped rather than shown. The ThinkPad driver
    keeps unpopulated inputs wired to 0 (temp4..temp7 on this machine) and the
    kernel reports unavailable sensors as a large negative, so both would add
    rows that look like hardware facts and are not.
    """
    rows: list[tuple[str, str]] = []
    try:
        chips = sorted(os.listdir(HWMON_ROOT))
    except OSError as err:
        logger.debug("hwmon: %s", err)
        done(rows)
        return

    for chip in chips:
        base = os.path.join(HWMON_ROOT, chip)
        if not os.path.isdir(base):
            continue
        name = _read_text(os.path.join(base, "name")).strip() or chip
        try:
            entries = os.listdir(base)
        except OSError:
            continue
        for kind, unit, divisor, word in (("temp", "°C", 1000.0, "Temp"),
                                          ("fan", " RPM", 1.0, "Fan")):
            for entry in sorted(entries):
                matched = re.fullmatch(rf"{kind}(\d+)_input", entry)
                if not matched:
                    continue
                raw = _read_text(os.path.join(base, entry)).strip()
                if not raw:
                    continue
                try:
                    value = int(raw)
                except ValueError:
                    continue
                if value <= 0:
                    continue
                label = _read_text(
                    os.path.join(base, f"{kind}{matched.group(1)}_label")).strip()
                name_suffix = label or f"{word} {matched.group(1)}"
                rows.append((f"{name} {name_suffix}",
                             f"{value / divisor:.0f}{unit}"))
    done(rows)


def hardware_card(done: Callable[[dict], None]) -> None:
    """Every hardware reading, each with its own fallback.

    done receives {row_name: text}; a source that could not be read is already
    carrying that row's fallback, so a caller never has to catch anything and a
    failure can never take out a row it did not belong to.

    The tool-backed rows go through _gather because this card is built while
    notebook.py is building the page, on the GTK main thread; a synchronous
    `lspci` here froze the whole window. The /proc and /sys rows are file reads
    that answer or fail in microseconds, so they stay inline.
    """
    out: dict = {}
    try:
        out["hw-cpu"], out["hw-virt"] = _cpu_readings()
    except Exception:  # noqa: BLE001 - one source is not the card's failure
        out["hw-cpu"] = out["hw-virt"] = "Unknown"
    for name, read, fallback in (("hw-cpu-temp", _cpu_temp, "N/A"),
                                 ("hw-ram", _ram, "N/A"),
                                 ("hw-battery", _battery, "N/A")):
        try:
            out[name] = read()
        except Exception:  # noqa: BLE001 - one source is not the card's failure
            out[name] = fallback

    def finished(tool_rows: dict) -> None:
        out.update(tool_rows)
        arrived()

    def got_profile(text: str) -> None:
        out["hw-power-profile"] = text
        arrived()

    # Two sources, one card. This cannot hang because power_profile() answers
    # exactly once, N/A included.
    left = 2

    def arrived() -> None:
        nonlocal left
        left -= 1
        if left == 0:
            done(out)

    _gather((("hw-gpu",), ["lspci"], _parse_gpu, "Unknown"),
            (("hw-bluetooth",), ["bluetoothctl", "show"], _parse_bluetooth, "○ Inactive"),
            done=finished)
    power_profile(got_profile)


def storage_card(done: Callable[[dict], None]) -> None:
    """The storage card's six rows, same contract as hardware_card().

    `du -sh /var/log` carries a 30s cap because it walks a directory tree, and
    it was the longest freeze this page could hand a user: every one of these
    reads ran synchronously while the page was being built.
    """
    _gather((("storage-root-usage", "storage-root"), ["df", "-h", "/"], _parse_df, "N/A"),
            (("storage-home-usage",), ["df", "-h", "/home"], _parse_df, "N/A"),
            (("storage-var-usage",), ["df", "-h", "/var"], _parse_df, "N/A"),
            (("storage-varlog",), ["du", "-sh", "/var/log"], _parse_du, "N/A"),
            (("storage-swap",), ["free", "-h"], _parse_free, "N/A"),
            done=done)


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


def tpm2_present(done: Callable[[Optional[bool], str], None]) -> None:
    """systemd-analyze has-tpm2: exit 0 = usable TPM2 (no root needed).

    True and False both come from the exit status, and None means the question
    could not be asked -- tool absent, or it would not start. None is not
    "this machine has no TPM": reporting that would tell a user with a working
    chip to go poke their firmware because the probe itself failed.
    """
    run_status(["systemd-analyze", "has-tpm2", "-q"],
               lambda status, err: done(None if status is None else status == 0, err))


def tpm2_status(done) -> None:
    """gen-efi tpm2-status --json (root: it reads the LUKS header)."""
    run_json(["pkexec", "gen-efi", "tpm2-status", "--json"], done)


# --- systemd's PCR separator, and what it does to an existing seal ---------
#
# systemd 261 ships systemd-pcrosseparator.service, and Arch's mkinitcpio 42-1
# began including it in the systemd initrd hook. It extends a PCR's measured
# value with a separator entry, so a seal bound to one of those PCRs records a
# value that will never recur. Arch's own advice for a machine caught by this is
# to re-enrol the TPM2 key.
#
# Two facts this deliberately does NOT claim:
#
#   * Whether an enrolment is stale. The LUKS2 header stores no enrolment date,
#     systemd-cryptenroll has no --list and no dry-run, and asking the policy
#     whether it still unseals means unsealing the key. So this reports the
#     configuration that the change affects, and the caller must phrase it as a
#     conditional rather than a diagnosis.
#   * Which PCRs the key is bound to. gen-efi stores that in a systemd-tpm2
#     token, but not in the syntax that wrote it: --tpm2-pcrs takes them
#     '+'-separated ("0+7") and `cryptsetup luksDump` prints the result as
#     "tpm2-pcrs:" TAB <integer bitmask> -- verbatim, from shani-deploy's own
#     test fixture, `tpm2-pcrs:\t7`. Neither the flag's text nor a PCR list,
#     so it has to be bit-decoded, and a decode that comes out empty reads as
#     "no risk" on exactly the machines at risk. The policy is therefore
#     derived from gen-efi's own rule in shani-deploy rather than parsed out
#     of the token.

PCR_SEPARATOR_UNIT: Final = "/usr/lib/systemd/system/systemd-pcrosseparator.service"

# What the separator measures, per systemd's own documentation of the unit.
SEPARATOR_PCRS: Final = frozenset({0, 1, 2, 3, 4, 5, 6, 7, 9, 12, 13, 14})


def pcr_separator_measured() -> bool:
    """Whether this system has the PCR separator systemd 261 introduced.

    Tested by the unit file, not by running the unit: the question is what is
    installed, and starting a service is a state change this read-only page has
    no business making. Present exactly when systemd is new enough to ship it
    and enabled it in sysinit.target.wants, which is the same answer for a
    machine that cannot be affected (systemd 255) as "no".

    This is a proxy, and the error is deliberately one-sided. The unit file
    proves systemd is 261+; it does not prove the initrd on disk was rebuilt by
    an mkinitcpio new enough to include the unit, so a machine that upgraded
    systemd but not its initrd can be warned unnecessarily. That is the cheap
    direction: the row advises re-running a setup that gen-efi already offers,
    and a *missed* warning means a disk that silently stopped unlocking by
    itself with nothing in the UI to explain it.
    """
    return os.path.exists(PCR_SEPARATOR_UNIT)


def shani_tpm2_pcr_policy(secure_boot: bool) -> frozenset[int]:
    """The PCRs gen-efi's enroll-tpm2 seals against, as gen-efi itself decides.

    shani-deploy/scripts/gen-efi.sh pins "0+7" when Secure Boot is on and "0"
    when it is off. Derived rather than read back out of the LUKS2 token, for
    the array-vs-plus-separated reason documented above.
    """
    return frozenset({0, 7} if secure_boot else {0})


def tpm2_seal_risk(status: dict) -> str:
    """Why a re-enrolment may be needed, or "" when it cannot be.

    Empty is the honest answer for a disk with no TPM2 key, for a systemd too
    old to have the separator, and for a seal bound to none of the affected
    PCRs. What is never returned is a claim that the seal IS stale: nothing
    read-only can establish that, so this names the risk and lets the page's
    existing "Set up again" action be the remedy.
    """
    if not status.get("tpm2_enrolled") or not pcr_separator_measured():
        return ""
    bound = shani_tpm2_pcr_policy(bool(status.get("secure_boot")))
    affected = sorted(bound & SEPARATOR_PCRS)
    if not affected:
        return ""
    pcrs = ", ".join(str(p) for p in affected)
    return (f"This system's firmware measurements changed: systemd now measures a "
            f"separator into PCR {pcrs}, which this key is bound to. If the disk "
            f"stops unlocking by itself, set automatic unlock up again to record "
            f"the new measurements. Your passphrase is unaffected either way.")


# --- running a tool that lives in an sbin directory -----------------------
#
# On Arch `btrfs`, `ausearch` and `smartctl` install into /usr/sbin, which a
# desktop session's PATH leaves out, so have() - and therefore run_json() -
# calls an installed tool "not installed" on a perfectly working machine.
# have_sbin() has always known this, and one page solved it with a private
# helper; this is that helper, shared, so the next page does not grow its own
# copy. Two things are needed, not one: resolving the name, and then invoking
# the resolved path, because a bare argv[0] that which() cannot find would
# also fail to spawn. Presence without the path is the half-fix that still
# shows an empty page.
#
# run_json, run_json_lines, have and have_sbin are left exactly as they are:
# they are the contract every existing page and its tests already depend on.
# SBIN_DIRS, the directory list searched here, is defined further down with the
# fprintd constants - this section is where the missing-sbin-PATH problem was
# first met. This block also sits above that section on purpose: everything
# after FPRINTD_CLI is asserted to spawn no process at all.


def _tool_path(cmd: str) -> Optional[str]:
    """The absolute path of cmd, from PATH or the sbin directories, or None.

    shutil.which() first, because PATH is where an override belongs - a user
    or an image that shadows a tool must keep winning. The sbin fallback
    mirrors have_sbin()'s search, and reuses SBIN_DIRS so a test can point it
    at a temp directory.
    """
    found = shutil.which(cmd)
    if found is not None:
        return found
    base = os.path.basename(cmd)
    for directory in SBIN_DIRS:
        candidate = os.path.join(directory, base)
        if os.access(candidate, os.X_OK):
            return candidate
    return None


def tool_path_or_self(cmd: str) -> str:
    """The path to run cmd with, or cmd itself when it is nowhere to be found.

    _tool_path() answers "where is it, if anywhere", which is the right
    question for have_tool() and wrong for a caller that is about to build
    argv: an absent tool must still be executed, so the failure is the tool's
    own real error rather than the page deciding in advance that the tool is
    missing. Firewall needed exactly that and grew a private copy of the
    search to get it; this is that copy, shared.
    """
    return _tool_path(cmd) or cmd


def have_tool(cmd: str) -> bool:
    """Is cmd runnable at all, counting /usr/sbin and /usr/local/sbin?

    Prefer this over have() for any tool a package may have installed as root.
    have() answers "is it on this session's PATH", which on a normal desktop
    session is a fact about PATH, not about the machine - and reporting a
    working sbin tool as missing is the one failure a system manager must not
    make, because the page then claims a healthy machine is broken.
    """
    return _tool_path(cmd) is not None


def _json_failure_reason(argv: list[str], status: int, out: str, err: str) -> str:
    """What run_json-style callers are told when stdout held no JSON.

    Split out so a second runner can report a failure in exactly run_json's
    words. run_json keeps its own inline copy of this logic rather than calling
    in here: it is the function every existing page already runs, and this
    change is additive on purpose. The two must not drift - if run_json's
    wording changes, change this with it.
    """
    text = _strip_ansi(err or out or f"exit status {status}").strip()
    logger.warning("%s: rc=%s, no JSON: %.200s", argv, status, text)
    if "Invalid option" in text or "invalid option" in text:
        # e.g. shani-deploy older than --status: the image's tools are
        # behind this app, not a broken system
        return "This system's tools are older than Shani Cassini - update Shanios to see this"
    lines = text.splitlines()
    return re.sub(r"^\S+ \S+ \[\w+\]\s*", "", lines[-1]) if lines else f"exit status {status}"


def run_json_tool(argv: list[str], done: Callable[[Optional[dict], str], None]) -> None:
    """run_json() for a tool that may be sbin-only; see have_tool().

    Behaves as run_json() does in every observable way - same
    done(payload_or_None, error) shape, same "<name> is not installed" wording,
    same pkexec 126/127 "Authorization was cancelled", same "JSON on stdout
    wins over the exit status" - and differs in exactly one respect: the name
    is resolved through the sbin directories and the binary is spawned by its
    absolute path. Everything that can go wrong here arrives as a done() value
    and never as an exception, because a raising callback leaves a GTK page
    blank and says nothing at all about why.
    """
    path = _tool_path(argv[0])
    if path is None:
        GLib.idle_add(done, None, f"{argv[0]} is not installed")
        return
    try:
        proc = Gio.Subprocess.new([path, *argv[1:]],
                                  Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_PIPE)
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
        # keyed on the caller's argv, not the resolved path, so a pkexec run
        # that is missing an sbin tool still reports a cancelled dialog rather
        # than a raw exit status
        if argv[0] == "pkexec" and status in (126, 127):
            done(None, "Authorization was cancelled")
            return
        try:
            done(json.loads(out or ""), "")
            return
        except ValueError:
            pass
        done(None, _json_failure_reason(argv, status, out or "", err or ""))

    proc.communicate_utf8_async(None, None, finish)


STREAM_BOUNDS: Final[dict[str, int]] = {
    # `lxc` is the LXD client. It answers by talking to lxd.socket, and when that
    # socket never replies the command does not fail - it waits. Measured in a
    # real ShaniOS slot: unbounded, past seven minutes; under `timeout 20`, exit
    # 124. Gio.Subprocess reports nothing until the child exits, so an unbounded
    # read leaves the calling page pending for ever with no way back.
    "lxc": 20,
}


def run_stream_tool(argv: list[str], on_line: Callable[[str], None],
                    on_exit: Callable[[int], None]) -> Optional[Gio.Subprocess]:
    """run_streaming() for a tool that may be sbin-only; see have_tool().

    Line-by-line output is what a long privileged read wants, so a tool that
    installs into /usr/sbin has to be runnable through this too. An absent
    tool is reported the way run_streaming() reports a failed spawn - the
    message on on_line, then 127 on on_exit - so a page needs no separate
    "not installed" branch, and None comes back because there is nothing to
    cancel.

    A tool named in STREAM_BOUNDS is additionally stopped after that many
    seconds. The bound is enforced here rather than in a page because the pages'
    own gates forbid it: each asserts "timeout_add" not in its own source, so a
    page that armed a timer would fail its own test. Putting it in the runner
    also means a caller cannot forget to pass one.
    """
    path = _tool_path(argv[0])
    if path is None:
        on_line(f"{argv[0]} is not installed")
        GLib.idle_add(on_exit, 127)
        return None
    bound = STREAM_BOUNDS.get(argv[0])
    if bound is None:
        return run_streaming([path, *argv[1:]], on_line, on_exit)

    source = 0

    def settled(status: int) -> None:
        nonlocal source
        if source:
            GLib.source_remove(source)
            source = 0
        on_exit(status)

    def expire() -> bool:
        nonlocal source
        source = 0
        on_line(f"{argv[0]} did not answer within {bound}s and was stopped, so "
                "nothing is claimed here")
        if proc is not None:
            proc.force_exit()
        return False

    proc = run_streaming([path, *argv[1:]], on_line, settled)
    source = GLib.timeout_add_seconds(bound, expire)
    return proc


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
                        "scan_type": "", "num_enroll_stages": None, "fingers": [],
                        "device_count": 0})
                return
            _fprintd_device(conn, paths[0], finish, len(paths))
        _dbus_call(conn, FPRINTD_PATH, FPRINTD_MANAGER, "GetDevices", [], devices)

    _system_bus(status_step)


def _fprintd_device(conn, path: str, finish, count: int = 1) -> None:
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
                    finish(_status(path, values, [], count))
                    return
                finish(None, f"fprintd did not answer: {e}")
                return
            finish(_status(path, values, [str(x) for x in (raw2[0] if raw2 else [])], count))
        _dbus_call(conn, path, FPRINTD_DEVICE, "ListEnrolledFingers",
                   [_s(FPRINTD_SELF_USER)], fingers)
    _dbus_call(conn, path, FPRINTD_PROPERTIES, "GetAll", [_s(FPRINTD_DEVICE)], props)


def _status(path: str, values: dict, fingers: list, count: int = 1) -> dict:
    stages = values.get("num-enroll-stages")
    return {"daemon": True,
            "device_present": True,
            "path": path,
            "name": str(values.get("name") or ""),
            "scan_type": str(values.get("scan-type") or ""),
            "num_enroll_stages": int(stages) if isinstance(stages, int) else None,
            "fingers": fingers,
            "device_count": count}


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

# --- storage ------------------------------------------------------------
# shani-health --storage-info --json is the only storage interface we have, and
# its shape is not what the flag name suggests. Everything below is written
# against output captured from a real Btrfs Shanios layout, not from the docs.
#
# The four things a parser here must not assume, all confirmed by reading the
# captured file rather than the help text:
#
#   * `section` is "" for every check. analyze_storage never calls
#     _set_section, so there is nothing to group rows by.
#   * `key` is NOT unique - "bees" appears twice, once from the dedup check and
#     once from the reclaim-hint check - so it cannot be used as an identifier.
#   * sizes are pre-formatted human strings in `message`, not numbers:
#     "960K (ratio: 16M)", where that second figure is the UNCOMPRESSED size,
#     not a compression ratio. Total/Used are likewise strings straight out of
#     `btrfs filesystem usage`, e.g. "12.00GiB".
#   * the JSON is assembled by string concatenation (_print_json), not jq, and
#     _json_escape only escapes backslash and double-quote - a newline inside
#     any message produces malformed JSON. So a parse failure is reported, not
#     papered over.

STORAGE_INFO_KEYS = ("Free", "Total", "Used", "Snapshots", "Quotas", "Scrub",
                     "Scrub tmr", "Maint tmrs", "bees", "Dev errors", "Dedup")


def _storage_size(message: str) -> dict:
    """Pull the numbers back out of a human-formatted size string.

    Returns {} rather than guessing when the string is not the shape we know,
    so a caller can say "not reported" instead of showing a wrong figure.
    """
    out: dict = {}
    text = message.strip()
    if not text:
        return out
    head = text.split(" (ratio:", 1)[0].strip()
    out["used"] = head
    if " (ratio:" in text:
        out["uncompressed"] = text.split(" (ratio:", 1)[1].rstrip(")").strip()
    return out


def storage_info(done: Callable[[dict], None]) -> None:
    """Parse `shani-health --storage-info --json` into rows a page can render.

    done receives {"ok", "problem", "summary", "subvolumes", "warnings",
    "timestamp"}. Never raises and never calls back with an exception: a missing
    binary, a non-zero exit or unparseable JSON all arrive as ok=False with a
    reason, because a page that raises during build renders blank and says
    nothing. --storage-info exits 0 on success; run_json reads the JSON from
    stdout regardless of exit status, which is what the "JSON even on exit 1"
    contract for the other modes relies on too.
    """
    empty = {"ok": False, "problem": "", "summary": {}, "subvolumes": [],
             "warnings": [], "timestamp": ""}

    def finish(payload: Optional[dict], error: str) -> None:
        if payload is None:
            done({**empty, "problem": error or "shani-health did not answer"})
            return
        checks = payload.get("checks")
        if not isinstance(checks, list):
            done({**empty, "problem": "shani-health --storage-info --json has no "
                                      "checks list"})
            return
        result = {**empty, "ok": True, "problem": "",
                  "timestamp": str(payload.get("timestamp") or "")}
        for check in checks:
            if not isinstance(check, dict):
                continue
            key = str(check.get("key") or "")
            status = str(check.get("status") or "")
            message = str(check.get("message") or "")
            if key.startswith("@"):
                result["subvolumes"].append({"name": key, "status": status,
                                             **_storage_size(message)})
            elif key in STORAGE_INFO_KEYS:
                result["summary"][key] = {"status": status,
                                          "message": message.strip(),
                                          **_storage_size(message)}
                if status in ("warning", "critical", "fail"):
                    result["warnings"].append({"key": key, "status": status,
                                               "message": message.strip()})
        done(result)

    run_json(["shani-health", "--storage-info", "--json"], finish)


# ---------------------------------------------------------------------------
# Interfaces with no GUI in GNOME Control Center or KDE System Settings
# ---------------------------------------------------------------------------
#
# Every reader here is read-only, collects through run_json/run_text/run_status,
# and reports what the tool said rather than interpreting it. They are grouped
# here because they were added for one reason - the desktop settings apps have
# no panel for them - and that reason is worth keeping in one place: if one of
# them ever grows a GUI elsewhere, this is the list to revisit.
#
# Two of these tools live in /usr/sbin (aa-status, fwupdmgr) and one in
# /usr/bin, and the sbin trap has already cost this repo a page once.


# --- cron: the schedules systemd timers do not cover ----------------------
#
# `crontab -l` **exits 1 with empty stdout** when the account has no crontab,
# and says "no crontab for <user>" on stderr. run_text's contract is that empty
# stdout is a failure, which is right for a tool that should have said
# something - so this cannot use it naively, and the distinction is load-bearing:
# "you have no crontab" is an answer, and reporting it as an error would put a
# failure on the page of every account that has never scheduled anything.

CRON_SPOOL: Final = "/var/spool/cron/crontabs"
CRON_D: Final = "/etc/cron.d"
CRON_USER_D: Final = "/etc/cron.daily"


def cron_service_status(done: Callable[[Optional[bool], str], None]) -> None:
    """Is the cron daemon actually running?

    `systemctl is-active cron` answers 0 and prints "active", and exits
    **non-zero while inactive** while still printing the word - which is exactly
    the case run_text was built to keep (see its note on systemd-analyze time).
    So the answer is the text, and the exit status is not consulted.
    """
    def on_text(text: Optional[str], err: str) -> None:
        if text is None:
            done(None, err)
            return
        state = text.strip().lower()
        if state in ("active", "activating"):
            done(True, "")
        elif state in ("inactive", "failed", "deactivating"):
            done(False, "")
        else:
            done(None, f"cron is {state}" if state else err)
    run_text(["systemctl", "is-active", "cron"], on_text)


def user_crontab(done: Callable[[list[str], str], None]) -> None:
    """The calling user's own crontab lines, or [] when they have none.

    The *calling user's*, not root's and not a scan of the spool: reading other
    people's schedules is not this app's business, and `crontab -l` with no `-u`
    already means "mine". An account with no crontab is handed [] with no error,
    because it is the single most common state on a desktop and the page must
    say "you have no scheduled jobs" rather than failing.
    """
    def on_text(text: Optional[str], err: str) -> None:
        if text is None:
            # run_text's "said nothing" wording is cron's own
            # "no crontab for <user>", and that is a real answer, not a failure.
            lowered = err.lower()
            if "no crontab for" in lowered:
                done([], "")
                return
            done([], err)
            return
        done([line for line in text.splitlines() if line.strip()], "")

    argv = ["crontab", "-l"]
    run_text(argv, on_text)


def _cron_entries_in(directory: str) -> list[dict]:
    """Scheduled files in one cron directory, read directly rather than by tool.

    /etc/cron.d and /etc/cron.{hourly,daily,weekly,monthly} are plain files
    with no query tool for them - `crontab -l` only ever means the calling
    user's table. So the directory is read, which is also the only way to see
    the *system* schedules at all.

    A file that cannot be read is skipped rather than reported: /etc/cron.d
    holds files for packages that may have been removed, and one unreadable
    entry must not blank a list of a dozen working ones.
    """
    out: list[dict] = []
    try:
        names = sorted(os.listdir(directory))
    except OSError:
        return out
    for name in names:
        # cron ignores dotfiles and names containing anything but the safe set;
        # listing one as a schedule would be reporting a file cron will not run.
        if name.startswith(".") or not re.fullmatch(r"[A-Za-z0-9_.-]+", name):
            continue
        path = os.path.join(directory, name)
        if os.path.isdir(path):
            continue
        try:
            with open(path, encoding="utf-8", errors="replace") as handle:
                body = handle.read()
        except OSError:
            continue
        if not body.strip():
            continue
        # The file name is the schedule for the run-part directories, and the
        # contents are the job for /etc/cron.d. Both are shown, neither guessed.
        # A /etc/cron.d file *carries* its own schedule on each line, while a
        # run-part file is named for the **directory it is in**: /etc/cron.daily/
        # logrotate runs daily, and the schedule is "daily", not "logrotate".
        # The first version put the file's own name in the schedule column,
        # which rendered every run-part job as a job named after itself.
        schedule = "" if directory.endswith("cron.d") else \
            os.path.basename(directory).removeprefix("cron.")
        out.append({"name": name, "schedule": schedule,
                    "command": _cron_first_job(body), "body": body.strip()})
    return out


# A crontab's leading `NAME=value` lines set the job's environment; they are not
# the job. A real /etc/cron.d/anacron is nine lines of SHELL=/PATH=/START= and
# only then a schedule, so taking the first non-comment line names the *shell*
# as the command on every correctly-written file.
_CRON_ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\s*=")


def _cron_first_job(body: str) -> str:
    """The first line of a crontab file that is actually a scheduled job."""
    for line in body.splitlines():
        text = line.strip()
        if not text or text.startswith("#"):
            continue
        if _CRON_ASSIGN.match(text):
            continue
        return text
    return ""


def cron_system_jobs(done: Callable[[list[dict], str], None]) -> None:
    """Every system-wide schedule: /etc/cron.d and the four run-part dirs.

    Read from the filesystem, so this one answers with no tool and no privilege,
    and unlike the other readers on this page it cannot fail - an absent
    directory is a machine with no system crontabs, not an error.
    """
    entries: list[dict] = []
    entries += _cron_entries_in(CRON_D)
    for suffix in ("hourly", "daily", "weekly", "monthly"):
        entries += _cron_entries_in(f"{CRON_USER_D}.{suffix}")
    done(entries, "")


# --- AppArmor: profiles, which no settings app lists ------------------------
#
# aa-status **needs root** and exits 4 without it, having printed the module
# line but no profiles. So this is a pkexec read: a password prompt behind a
# button, never on page load, for the same reason --list-backups is.
#
# aa-status has no JSON. Its output is a human summary, so the parser below
# takes the counts from the tool's own wording rather than inventing structure.

def apparmor_status(done: Callable[[dict, str], None]) -> None:
    """Loaded / enforce / complain profile counts, as aa-status counts them.

    Shape like storage_info(): a dict that is always safe to render. `ok=False`
    means the *read* did not happen, which is different from "the module is not
    enabled" - and the page has to keep those apart, because a user whose
    AppArmor is genuinely off and a user whose prompt was dismissed both
    otherwise end up looking like the same machine.
    """
    empty = {"ok": False, "problem": "", "module_loaded": False,
             "loaded": 0, "enforce": 0, "complain": 0, "unconfined": None}

    # done(payload, error) - the two-argument shape every reader in this module
    # uses. aa-status prints prose, so there is no JSON to parse with run_json
    # and the raw text is handed to a parser instead.
    run_text(["pkexec", tool_path_or_self("aa-status")],
             lambda text, err: done(_parse_aa_status(text, err), err))


def _parse_aa_status(text: Optional[str], error: str) -> dict:
    """aa-status's own summary text into the counts it prints.

    Verbatim shape from AppArmor 3.x/4.x:

        apparmor module is loaded.
        42 profiles are loaded.
        40 profiles are in enforce mode.
         2 profiles are in complain mode.
         0 unconfined processes.

    Parsed by number-in-sentence rather than by fixed line order, because the
    lines differ between apparmor-parser versions (3.x prints "N unconfined
    processes", 4.x prints the process table instead) and a line-index parser
    silently reports 0 for a machine with profiles. **A count that is absent is
    left at 0 and `unconfined` at None** - never inferred from another line.
    """
    out = {"ok": False, "problem": "", "module_loaded": False,
           "loaded": 0, "enforce": 0, "complain": 0, "unconfined": None}
    if not text:
        # Without root aa-status prints only the module line and exits 4. That
        # is a refusal to answer, not a machine with no profiles.
        out["problem"] = error or "aa-status did not answer"
        return out
    body = _strip_ansi(text)
    out["module_loaded"] = "apparmor module is loaded" in body
    # Checked BEFORE the counts, because this is the shape aa-status prints
    # without root: the module line and then a refusal, with no numbers at all.
    # Falling through to the count parser reported that as "the module is loaded
    # but printed no profile counts this build understands" - which blames this
    # parser for the tool having refused, and sends the reader to look for a
    # format bug that is not there.
    #
    # The wording matched is aa-status's own: "You do not have enough privilege
    # to read the profile set." An earlier version tested for "not enough
    # privilege", which **is not a substring of that sentence** - it says "do
    # not have enough" - so the refusal went undetected while the test that
    # claimed to cover it passed. The needle is the tool's exact phrase.
    if "do not have enough privilege" in body.lower():
        out["problem"] = "aa-status needs an administrator password"
        return out
    patterns = (
        ("loaded", r"(\d+)\s+profiles?\s+are\s+loaded"),
        ("enforce", r"(\d+)\s+profiles?\s+are\s+in\s+enforce"),
        ("complain", r"(\d+)\s+profiles?\s+are\s+in\s+complain"),
    )
    found = False
    for key, pattern in patterns:
        match = re.search(pattern, body)
        if match:
            out[key] = int(match.group(1))
            found = True
    unconf = re.search(r"(\d+)\s+unconfined", body)
    if unconf:
        out["unconfined"] = int(unconf.group(1))
        found = True
    if not found:
        # The module is loaded but no profile line matched: this is a parser
        # that is out of date, and saying so beats reporting zero profiles on a
        # machine that has them.
        out["problem"] = ("aa-status said the module is loaded but printed no "
                          "profile counts this build understands")
        return out
    out["ok"] = True
    return out


def apparmor_profiles(done: Callable[[dict, str], None]) -> None:
    """The profile names aa-status lists, in enforce/complain order.

    Two lines out of the same tool's output, parsed from the same read as the
    counts rather than by a second privileged call: `aa-status` prints

        Profiles:
          Enforcement mode
            /usr/bin/foo// null
          complain mode
            /usr/bin/bar// null

    and re-running it to get this would put a second password prompt behind the
    same button.
    """
    def on_text(text: Optional[str], err: str) -> None:
        done(_parse_aa_profiles(text, err), err)

    run_text(["pkexec", tool_path_or_self("aa-status")], on_text)


def _parse_aa_profiles(text: Optional[str], error: str) -> dict:
    """The profile names out of aa-status's Profiles block."""
    out: dict = {"ok": False, "problem": "", "enforce": [], "complain": []}
    if not text:
        out["problem"] = error or "aa-status did not answer"
        return out
    section = None
    saw_header = False
    for raw in _strip_ansi(text).splitlines():
        line = raw.strip()
        if not line:
            continue
        lowered = line.lower()
        if lowered == "profiles:":
            saw_header = True
            continue
        if not saw_header:
            continue
        if "enforcement mode" in lowered:
            section = "enforce"
            continue
        if "complain mode" in lowered:
            section = "complain"
            continue
        # "Processes are in enforce mode" also *contains* "enforcement mode"-
        # shaped wording, and a process line under it looks exactly like a
        # profile line - so without this the confined-process table would be
        # read as a list of complain-mode profiles, naming the user's browser
        # and every other running program as a profile. It ends the block.
        if lowered.startswith("processes are in"):
            section = None
            continue
        if section is None:
            continue
        # A profile line is "<name>// <flags>"; the name is what identifies it.
        name = line.split("//", 1)[0].strip()
        if not name:
            continue
        out[section].append(name)
    if not (out["enforce"] or out["complain"]):
        out["problem"] = ("aa-status printed no profile names - either none are "
                          "loaded, or this build cannot read them")
        return out
    out["ok"] = True
    return out


# --- firmware: fwupd, which no settings app drives --------------------------
#
# fwupdmgr has --json on every subcommand, so this is the one reader on the
# page that gets real structured data rather than prose. get-devices is
# **unprivileged** and works without a password (verified); get-updates needs
# the daemon and is also unprivileged but slower, because it asks LVFS.

def firmware_devices(done: Callable[[dict, str], None]) -> None:
    """Every device fwupd knows about, and which of them can be updated.

    `fwupdmgr get-devices --json` is unprivileged on 1.9.x and answers without
    a polkit prompt - verified on fwupd 2.0.20 - so this runs on page load
    rather than behind a button. A machine with no fwupd daemon gets the tool's
    own error through the problem channel, which is the honest answer.
    """
    def finish(payload, error: str) -> None:
        if not isinstance(payload, dict):
            done({"ok": False, "problem": error or "fwupdmgr did not answer",
                  "devices": []}, error)
            return
        devices = payload.get("Devices")
        if not isinstance(devices, list):
            done({"ok": False, "problem": "fwupdmgr get-devices --json has no "
                                          "Devices list", "devices": []}, error)
            return
        rows = []
        for device in devices:
            if not isinstance(device, dict):
                continue
            flags = device.get("Flags")
            flags = flags if isinstance(flags, list) else []
            rows.append({
                "name": str(device.get("Name") or ""),
                "vendor": str(device.get("Vendor") or ""),
                "version": str(device.get("Version") or ""),
                "version_format": str(device.get("VersionFormat") or ""),
                "plugin": str(device.get("Plugin") or ""),
                "updatable": "updatable" in [str(f).lower() for f in flags],
                "internal": "internal" in [str(f).lower() for f in flags],
                "guid": (device.get("Guid") or [""])[0]
                        if isinstance(device.get("Guid"), list) else "",
            })
        done({"ok": True, "problem": "", "devices": rows}, "")

    run_json([tool_path_or_self("fwupdmgr"), "get-devices", "--json"], finish)


def firmware_updates(done: Callable[[dict, str], None]) -> None:
    """Firmware updates LVFS is offering, as a list.

    Ask, never volunteer: `get-updates` reaches out to lvfs.lvfs.org, so it is
    behind a button like the backup listing. The empty list is a real answer and
    renders as "nothing to install" - which is what a current machine should
    say, and is not the same as the read having failed.
    """
    def finish(payload, error: str) -> None:
        if not isinstance(payload, dict):
            done({"ok": False, "problem": error or "fwupdmgr did not answer",
                  "updates": []}, error)
            return
        updates = payload.get("Devices")
        if not isinstance(updates, list):
            done({"ok": False, "problem": "fwupdmgr get-updates --json has no "
                                          "Devices list", "updates": []}, error)
            return
        rows = []
        for device in updates:
            if not isinstance(device, dict):
                continue
            flags = device.get("Flags")
            rows.append({
                "name": str(device.get("Name") or ""),
                "version": str(device.get("Version") or ""),
                "release": str(device.get("Release") or ""),
                "description": str(device.get("Description") or ""),
                "severity": str(device.get("Severity") or ""),
                "flags": [str(f) for f in flags] if isinstance(flags, list) else [],
            })
        done({"ok": True, "problem": "", "updates": rows}, "")

    run_json([tool_path_or_self("fwupdmgr"), "get-updates", "--json"], finish)


# --- kernel modules ---------------------------------------------------------
#
# Read from /proc/modules and /sys/module rather than by running lsmod: the
# file is the kernel's own list, it is what `lsmod` prints, and reading it
# means this reader needs no tool and no privilege at all.

PROC_MODULES: Final = "/proc/modules"

# A module constant rather than a hardcoded path, for the same reason
# PROC_MODULES and HWMON_ROOT are: a test cannot create entries in the real
# /sys, so the root has to be reachable without patching os.path.join globally.
SYS_MODULE_ROOT: Final = "/sys/module"


def _module_rows() -> list[dict]:
    """Loaded modules out of /proc/modules, with their parameters and deps.

    A real line, verbatim from a 5.x /proc/modules:

        rdma_cm 155648 1 rpcrdma, Live 0x0000000000000000

    which is **space-separated, not tab-separated** - the format is
    `<name> <size> <refcount> <deps> <state> <address>`, with the dependency
    list comma-separated and a bare `-` when there are none. The first version
    of this parser split on tabs, on the strength of a docstring that said so,
    and returned **zero rows on a machine with 242 modules loaded** - which is
    the "invent nothing, report nothing" failure wearing the costume of a
    careful parser.

    Split on whitespace with maxsplit, keeping the trailing state and address
    together, because the dependency field is the only one that can contain a
    comma and the state is not worth separating from its address.
    """
    rows: list[dict] = []
    try:
        with open(PROC_MODULES, encoding="utf-8", errors="replace") as handle:
            lines = handle.read().splitlines()
    except OSError:
        return rows
    for line in lines:
        if not line.strip():
            continue
        parts = line.split(None, 4)
        if len(parts) < 3:
            continue
        name = parts[0].strip()
        if not name:
            continue
        deps_field = parts[3] if len(parts) > 3 else "-"
        deps = [d.strip() for d in deps_field.split(",") if d.strip() not in ("", "-")]
        rows.append({"name": name,
                     "size": int(parts[1]) if parts[1].strip().isdigit() else 0,
                     "count": parts[2].strip(),
                     "deps": deps,
                     "state": parts[4].split()[0] if len(parts) > 4
                              and parts[4].split() else "",
                     "params": module_parameters(name)})
    return rows


def module_parameters(name: str) -> list[dict]:
    """A module's runtime parameters, read from /sys/module/<name>/parameters.

    Each file there is one parameter and its current value, which is the
    authoritative source: `modinfo -p` reports what the module *accepts*, not
    what it is *set to*, and a page that showed only that would answer a
    different question from the one a user with a loaded module is asking.
    """
    base = os.path.join(SYS_MODULE_ROOT, name, "parameters")
    out: list[dict] = []
    try:
        names = sorted(os.listdir(base))
    except OSError:
        return out
    for param in names:
        try:
            with open(os.path.join(base, param), encoding="utf-8",
                      errors="replace") as handle:
                value = handle.read().strip()
        except OSError:
            continue
        out.append({"name": param, "value": value})
    return out


def loaded_modules(done: Callable[[list[dict], str], None]) -> None:
    """Every loaded kernel module, with its size, dependencies and parameters.

    Synchronous on purpose, like the /proc and /sys reads in hardware_card(): it
    is two directory walks answering in microseconds, and moving them to a
    thread to read a file the kernel keeps in memory would buy nothing.
    """
    rows = _module_rows()
    done(rows, "" if rows else "no modules are listed in /proc/modules")


# --- journal: a boot log, which is not a settings panel ---------------------

def journal_boots(done: Callable[[list[dict], str], None]) -> None:
    """done(rows, error) - the same two-argument shape every reader here uses.

    Worth stating because three of these readers were first written with a
    one-argument callback, and a page calling `def done(payload)` then failed
    with a TypeError **inside a GTK callback** - which GLib swallows into a page
    that silently renders nothing. Same failure shape as the fleet page's
    runner-signature mismatch.
    """
    def on_text(text: Optional[str], err: str) -> None:
        done([] if text is None else _parse_list_boots(text, err), "")

    run_text(["journalctl", "--list-boots", "--no-pager"], on_text)


def _parse_list_boots(text: str, error: str = "") -> list[dict]:
    """`journalctl --list-boots` into rows, split on **two** spaces.

    The table is fixed-width with columns separated by runs of spaces:

        IDX BOOT ID                          FIRST ENTRY                 LAST ENTRY
         -8 aa4a6a128a734f44b94d97a81607acf9 Sun 2026-09-20 14:21:35 IST Mon 2026-09-21 03:43:07 IST

    so the boot id's column is padded and every date is *one* field containing
    spaces of its own. Splitting on single whitespace gives seven columns where
    the table has four, and "Sun" lands where the date should be - which is what
    the first version did, and why it reported a boot's first entry as the word
    "Sun". The IDX and BOOT-ID boundaries are taken from the header's own column
    offsets, so the parse follows the header rather than counting on.
    """
    lines = [ln.rstrip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return []
    header = lines[0]
    try:
        id_idx = header.index("IDX")
        boot_idx = header.index("BOOT ID")
        first_idx = header.index("FIRST ENTRY")
        last_idx = header.index("LAST ENTRY")
    except ValueError:
        return []
    rows: list[dict] = []

    def field(line: str, start: int, end: int) -> str:
        if start >= len(line):
            return ""
        return line[start:min(end, len(line))].strip()

    for line in lines[1:]:
        rows.append({
            "idx": field(line, id_idx, boot_idx),
            "id": field(line, boot_idx, first_idx),
            "first": field(line, first_idx, last_idx),
            "last": field(line, last_idx, len(line)),
        })
    return rows


def journal_disk_usage(done: Callable[[Optional[str], str], None]) -> None:
    """How much disk the journal occupies, in the tool's own words.

    `--disk-usage` prints "Archived and active journals take up 2.2G in the file
    system." The figure is taken as the tool wrote it rather than reparsed into
    bytes: a page that showed "2.2 GB" and a tool that said "2.2G" would be
    making two claims about the same number, and only one of them is the
    tool's.
    """
    def on_text(text: Optional[str], err: str) -> None:
        if text is None:
            done(None, err)
            return
        match = re.search(r"take up\s+(.+?)\s+in the file system",
                          _strip_ansi(text))
        size = ""
        if match:
            size = match.group(1)
        elif text.strip():
            size = text.strip().splitlines()[0]
        done(size or None, "")

    run_text(["journalctl", "--disk-usage"], on_text)


# --- audio: the PipeWire graph, beyond a volume slider ----------------------
#
# wpctl status is a tree with three levels and box-drawing characters. Parsed
# by the tree's own structure rather than by splitting on " │" or "├─", because
# the box characters are what a *human* reads and they are what a renderer has
# to strip - so the name, the [id] and the flags are read off each line
# independently and the hierarchy is not guessed at.

WP_NODE = re.compile(
    r"(?P<marker>\*)?\s*"
    r"(?P<id>\d+)\.\s*"
    r"(?P<name>.*?)"
    r"(?:\s*\[(?P<flags>[^\]]*)\])?\s*$")

WP_SECTIONS = ("Audio", "Video", "Camera")

# A node line begins with an optional `*` then the id. Used to tell a node from
# a heading, because a *name* may end in a colon.
WP_ID = re.compile(r"^\*?\s*\d+\.")

# The heading line that starts "Clients:". A client under it names a *program*;
# a node under Devices/Sinks/Sources names hardware or an endpoint. There is no
# other way to tell them apart from the line itself, so the heading decides -
# and this is the reason getting it wrong turns the user's running programs into
# audio hardware.
WP_CLIENTS = "clients"

# The sub-headings wpctl prints, taken from real `wpctl status` output on 1.0.5:
# "Devices:", "Sinks:", "Sink endpoints:", "Sources:", "Source endpoints:",
# "Clients:", and under Video the same minus the endpoint pair. Named with
# underscores because a row title cannot contain a colon without libadwaita
# trying to parse the rest of it as markup.
WP_HEADINGS: Final = {
    "devices": "devices",
    "sinks": "sinks",
    "sink endpoints": "sink_endpoints",
    "sources": "sources",
    "source endpoints": "source_endpoints",
    "clients": "clients",
    "streams": "streams",
}

# wpctl draws the tree with box characters, so every line is prefixed with some
# of "│ ├ └ ─". Stripped before anything is parsed: a heading line arrives as
# " ├─ Devices:" and, left unstripped, matched no heading at all - which is
# exactly what happened on the first version of this parser, and why it reported
# zero sinks on a machine with four.
#
# **`*` is deliberately NOT in this class.** The star marks a section's default
# node and appears *after* the tree characters (" │  *   54. Speaker"), so
# stripping it here ate the one marker that says which output is in use - and
# every node came back with `default: False`, on a machine whose default sink
# was plainly marked.
_WP_TREE = re.compile(r"^[\s│├└─]+")


def pipewire_status(done: Callable[[dict, str], None]) -> None:
    """Sinks, sources and stream clients, as the graph reports them.

    Shape always safe to render: `ok=False` means the read did not happen, which
    is different from a session with no audio hardware - and the two must not
    look alike, because "your machine has no sound card" is a hardware claim
    and "wpctl did not answer" is not.
    """
    empty = {"ok": False, "problem": "", "server": "", "default": {},
             "default_sink": "", "default_source": "", "default_camera": "",
             "devices": [], "sinks": [], "sink_endpoints": [], "sources": [],
             "source_endpoints": [], "streams": [], "clients": [],
             "programs": [], "playing": [],
             "audio_devices": [], "audio_sinks": [], "audio_sources": [],
             "video_devices": [], "video_sinks": [], "video_sources": [],
             "camera_devices": [], "camera_sinks": [], "camera_sources": []}

    def on_text(text: Optional[str], err: str) -> None:
        if text is None:
            done({**empty, "problem": err or "wpctl did not answer"}, "")
            return
        done(_parse_wpctl(text), "")

    run_text([tool_path_or_self("wpctl"), "status"], on_text)


def _parse_wpctl(text: str) -> dict:
    """`wpctl status` into the graph's own sections.

    The default device is the one line in each section marked `*`, and it is
    recorded as an id rather than as a name: the name is already in the list, and
    copying it would let the two disagree.
    """
    out: dict = {"ok": True, "problem": "", "server": "", "default": {}}
    for key in WP_HEADINGS.values():
        out[key] = []
    section = ""
    heading = ""
    for raw in text.splitlines():
        if not raw.strip():
            continue
        stripped = _WP_TREE.sub("", raw).strip()
        if not stripped:
            continue
        if stripped.startswith("PipeWire "):
            match = re.search(r"PipeWire\s+'([^']+)'", stripped)
            out["server"] = match.group(1) if match else stripped
            continue
        # A top-level section: "Audio", "Video", "Camera".
        if stripped in WP_SECTIONS:
            section = stripped.lower()
            heading = ""
            continue
        # A sub-heading, e.g. "Devices:" or "Sink endpoints:".
        #
        # The `WP_ID` guard is **defensive and deliberately untested**: no line
        # in real `wpctl status` output has been found that needs it. A node
        # always carries `[flags]`, so its line ends in `]`; a heading ends in
        # `:`. A test for it was written and then deleted — it used
        # `Speaker: Built-in`, whose colon is *internal*, so the branch was never
        # reached and the test passed against a parser with the guard removed.
        # That is the untestable-defence shape this repo has removed twice
        # before (the fleet page's row-identity check, and an earlier version of
        # this file's own AST gate). It stays because it is correct and costs
        # nothing, but it is recorded here so nobody reads it as covered.
        if stripped.endswith(":") and not WP_ID.match(stripped):
            name = stripped[:-1].strip().lower()
            if name in WP_HEADINGS:
                heading = WP_HEADINGS[name]
                continue
            # An unrecognised heading ends the current one rather than leaving
            # its nodes filed under the last heading that *was* recognised -
            # which is how a "Video Streams:" list would show up as audio sinks.
            heading = ""
            continue
        match = WP_NODE.match(stripped)
        if not match:
            continue
        entry = {"id": match.group("id"),
                 "name": match.group("name").strip(),
                 "flags": (match.group("flags") or "").strip(),
                 "section": section, "heading": heading,
                 "default": bool(match.group("marker"))}
        if match.group("marker") == "*":
            # Keyed on **section and heading together**, because wpctl reuses the
            # heading names across sections: Video has its own "Sources:", so a
            # default keyed on the heading alone made the camera overwrite the
            # microphone and the page reported the wrong default input - with
            # *two* starred sources on screen and one of them silently winning.
            # The keys are what a row needs to ask "is this the default?".
            out["default"][f"{section}/{heading}" if heading else section] = \
                match.group("id")
        if heading:
            out[heading].append(entry)
    # A user asking "what is playing" means the running programs, which wpctl
    # files under Clients. They are surfaced under `programs` as well so the page
    # does not have to know wpctl's own heading for them.
    out["programs"] = out["clients"]
    out["playing"] = out["streams"] + out["clients"]
    # The per-section lists the page actually renders. wpctl reuses the heading
    # names across sections, so `sources` alone holds the audio microphone *and*
    # the camera, and a page reading that would put a webcam in the microphone
    # list. Resolved here rather than in the page so there is one place that
    # knows the heading names.
    for heading in ("sinks", "sources", "devices"):
        for sect in ("audio", "video", "camera"):
            out[f"{sect}_{heading}"] = [e for e in out[heading]
                                        if e["section"] == sect]
    out["default_sink"] = out["default"].get("audio/sinks", "")
    out["default_source"] = out["default"].get("audio/sources", "")
    out["default_camera"] = out["default"].get("video/sources", "")
    return out


# --- graphics: the driver matrix, per machine ------------------------------
#
# Built from the same `lspci -k` the Drivers page already runs, so it is one
# tool answering two questions and not a second source for PCI devices. The
# point of the page is the *userspace* half - Mesa, Vulkan, the render node -
# which no lspci line carries.

GPU_CLASSES = ("VGA compatible controller", "3D controller", "Display controller")


def gpu_report(done: Callable[[dict, str], None]) -> None:
    """Graphics hardware, the driver bound to it, and the render node.

    `ls /dev/dri/render*` is read directly: it is the kernel's own list of
    render nodes, needs no tool, and is the only way to answer "is there a GPU
    this session could actually use" rather than "is there a GPU".
    """
    render_nodes: list[str] = []
    try:
        render_nodes = sorted(
            os.path.join("/dev/dri", name) for name in os.listdir("/dev/dri")
            if name.startswith("render"))
    except OSError:
        render_nodes = []

    def on_text(text: Optional[str], err: str) -> None:
        if text is None:
            done({"ok": False, "problem": err or "lspci did not answer",
                  "gpus": [], "render_nodes": render_nodes}, err)
            return
        gpus = _parse_gpus(text)
        done({"ok": True, "problem": "", "gpus": gpus,
              "render_nodes": render_nodes}, "")

    run_text(["lspci", "-k"], on_text)


def _parse_gpus(text: str) -> list[dict]:
    """The graphics devices out of `lspci -k`, with the driver bound to each.

    An entry is a slot line mentioning one of the GPU classes, plus the
    indented `Kernel driver in use:` that follows it. **A slot with no driver
    line is reported with an empty driver**, not omitted: an unbound GPU is the
    single most useful thing this page can say, and dropping it would leave a
    machine with no working graphics looking like a machine with none.
    """
    gpus: list[dict] = []
    current: dict | None = None
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        if not line.startswith((" ", "\t")):
            head = line.split(":", 1)
            is_gpu = any(c in head[-1] for c in GPU_CLASSES)
            current = {"slot": head[0].strip(), "device": head[-1].strip(),
                       "driver": "", "modules": ""} if is_gpu and \
                len(head) > 1 else None
            if current:
                gpus.append(current)
            continue
        if current is None:
            continue
        body = line.strip()
        if body.startswith("Kernel driver in use:"):
            current["driver"] = body.split(":", 1)[1].strip()
        elif body.startswith("Kernel modules:") or body.startswith("Kernel driver:"):
            current["modules"] = body.split(":", 1)[1].strip()
    return gpus


# --- hybrid graphics: what PRIME would let a user choose ---------------------
#
# `switcheroo-control` is a **system** D-Bus service (net.hadess.
# SwitcherooControl) and is **read-only**. Verified by introspecting the live
# service on this machine: the only interface is `org.freedesktop.DBus.Properties`
# plus Introspect/Ping, and GetAll returns exactly
#
#     HasDualGpu : bool
#     NumGPUs   : uint32
#     GPUs      : [ { Name: str, Environment: [str], Default: bool } ]
#
# There is **no ListDevices, no SetDefault, no ListProperties** - those answer
# UnknownMethod / InvalidArgs. `switcherooctl list` is a pretty-printer over
# those same properties, which is why this page reads them directly instead of
# parsing its output.
#
# So a page can *report* which GPU is the default and what DRI_PRIME value
# addresses each one, and it can *launch* something on a chosen GPU - which is
# per-application and needs no privilege. It **cannot switch the session
# default**, because the service that would answer that does not implement it.
# Any control that appeared to would be a second manager built on a guess.
#
# The Environment array is flat and positional - ["DRI_PRIME",
# "pci-0000_00_02_0"] - because it is meant to be handed to `env`. It is
# paired up here, and a trailing odd element is dropped rather than paired with
# an empty value, which would produce a variable set to "" and an application
# that silently renders on the wrong GPU.

SWITCHEROO_BUS: Final = "net.hadess.SwitcherooControl"
SWITCHEROO_PATH: Final = "/net/hadess/SwitcherooControl"


def switcheroo_gpus(done: Callable[[dict, str], None]) -> None:
    """Every GPU switcheroo-control knows about, and which one is default.

    Always safe to render: `ok=False` means the service did not answer, which is
    different from a machine with one GPU - a container with no system bus says
    so, and a desktop with a single integrated GPU says `HasDualGpu: false` with
    its one entry listed. Those two must not look alike, because the first is an
    environment and the second is a machine.
    """
    empty = {"ok": False, "problem": "", "has_dual": False, "num": 0,
             "gpus": [], "default": ""}

    def failed(message: str) -> None:
        done({**empty, "problem": message}, "")

    try:
        proxy = Gio.DBusProxy.new_for_bus_sync(
            Gio.BusType.SYSTEM, Gio.DBusProxyFlags.DO_NOT_LOAD_PROPERTIES,
            None, SWITCHEROO_BUS, SWITCHEROO_PATH, SWITCHEROO_BUS, None)
    except GLib.Error as e:
        # No system bus at all: a container or a chroot, not a broken machine.
        failed(e.message)
        return

    def got(source, res):
        try:
            reply = source.call_finish(res)
        except GLib.Error as e:
            failed(e.message)
            return
        try:
            payload = reply.unpack()[0]
        except (IndexError, TypeError, AttributeError) as exc:
            failed(f"switcheroo-control sent something unreadable: {exc}")
            return
        done(_parse_switcheroo(payload), "")

    proxy.call("org.freedesktop.DBus.Properties.GetAll",
               GLib.Variant("(s)", (SWITCHEROO_BUS,)),
               Gio.DBusCallFlags.NONE, 5000, None, got)


def _parse_switcheroo(payload: dict) -> dict:
    """`Properties.GetAll` output into the shape the page renders.

    Defaults are recorded as the GPU's **index** within the returned list, which
    is what `switcherooctl launch -g N` takes. Recording the name instead would
    be a second way of naming a GPU that could drift from the tool's own
    numbering, and the tool's numbering is the one a user pastes into a command.
    """
    out = {"ok": True, "problem": "", "has_dual": False, "num": 0,
           "gpus": [], "default": ""}
    out["has_dual"] = payload.get("HasDualGpu") is True
    num = payload.get("NumGPUs")
    out["num"] = int(num) if isinstance(num, int) else 0
    raw = payload.get("GPUs")
    if not isinstance(raw, list):
        # The service answered but with no GPU list. That is not "no GPUs" - it
        # is a service this build cannot read, and saying zero would be a claim
        # about the machine.
        out["ok"] = False
        out["problem"] = ("switcheroo-control sent no GPU list this build "
                          "understands")
        return out
    default_index = -1
    for index, gpu in enumerate(raw):
        if not isinstance(gpu, dict):
            continue
        env = gpu.get("Environment")
        pairs: dict[str, str] = {}
        if isinstance(env, list):
            # Flat and positional, meant for `env`: NAME, value, NAME, value.
            # A trailing odd element is dropped rather than paired with "".
            for i in range(0, len(env) - 1, 2):
                key, value = str(env[i]), str(env[i + 1])
                if key:
                    pairs[key] = value
        is_default = gpu.get("Default") is True
        if is_default:
            default_index = index
        out["gpus"].append({
            "index": index,
            "name": str(gpu.get("Name") or ""),
            "environment": pairs,
            "default": is_default,
        })
    # The service's own count is trusted over len(gpus) only where it agrees; a
    # disagreement is reported rather than silently corrected either way.
    if out["num"] and out["num"] != len(out["gpus"]):
        logger.warning("switcheroo-control says NumGPUs=%s but sent %d entries",
                       out["num"], len(out["gpus"]))
    out["default"] = str(default_index) if default_index >= 0 else ""
    return out


def switcheroo_launch_command(gpu_index: str, command: str) -> list[str]:
    """The argv that runs `command` on `gpu_index`, for the page to show.

    A *displayed* command rather than a spawned one. Running somebody else's
    application is not a system-settings action, and `switcherooctl launch` would
    also block this page's main loop for as long as that application lives.
    The user copies it, or the desktop's own right-click integration does the
    same thing without a terminal.

    Uses `switcherooctl` rather than a bare `DRI_PRIME=` prefix because the
    switcheroo form also sets the NVIDIA variables (`__NV_PRIME_RENDER_OFFLOAD`,
    `__GLX_VENDOR_LIBRARY_NAME`) when the chosen GPU is an NVIDIA one, which is
    what makes GLX applications work rather than only Vulkan ones.
    """
    argv = ["switcherooctl", "launch"]
    if str(gpu_index).strip():
        argv.append(f"-g={gpu_index}")
    argv.append(command)
    return argv
