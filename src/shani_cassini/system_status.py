"""The real interfaces Cassini reads and drives - nothing here is invented.

* ``shani-deploy --status [--check] --json`` - slots, version, channel,
  remote stable/latest, update_available. Read-only, no root.
* ``shani-health --verify --json`` - {"timestamp", "checks": [{section,
  key, status, message}]}. Needs root: run through pkexec, on request.
* ``shani-deploy`` / ``--rollback`` / ``--set-channel X`` - through pkexec,
  output streamed line by line.

Everything runs through Gio.Subprocess, so the window never blocks.
"""

from __future__ import annotations

import json
import logging
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
