r"""Printers: what CUPS can see, and who it is that administers it.

**This page exists because the two desktops disagree.** GNOME Control Center
50.4 ships `gnome-printers-panel.desktop` (27 panels, printers among them,
verified by downloading the package and listing it). Plasma 6.7 ships **62**
System Settings KCMs and **none** of them is a printer: `grep -iE
'print|cups|paper|scanner'` over all 62 matches only `kcm_wallpaper.so`, on the
substring "paper", and sweeping every one of the 5067 cached packages for
`kcms/systemsettings/kcm_(print|cups|paper|scan|sane)` matches nothing at all.
So for a Plasma user this is a total gap and for a GNOME user a partial one.

**Read-only, and it will not print, cancel, accept or modify anything.** The
reader runs exactly six things: `lpstat -r`, `lpstat -t`, `lpoptions`,
`lpinfo -v`, `scanimage -L`, and `systemctl is-enabled`. `lpadmin`, `lp`,
`cupsctl` and `cancel` are *named* in the last group and never run - a report
that ran `cupsctl` would be one keystroke away from a write, because bare
`cupsctl` is a read and `cupsctl <anything>` is a write. A test asserts that by
walking the AST.

**Four states, kept apart, because a system manager that conflates them lies.**

| State | What prints it |
|---|---|
| CUPS not installed | no `lpstat` at all |
| **the daemon did not answer** | `lpstat -r` -> `scheduler is not running` |
| the daemon answered, no queue | `scheduler is running` and no printer lines |
| printers present | `printer <name> ...` lines |

**"The daemon did not answer" is the normal state on Shanios, and that is
measured, not guessed.** `shani-printer.install` runs `systemctl enable
cups.socket`, and `/usr/lib/systemd/system/cups.socket` is
`[Socket] ListenStream=/run/cups/cups.sock` - so the scheduler is
socket-activated and does not start until something talks to the socket. A
fresh Shanios install with no printer ever used has no running cupsd, and
`lpstat -r` answers `scheduler is not running`. The page says exactly that and
does not dress it as a fault.

**`lpstat -r` exits 0 in both states**, so the exit status cannot be the
discriminator; the text is. It also prints a *different capitalisation* per
subcommand - `lpstat -r`/`-t` say lowercase `scheduler is not running`, while
`lpstat -a`/`-p` say `Scheduler is not running.` with a full stop - which is
why the reachability probe is always `-r`.

## What the tools actually print (all captured, none recalled)

Every fixture in `tests/test_printers_page.py` is verbatim output from Arch
`cups 2:2.4.19-1`, `cups-filters 2.0.1-3`, `sane-airscan 0.99.38-1` and
`sane 1.4.0-4` with queues actually created. Four things that a
plausible-looking fixture would have hidden:

1. **`lpstat -t` interleaves five record kinds in one stream, and two of them
   look like printer names.** A job line is
   `OfficeHP-1              root              1024   Sat Oct  3 12:11:07 2026`
   - its first token is a queue name. A reason is on its own **tab-indented**
   continuation line, `\treason unknown`, and `\tpdftopdf filter function
   failed.` sits under a printer line for the same reason. Parsing by "any line
   that isn't the scheduler line is a printer" invents printers out of both.
2. **A printer state line has two spaces and a full stop in the middle:**
   `printer OfficeHP now printing OfficeHP-1.  enabled since Sat Oct  3
   12:11:07 2026`. The state phrase is free text (`is idle.`, `now printing
   X.`, `disabled`, `waiting...`), and only the trailing `enabled since` /
   `disabled since` is the enabled flag.
3. **`lpoptions` is one line of `key=value` pairs whose values may be
   single-quoted with spaces inside** - `printer-info='Office LaserJet'`.
   Splitting on whitespace turns that into two tokens and loses the value.
4. **`lpoptions` prints nothing at all and exits 0 when no queue exists**, and
   `scanimage -L` prints a whole four-line paragraph *on stdout* and exits 0
   when no scanner exists. Both are answers, not failures, and `run_text()`
   reports empty stdout as `said nothing` - so both readers accept the empty
   case as a value.

**`lpinfo -v` is not reachable by an arbitrary user.** As `nobody` it answers
`lpinfo: Forbidden`; as a member of groups `cups,lp,sys` it lists backends
normally. That is not an accident - `shani-printer.install` adds every
non-system user to `sys`, `cups` and `lp`, which is also what lets the same
user read `/etc/cups/cups-files.conf` (mode `0640 root:cups`). So
`Forbidden` is a real, expected outcome that must be reported as itself and
never as "no backends found".

**Where there is no `/etc/cupd/`.** CUPS on Arch keeps its configuration in
`/etc/cups/`; `/etc/cupd/` is the Debian path and does not exist here. There is
no `client.conf` either. The page reports the paths that exist and says so
rather than reading a file that is not there.

**Scanner sources are reported only when the backend says so.** sane-airscan's
own binary contains the literal strings `Flatbed`, `ADF Duplex`, `scan:Adf`
and names devices `%s:%d: %s`; `scanimage` prints `device \`%s' is a %s %s %s`
and `default device is \`%s'` (both format strings read out of the installed
binary, not from the manual). So the backend is the part of the device name
before the first `:`, and an ADF or flatbed is reported **only** when one of
the backend's own words appears in the line. If neither does, the page says the
backend did not state one instead of guessing "flatbed".
"""

from __future__ import annotations

import logging
import os
import re
from typing import Callable, Final, Optional

from gi.repository import Adw, GLib, Gtk  # type: ignore

from shani_cassini import system_status as ss

logger = logging.getLogger(__name__)

# The CUPS client tools live in /usr/sbin. ss.tool_path_or_self() searches the
# sbin directories and returns the bare name when nothing is found, so an absent
# tool still gets executed and reports its own real error rather than the page
# deciding in advance that it is missing.
LPSTAT: Final = "lpstat"
LPINFO: Final = "lpinfo"
LPOPTIONS: Final = "lpoptions"
SCANIMAGE: Final = "scanimage"

SUMMARY_NOTE = (
    "CUPS administration. This reports the queues, the printers, what can "
    "scan, and the tools that change any of it. It changes nothing itself."
)

TOOLS_NOTE = (
    "These four belong to their own tools. Adding, removing, enabling or "
    "disabling a queue is an administration action with a policy behind it, "
    "and this page does not perform it."
)

SCAN_NOTE = (
    "Scan-capable hardware SANE can see, and the backend that claims it. A "
    "device with an automatic document feeder is normally a second entry, "
    "because the feeder is a separate source."
)

STATE_ABSENT = (
    "The CUPS client tools are not installed, so nothing on this page can be "
    "read. On a Shanios image they ship as part of the printer support group."
)

STATE_UNREACHABLE = (
    "The scheduler did not answer. This is the normal state on Shanios: the "
    "CUPS socket is enabled, so the scheduler starts when something connects "
    "to it and is not running until then. It is not a fault, and it does not "
    "mean there are no printers."
)

STATE_NO_QUEUES = (
    "The scheduler is running and answering, and no queue has been defined on "
    "it. That is different from it not answering."
)

# The tools named in the last group. cupsctl is listed rather than run on
# purpose: with no arguments it reads the server settings, and with any
# argument at all it writes them.
TOOL_ROWS: Final[tuple[tuple[str, str, str], ...]] = (
    ("lpadmin", "Add, remove, enable or disable a queue",
     "Needs root for most changes"),
    ("lp", "Send a job to a queue - this is the printing command",
     "Needs root for someone else's job"),
    ("cupsctl", "Read or change the scheduler's own settings",
     "Reads with no argument; writes with any"),
    ("system-config-printer", "The graphical CUPS administration tool",
     "Needs the package installed; asks polkit"),
)

CUPS_FILES: Final[tuple[str, ...]] = (
    "/etc/cups/cups-files.conf",
    "/etc/cups/cupsd.conf",
    "/etc/cups/printers.conf",
)

# --- lpstat -t, verbatim shapes ---------------------------------------------
# `device for <name>: <uri>`
_DEVICE_RE = re.compile(r"^device for (?P<name>\S+): (?P<uri>\S.*)$")
# `<name> accepting requests since <date>` / `... not accepting requests ... -`
_ACCEPT_RE = re.compile(r"^(?P<name>\S+) (?P<neg>not )?accepting requests since")
# `printer <name> <free text phrase>.  enabled|disabled since <date> [-]`
#
# The phrase is OPTIONAL and the capture proves why: an enabled queue reads
# `printer OfficeHP now printing OfficeHP-1.  enabled since ...` with two
# spaces and a full stop, while a *disabled* queue reads
# `printer OldFax disabled since Sat Oct  3 12:11:07 2026 -` with no phrase at
# all and no doubled space. Requiring the phrase lost the enabled flag on every
# disabled queue - which is the one row that most needs it.
_PRINTER_RE = re.compile(
    r"^printer (?P<name>\S+) (?:(?P<phrase>.+?)\.\s\s)?"
    r"(?P<flag>enabled|disabled) since "
)
# A job: `OfficeHP-1   root   1024   Sat Oct  3 12:11:07 2026`. The first token
# is a queue name, so this must be matched before anything can call it a printer.
_JOB_RE = re.compile(
    r"^(?P<job>\S+-\d+)\s{2,}(?P<user>\S+)\s+(?P<size>\d+)\s+(?P<when>\S.*)$"
)
_DEFAULT_RE = re.compile(r"^system default destination: (?P<name>\S.*)$")
_REASON_RE = re.compile(r"^\t(?P<reason>\S.*)$")

_SCHEDULER_RE = re.compile(r"^scheduler is (?P<state>not running|running)\s*$")

# scanimage's own format strings, read out of the installed 1.4.0 binary.
_DEVICE_LINE_RE = re.compile(r"^device `(?P<name>.*)' is a (?P<rest>.*)$")
_DEFAULT_LINE_RE = re.compile(r"^default device is `(?P<name>.*)'$")
_NO_SCANNER_RE = re.compile(r"^No scanners were identified\.")

# sane-airscan's own literals, so "ADF" and "Flatbed" below are the words a
# backend uses rather than words this page made up.
_SOURCE_WORDS: Final = ("ADF", "Flatbed")

# `key=value`, where a value may be 'quoted with spaces inside'.
_OPTION_RE = re.compile(r"(\S+?)=('(?:[^']*)'|\S*)")


def esc(text: str) -> str:
    """Escape a string for a Pango label.

    **Every** title and subtitle on this page goes through here, because
    Adw.ActionRow parses its title and subtitle as Pango markup. A printer
    description containing `&` - and a device URI is free text - otherwise
    makes the row render as an *empty subtitle* rather than as an error, so a
    test that searched a subtitle for a character would pass against a row
    showing nothing at all.
    """
    return GLib.markup_escape_text(text or "", -1)


def parse_scheduler(out: str) -> Optional[str]:
    """`running` or `not running` from `lpstat -r`, or None if neither.

    The exit status is 0 in both cases, so it cannot be the discriminator; the
    text is the only thing that tells them apart.
    """
    for line in (out or "").splitlines():
        m = _SCHEDULER_RE.match(line.strip())
        if m:
            return m.group("state")
    return None


def parse_lpstat_t(out: str) -> dict:
    """Queues, their URIs, their state and the default, from `lpstat -t`.

    The stream interleaves scheduler line, default destination, device URIs,
    accept records, printer records, job records and **tab-indented
    continuation lines carrying a reason**. Only a `printer ` record, a
    `device for` record or an `accepting requests` record makes a queue.
    """
    printers: dict[str, dict] = {}
    default: Optional[str] = None
    jobs = 0
    # The record a following tab-indented line attaches its reason to.
    pending: Optional[dict] = None

    def queue(name: str) -> dict:
        return printers.setdefault(name, {
            "name": name,
            "device": None,
            "accepting": None,
            "phrase": None,
            "enabled": None,
            "reason": None,
        })

    for raw in (out or "").splitlines():
        m = _REASON_RE.match(raw)
        if m and pending is not None:
            pending["reason"] = m.group("reason")
            continue

        m = _JOB_RE.match(raw)
        if m:
            # Matched before the printer patterns: a job's first token is a
            # queue name, and this stream really does contain both.
            jobs += 1
            pending = None
            continue

        m = _DEVICE_RE.match(raw)
        if m:
            queue(m.group("name"))["device"] = m.group("uri")
            pending = None
            continue

        m = _ACCEPT_RE.match(raw)
        if m:
            rec = queue(m.group("name"))
            rec["accepting"] = m.group("neg") is None
            pending = rec
            continue

        m = _PRINTER_RE.match(raw)
        if m:
            rec = queue(m.group("name"))
            rec["phrase"] = (m.group("phrase") or "").strip() or None
            rec["enabled"] = m.group("flag") == "enabled"
            pending = rec
            continue

        m = _DEFAULT_RE.match(raw)
        if m:
            default = m.group("name")
            pending = None
            continue

        if raw.strip() == "no system default destination":
            default = None
            pending = None
            continue

        if _SCHEDULER_RE.match(raw.strip()):
            pending = None
            continue

        # Anything else is a header or a status line (e.g. `lpstat: No
        # destinations added.`), never a queue.
        pending = None

    return {
        "printers": list(printers.values()),
        "default": default,
        "jobs": jobs,
    }


def parse_lpoptions(out: str) -> dict:
    """`lpoptions` key/value pairs, with single-quoted values kept whole.

    Splitting on whitespace breaks `printer-info='Office LaserJet'` into two
    tokens and loses the value; empty output means no queue has defaults, which
    is an answer rather than a failure.
    """
    if not out or not out.strip():
        return {}
    return {
        m.group(1): (m.group(2)[1:-1] if m.group(2).startswith("'")
                     else m.group(2))
        for m in _OPTION_RE.finditer(out)
    }


def parse_lpinfo_v(out: str) -> list[str]:
    """Backend names from `lpinfo -v`, one `network <backend>` per line.

    An empty list is the honest answer when the read failed (`Forbidden` is
    stderr, and stdout is empty), and the caller distinguishes the two by
    carrying the error alongside.
    """
    found = []
    for line in (out or "").splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0] in ("network", "file", "usb"):
            found.append(parts[1])
    return found


def parse_scanimage_l(out: str) -> tuple[list[dict], str]:
    """Devices from `scanimage -L`, and a note when it found none.

    A device's backend is the part of its name before the first `:`, which is
    the convention sane uses (`hp:/dev/scanner`, and airscan's own `%s:%d: %s`).
    Sources are reported **only** when one of the backend's own words appears,
    so "not stated by the backend" is a real answer and never a guess.
    """
    devices: list[dict] = []
    note = ""
    for raw in (out or "").splitlines():
        m = _NO_SCANNER_RE.match(raw.strip())
        if m:
            note = (
                "SANE was asked and answered that no scanner is attached"
            )
            continue
        m = _DEFAULT_LINE_RE.match(raw.strip())
        if m:
            # `default device is `X'` is a second record kind in the same
            # stream; without this its name becomes a phantom device.
            continue
        m = _DEVICE_LINE_RE.match(raw.strip())
        if m:
            name = m.group("name")
            blob = f"{name} {m.group('rest')}"
            sources = sorted({w for w in _SOURCE_WORDS if w in blob})
            devices.append({
                "name": name,
                "backend": name.split(":", 1)[0] if ":" in name else name,
                "description": m.group("rest").strip(),
                "sources": sources,
            })
    return devices, note


def _run(tool: str, args: list[str], done: Callable) -> None:
    """One read, with the sbin-aware resolution this tool needs."""
    ss.run_text([ss.tool_path_or_self(tool), *args], done)


def _tool_rows() -> list[dict]:
    return [
        {"tool": tool, "what": what, "note": note,
         "installed": ss.have_tool(tool)}
        for tool, what, note in TOOL_ROWS
    ]


def printers_state(done: Callable[[dict, str], None]) -> None:
    """Everything this page shows, in one payload. Read-only.

    The order matters: the scheduler is probed first because `lpstat -t` on an
    unreachable daemon answers `scheduler is not running` with a **zero** exit
    status and an empty printer list, which is indistinguishable from a healthy
    scheduler holding no queues unless the reachability line is read on its own.

    The reads run **sequentially through an index, not as nested
    continuations.** The first version passed `collect` as the continuation of
    each of the four remaining readers, so completing any one of them called
    `collect` again and started all four over - which is an unbounded loop,
    whether the runner is asynchronous or not, and it is invisible in review
    because every line reads correctly. An index cannot re-enter itself.
    """
    payload: dict = {
        # An explicit flag, because `scheduler_error` cannot stand in for it:
        # "lpstat is not installed" and "lpstat -r answered something this page
        # does not recognise" are both an error string, and reporting the second
        # as the first tells a user to install a package they already have.
        "cups_installed": ss.have_tool(LPSTAT),
        "scheduler": None,
        "scheduler_error": "",
        "default": None,
        "printers": [],
        "jobs": 0,
        "options": {},
        "backends": [],
        "backends_error": "",
        "scanners": [],
        "scanners_note": "",
        # True until the SANE read lands. Measured on Arch with `sane` and
        # `sane-airscan` installed and **no scanner attached**:
        # `scanimage -L` takes 3.59s, reproducibly, against under 10ms for each
        # of the other five reads on this page. Held in sequence it left the
        # whole page showing "Reading…" for three and a half seconds on a
        # machine with no scanner - the common case - and that is the
        # *no-hardware* number: a machine with sane-airscan's DNS-SD discovery
        # has more probing to wait through, not less.
        "scanners_pending": True,
        "browsed": None,
        "tools": _tool_rows(),
        "files": [],
        "errors": [],
    }
    if not payload["cups_installed"]:
        payload["scheduler_error"] = f"{LPSTAT} is not installed"
        payload["files"] = _cups_files()
        done(payload, payload["scheduler_error"])
        return

    steps = (_read_scheduler, _read_queues, _read_options,
             _read_backends, _read_browsed)

    def deliver() -> None:
        # Called twice by design: once when the fast chain finishes and once
        # when the scan answer arrives. The page renders both times, and every
        # group is cleared and rebuilt, so the second delivery updates rather
        # than duplicates.
        payload["files"] = _cups_files()
        done(payload, "; ".join(payload["errors"]))

    def step(index: int) -> None:
        if index >= len(steps):
            deliver()
            return
        steps[index](payload, lambda _t, _e, i=index: step(i + 1))

    # The SANE read starts first and is NOT in `steps`, so it cannot hold up
    # the other five. It is the one read on this page that costs seconds.
    def scan_landed(text: Optional[str], err: str) -> None:
        _store_scanners(payload, text, err)
        payload["scanners_pending"] = False
        deliver()

    _read_scanners(payload, scan_landed)
    step(0)


def _read_scheduler(payload: dict, then: Callable) -> None:
    def got(text: Optional[str], err: str) -> None:
        if err:
            payload["scheduler_error"] = err
            payload["errors"].append(f"lpstat -r: {err}")
        else:
            state = parse_scheduler(text or "")
            if state is None:
                payload["scheduler_error"] = (
                    "lpstat -r answered something this page does not recognise"
                )
                payload["errors"].append(payload["scheduler_error"])
            else:
                payload["scheduler"] = state
        then(None, "")

    _run(LPSTAT, ["-r"], got)


def _read_queues(payload: dict, then: Callable) -> None:
    def got(text: Optional[str], err: str) -> None:
        if err:
            payload["errors"].append(f"lpstat -t: {err}")
        elif payload["scheduler"] == "not running":
            # The stream's empty printer list is the daemon not answering, and
            # it must not be rendered as "this machine has no printers".
            pass
        else:
            parsed = parse_lpstat_t(text or "")
            payload["printers"] = parsed["printers"]
            payload["default"] = parsed["default"]
            payload["jobs"] = parsed["jobs"]
        then(None, "")

    _run(LPSTAT, ["-t"], got)


def _read_options(payload: dict, then: Callable) -> None:
    def got(text: Optional[str], err: str) -> None:
        if err:
            # `lpoptions` prints nothing and exits 0 when no queue exists, which
            # run_text() quite correctly reports as `said nothing`. That is the
            # expected answer for a machine with no printers, not a fault.
            payload["errors"].append(f"lpoptions: {err}")
        else:
            payload["options"] = parse_lpoptions(text or "")
        then(None, "")

    _run(LPOPTIONS, [], got)


def _read_backends(payload: dict, then: Callable) -> None:
    def got(text: Optional[str], err: str) -> None:
        if err:
            # `Forbidden` is real and expected for a user not in group cups,
            # and is not the same answer as "there are no backends".
            payload["backends_error"] = err
        else:
            payload["backends"] = parse_lpinfo_v(text or "")
        then(None, "")

    _run(LPINFO, ["-v"], got)


def _store_scanners(payload: dict, text: Optional[str], err: str) -> None:
    """The one place a SANE answer becomes payload."""
    if err:
        payload["scanners_note"] = err
        return
    devices, note = parse_scanimage_l(text or "")
    payload["scanners"] = devices
    payload["scanners_note"] = note


def _read_scanners(payload: dict, then: Callable) -> None:
    def got(text: Optional[str], err: str) -> None:
        _store_scanners(payload, text, err)
        # The text and the error are **forwarded**, not dropped. The other
        # readers' continuation is the index-advancing step, which ignores
        # both; this one's is `scan_landed`, which reads the note off them.
        # Passing `(None, "")` instead delivered a second payload with an
        # empty scan answer, blanking the Scanning group on a machine whose
        # scanners had been identified perfectly well.
        then(text, err)

    _run(SCANIMAGE, ["-L"], got)


def _read_browsed(payload: dict, then: Callable) -> None:
    def got(text: Optional[str], err: str) -> None:
        # `systemctl is-enabled` answers on **stdout**, including the two
        # answers that are not a state: `not-found` (exit 4, the unit is not
        # installed at all) and `static`/`indirect` (no [Install] section, so
        # it can never be enabled). All are kept verbatim and worded where they
        # are used, because "enabled" is the only one that means browsing is on.
        if not err and text and text.strip():
            payload["browsed"] = text.strip()
        then(None, "")

    ss.run_text([ss.tool_path_or_self("systemctl"), "is-enabled",
                 "cups-browsed.service"], got)


def _cups_files() -> list[dict]:
    """The CUPS configuration files, reported whether or not they are readable.

    They are mode 0640 root:cups, and `shani-printer.install` puts every human
    user in group cups - so they are readable on a Shanios image and not on a
    system where that script never ran. Which of those two is true is the fact
    worth reporting, and it is why a refusal is not reported as a missing file.
    """
    found = []
    for path in CUPS_FILES:
        try:
            os.stat(path)
        except OSError:
            found.append({"path": path, "present": False, "readable": False})
            continue
        found.append({"path": path, "present": True,
                      "readable": os.access(path, os.R_OK)})
    return found


# --- the page ---------------------------------------------------------------

def _row(title: str, subtitle: str = "") -> Adw.ActionRow:
    return Adw.ActionRow(title=esc(title), subtitle=esc(subtitle))


class PrintersTab(Gtk.Box):
    """Read-only reporter. It renders what the reader hands it and shells out
    to nothing of its own."""

    def __init__(self, state=None, auth_manager=None) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self._state = state
        self._auth_manager = auth_manager
        self._page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self.append(self._page)
        self._build()
        GLib.idle_add(self.load)

    def _build(self) -> None:
        self._summary = Adw.PreferencesGroup(
            title="Printers", description=esc(SUMMARY_NOTE))
        self._row_state = _row("Reading…", "Reading the CUPS scheduler…")
        self._summary.add(self._row_state)
        self._page.append(self._summary)

        self._daemon = Adw.PreferencesGroup(
            title="Scheduler",
            description=esc("Whether cupsd is answering at all, which is a "
                            "different question from whether any queue "
                            "exists."))
        self._daemon_rows: list[Adw.ActionRow] = []
        self._page.append(self._daemon)

        self._queues = Adw.PreferencesGroup(
            title="Queues",
            description=esc("Every queue the scheduler is holding, its device "
                            "URI, and whether it is accepting jobs."))
        self._queue_rows: list[Adw.ActionRow] = []
        self._page.append(self._queues)

        self._scan = Adw.PreferencesGroup(
            title="Scanning", description=esc(SCAN_NOTE))
        self._scan_rows: list[Adw.ActionRow] = []
        self._page.append(self._scan)

        self._options = Adw.PreferencesGroup(
            title="Default printer and print options",
            description=esc("What lpoptions reports for this user."))
        self._option_rows: list[Adw.ActionRow] = []
        self._page.append(self._options)

        self._files = Adw.PreferencesGroup(
            title="CUPS configuration files",
            description=esc("These are mode 0640 root:cups. Shanios puts every "
                            "human user in group cups, so they are normally "
                            "readable; where they are not, that is reported "
                            "rather than worked around."))
        self._file_rows: list[Adw.ActionRow] = []
        self._page.append(self._files)

        self._tools = Adw.PreferencesGroup(
            title="Managing printers", description=esc(TOOLS_NOTE))
        for tool, what, note in TOOL_ROWS:
            self._tools.add(_row(tool, what))
            self._tools.add(_row(f"{tool} - notes", note))
        self._page.append(self._tools)

    def load(self) -> bool:
        printers_state(self._on_state)
        return False

    # -- render ------------------------------------------------------------
    @staticmethod
    def _clear(group: Adw.PreferencesGroup, rows: list) -> None:
        for row in rows:
            group.remove(row)
        rows.clear()

    def _on_state(self, payload: dict, err: str) -> None:
        sched = payload.get("scheduler")
        printers = payload.get("printers") or []

        if sched is None and not payload.get("cups_installed", True):
            title = "CUPS is not installed"
            self._row_state.set_subtitle(esc(STATE_ABSENT))
        elif sched == "not running":
            title = "The scheduler did not answer"
            self._row_state.set_subtitle(esc(STATE_UNREACHABLE))
        elif sched == "running" and not printers:
            title = "No queue is defined"
            self._row_state.set_subtitle(esc(STATE_NO_QUEUES))
        elif sched == "running":
            title = f"{len(printers)} queue{'' if len(printers) == 1 else 's'}"
            self._row_state.set_subtitle(esc(
                "The scheduler is answering and is holding these."))
        else:
            title = "The scheduler's state could not be read"
            self._row_state.set_subtitle(esc(
                "lpstat -r answered nothing this page recognises, which is not "
                "the same as it being stopped."))
        self._row_state.set_title(esc(title))

        self._render_daemon(payload)
        self._render_queues(payload)
        self._render_scanners(payload)
        self._render_options(payload)
        self._render_files(payload)

    def _add_daemon(self, row: Adw.ActionRow) -> Adw.ActionRow:
        """Track a Scheduler row so the next delivery can remove it.

        Without this the group was only ever appended to: the page is rendered
        **twice** by design (the fast chain, then the SANE answer), and the
        second delivery added the same three rows again. Rendering in Arch with
        the real tools showed 22 rows where there were 19 - the tell being a
        *duplication*, the mirror of this repo's more usual "row was built and
        never given a parent".
        """
        self._daemon_rows.append(row)
        return row

    def _render_daemon(self, payload: dict) -> None:
        self._clear(self._daemon, self._daemon_rows)

        err = payload.get("scheduler_error") or ""
        if not payload.get("scheduler") and not err:
            state = "Not read"
        elif payload.get("scheduler") == "running":
            state = "Running and answering"
        elif payload.get("scheduler") == "not running":
            state = "Not running - it did not answer"
        else:
            state = f"Could not be read: {err}"
        self._daemon.add(self._add_daemon(_row("CUPS scheduler", state)))

        browsed = payload.get("browsed")
        if not browsed:
            self._daemon.add(self._add_daemon(_row(
                "cups-browsed.service",
                "Could not be read, which is what a machine with no systemd "
                "says. cups-browsed finds printers on the network by "
                "browsing.")))
        elif browsed in ("enabled", "enabled-runtime"):
            self._daemon.add(self._add_daemon(_row(
                "cups-browsed.service",
                "Enabled, so printers announced on the network are found "
                "without being added by hand.")))
        elif browsed == "not-found":
            self._daemon.add(self._add_daemon(_row(
                "cups-browsed.service",
                "The unit is not installed, so no network printer is "
                "discovered automatically. A USB or local queue still "
                "works.")))
        elif browsed in ("static", "indirect", "generated", "transient",
                         "alias", "linked", "linked-runtime"):
            self._daemon.add(self._add_daemon(_row(
                "cups-browsed.service",
                f"Answered {browsed}, which means the unit has no [Install] "
                "section and cannot be switched on or off this way.")))
        elif browsed == "masked":
            self._daemon.add(self._add_daemon(_row(
                "cups-browsed.service",
                "Masked, so network discovery is deliberately switched "
                "off.")))
        else:
            self._daemon.add(self._add_daemon(_row(
                "cups-browsed.service",
                f"Answered {browsed}, so network printers are not discovered "
                "automatically.")))

        backends = payload.get("backends") or []
        berr = payload.get("backends_error") or ""
        if backends:
            self._daemon.add(self._add_daemon(_row(
                "Discovery backends",
                f"{len(backends)} available: {', '.join(backends)}")))
        elif berr:
            self._daemon.add(self._add_daemon(
                _row("Discovery backends", berr)))
        else:
            self._daemon.add(self._add_daemon(_row(
                "Discovery backends",
                "None listed, which means the read returned nothing")))

    def _render_queues(self, payload: dict) -> None:
        self._clear(self._queues, self._queue_rows)
        printers = payload.get("printers") or []
        default = payload.get("default")

        if not printers:
            if payload.get("scheduler") == "not running":
                sub = ("Not read: the scheduler did not answer, so this page "
                       "cannot say what it would have listed")
            elif payload.get("scheduler") == "running":
                sub = ("The scheduler is answering and holds no queue")
            else:
                sub = "Not read"
            self._queue_rows.append(_row("No queue to show", sub))
            self._queues.add(self._queue_rows[-1])
            return

        for p in printers:
            bits = []
            if p.get("enabled") is False:
                bits.append("Disabled")
            elif p.get("enabled") is True:
                bits.append("Enabled")
            if p.get("accepting") is False:
                bits.append("not accepting requests")
            if p.get("phrase"):
                bits.append(p["phrase"])
            if p.get("reason"):
                bits.append(f"reason: {p['reason']}")
            if p.get("device"):
                bits.append(f"device {p['device']}")
            if p.get("name") == default:
                bits.append("this is the default printer")
            self._queue_rows.append(_row(p["name"], "; ".join(bits)))
            if p.get("enabled") is False:
                self._queue_rows[-1].add_css_class("warning")
            self._queues.add(self._queue_rows[-1])

        jobs = payload.get("jobs") or 0
        self._queue_rows.append(_row(
            "Jobs held",
            f"{jobs} job{'' if jobs == 1 else 's'} in the queues above. "
            "This page does not cancel, hold or release them."))
        self._queues.add(self._queue_rows[-1])

    def _render_scanners(self, payload: dict) -> None:
        self._clear(self._scan, self._scan_rows)
        if payload.get("scanners_pending"):
            # Says it is asking. Rendering this group as "no hardware" while
            # the read is still outstanding is the version of this bug that
            # tells a user with a working scanner that they have none.
            self._scan_rows.append(_row(
                "Asking SANE",
                "Asking what scan hardware it can see. This is the slowest "
                "read on the page and it does not hold up anything else."))
            self._scan.add(self._scan_rows[-1])
            return
        devices = payload.get("scanners") or []
        note = payload.get("scanners_note") or ""
        if not devices:
            sub = note or ("Nothing was read; scanimage said nothing, which "
                           "is its answer when it is not installed")
            self._scan_rows.append(_row("No scan hardware found", sub))
            self._scan.add(self._scan_rows[-1])
            return
        for d in devices:
            bits = [f"backend {d['backend']}"]
            if d["sources"]:
                bits.append("sources: " + ", ".join(d["sources"]))
            else:
                bits.append("the backend did not state a source")
            if d["description"]:
                bits.append(d["description"])
            self._scan_rows.append(_row(d["name"], "; ".join(bits)))
            self._scan.add(self._scan_rows[-1])

    def _render_options(self, payload: dict) -> None:
        self._clear(self._options, self._option_rows)
        default = payload.get("default")
        self._option_rows.append(_row(
            "Default printer",
            default or "No default printer is set - lpstat reports none"))
        self._options.add(self._option_rows[-1])

        options = payload.get("options") or {}
        if not options:
            self._option_rows.append(_row(
                "Print options",
                "None set. lpoptions prints nothing and exits 0 when no "
                "queue has defaults, which is this answer rather than a "
                "failure."))
            self._options.add(self._option_rows[-1])
            return
        for key in sorted(options):
            self._option_rows.append(_row(key, options[key]))
            self._options.add(self._option_rows[-1])

    def _render_files(self, payload: dict) -> None:
        self._clear(self._files, self._file_rows)
        for f in payload.get("files") or []:
            if not f.get("present"):
                sub = "Not present on this system"
            elif f.get("readable"):
                sub = "Present and readable by this user"
            else:
                sub = ("Present but not readable without group cups or root. "
                       "Shanios adds every human user to that group.")
            self._file_rows.append(_row(f["path"], sub))
            self._files.add(self._file_rows[-1])