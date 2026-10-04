r"""IRQ balancing: whether the daemon is running, and where each IRQ is pinned.

**Neither desktop's settings has a panel for this.** GNOME Control Center 46.7
ships 28 panels and Plasma 6.7 ships 62 System Settings KCMs; neither set
contains anything about `irqbalance`, per the enumeration in this repo's
`AGENTS.md`, which is where the "IRQ balancing - `irqbalance` - none" row of
the measured panel-gap table comes from. `irqbalance` **ships** - it is a
`depends` of `shani-settings` (`shani-pkgbuilds/shani-settings/PKGBUILD:21`) and
`shani-settings.install:42` runs `systemctl enable irqbalance` - so on a Shanios
image the daemon is installed and enabled, and nothing anywhere says whether it
is running or what it did.

**Read-only, and that is a measurement rather than a preference.** irqbalance's
one job is to *write* `/proc/irq/<n>/smp_affinity_list`. The unit's own
`ReadWritePaths=/proc/irq` says so, and `irqbalance --debug` shows the balance
by performing it. So this page never runs the daemon, not even once with
`--debug`, and the reason is put in front of the user rather than filed as an
omission.

## What was measured, and the two things the measurement changed

Every fixture in `tests/test_irqbalance_page.py` is a capture, and three of them
came from an **Arch package archive** rather than from a live machine:

1. **`irqbala` does not exist, and that is not a "not installed" answer.** The
   `irqbalance 1.9.5-3` package in `shani-install-media/cache/pacman_cache/pkg/`
   was listed with `tar --zstd -tf` and contains exactly two executables,
   `usr/bin/irqbalance` and `usr/bin/irqbalance-ui`. There is no `irqbala` and
   there is nothing to install. A page that reached for `irqbala --debug` and
   reported its absence would send the user to install a program they already
   have.

2. **`/etc/irqbalance/irqbalance.banlist` and `irqbalance.smp_banlist` are not
   paths this package uses.** The same archive ships no `/etc/irqbalance/`
   directory at all: it ships `usr/share/irqbalance/irqbalance.env`, and the
   unit reads that plus an optional `/etc/default/irqbalance`. Bans in 1.9.5 are
   command-line flags, `--banirq=<irqnum>` and `--banmod=<module_name>`, read
   out of the package's own `irqbalance.1.gz` man page. Those two filenames are
   the Debian/Fedora-era spelling, and a page reporting them as "absent" would
   be reporting the absence of a file this distro never had.

3. **A single-CPU `smp_affinity_list` is NOT evidence that irqbalance ran.**
   This is the measurement that shaped the page. On the capture host -
   irqbalance **not installed at all**, `systemctl is-active` answering
   `inactive` - sixteen of the forty IRQ rows read back a **one-CPU** affinity:
   `nvme0q1`..`nvme0q8` on CPUs 1, 5, 3, 7, 2, 6, 0, 4, and `iwlwifi:queue_1`..
   `queue_8` on CPUs 0..7. The drivers set those themselves, one per queue. So a
   page reporting "interrupts are pinned across all 8 CPUs, balancing is
   working" would be reporting the drivers' defaults as the daemon's work on a
   machine with no daemon. **Spread and daemon state are two separate facts and
   are drawn as two separate things.**

4. **`/proc/interrupts` has 61 lines, 40 of which are IRQs.** The header is
   `CPU0`..`CPU7`, and **twenty named non-IRQ lines** follow the numeric ones:
   `NMI:`, `LOC:`, `SPU:`, `PMI:`, `IWI:`, `RTR:`, `RES:`, `CAL:`, `TLB:`,
   `TRM:`, `THR:`, `DFR:`, `MCE:`, `MCP:`, `ERR:`, `MIS:`, `PIN:`, `NPI:`,
   `PIW:`, `VPMI:`. `awk '{print $1}'` prints all twenty and `grep -c .` counts
   them, so "61 interrupts" is the answer a plausible-looking line gives on a
   machine with forty. `ERR:` and `MIS:` are worse than the rest: they carry
   **no per-CPU columns at all**, one number and nothing else.

5. **`/proc/irq/` holds 51 directories where `/proc/interrupts` has 40 rows.**
   IRQs 0-7, 10, 11, 13 and 15 each have a readable `smp_affinity_list` and no
   row in the interrupts file, so they have no device name. Both counts are real
   and they are not the same count; the page reports them apart and names the
   eleven rather than silently dropping them or folding them in.

6. **`systemctl cat irqbalance.service` answers on stderr with empty stdout.**
   Verbatim: `No files found for irqbalance.service.`, exit status 1, stdout
   empty. `ss.run_text()` reads empty stdout as a failure and hands the stderr
   text over as the error, so the unit is read as a **file** instead. That is the
   same reason `camera.py` has a local reader for `v4l2-ctl --list-devices`.

7. **The unit carries two conditions that make "enabled" and "running"
   different questions.** `ConditionVirtualization=!container` and
   `ConditionCPUs=>1`, verbatim from the shipped unit. An enabled-but-inactive
   irqbalance is therefore the *normal* state inside any container and on a
   single-CPU machine, and rendering that as a fault would be wrong. The unit
   also declares `RuntimeDirectory=irqbalance/`, so `/run/irqbalance` is the one
   filesystem artifact of a run - and systemd removes a `RuntimeDirectory` again
   when the unit stops, so its absence is what a stopped unit looks like rather
   than evidence about an earlier one.

8. **`is-enabled` and `is-active` both answer on stdout, with empty stderr and a
   non-zero exit status** - `not-found` and `inactive`, status 4. `run_text()`
   treats that as a value, because it only calls empty stdout a failure.

**`irqtop` ships with `util-linux` and was confirmed as `usr/bin/irqtop` in the
capture host's own pacman database**, so the page can name it as present rather
than guessing. It is not run: it is interactive, and it needs the daemon's
affinity to be worth watching.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Callable, Final, Optional

from gi.repository import Adw, GLib, Gtk  # type: ignore

from shani_cassini import system_status as ss

logger = logging.getLogger(__name__)

UNIT: Final = "irqbalance.service"
SYSTEMCTL: Final = "systemctl"

INTERRUPTS: Final = "/proc/interrupts"
IRQ_DIR: Final = "/proc/irq"
CPU_ONLINE: Final = "/sys/devices/system/cpu/online"

# The unit the package ships, read as a file. Not `systemctl cat`, which answers
# "No files found for <unit>." on stderr with empty stdout when the unit is not
# installed at all - an empty stdout the shared reader reports as a failure.
UNIT_FILE: Final = f"/usr/lib/systemd/system/{UNIT}"

# The unit's two `EnvironmentFile=` lines, verbatim:
#   EnvironmentFile=/usr/share/irqbalance/irqbalance.env
#   EnvironmentFile=-/etc/default/irqbalance
# The `-` prefix means optional, so an absent second file is what the unit asks
# for and is never reported as a missing configuration.
SHIPPED_ENV: Final = "/usr/share/irqbalance/irqbalance.env"
LOCAL_ENV: Final = "/etc/default/irqbalance"

# Read and reported because they are named so widely, and reported as what they
# are: paths this package does not use. Neither exists on a stock Arch install,
# which is not the same as a file the user deleted.
UNUSED_BANLIST_PATHS: Final[tuple[str, ...]] = (
    "/etc/irqbalance/irqbalance.banlist",
    "/etc/irqbalance/irqbalance.smp_banlist",
)

# The unit's Conditions, spelled out here as well as read from the file, so a
# test can assert the page knows them without needing the unit installed. The
# reasons are this page's; the conditions are the unit's.
UNIT_CONDITIONS: Final[tuple[tuple[str, str], ...]] = (
    ("ConditionVirtualization=!container",
     "skipped inside a container, which is where a settings window often is"),
    ("ConditionCPUs=>1",
     "skipped on a machine with one CPU, where there is nothing to balance"),
)

# The ban flags, from the package's own `irqbalance.1.gz`. This is where
# irqbalance 1.9.5 keeps what those two banlist files used to hold.
BAN_FLAGS: Final[tuple[tuple[str, str], ...]] = (
    ("--banirq=<irqnum>",
     "leave these IRQ numbers' affinity exactly as it is"),
    ("--banmod=<module_name>",
     "leave every IRQ owned by these modules exactly as it is"),
)

# The two `IRQBALANCE_*` variables that decide what the daemon is even asked to
# do, named here because they are the ones with a consequence.
VARS_THAT_MATTER: Final[tuple[str, ...]] = ("IRQBALANCE_ARGS", "IRQBALANCE_ONESHOT")

# The interactive viewer, named rather than run. Confirmed present as
# `usr/bin/irqtop` in the capture host's own pacman database.
IRQTOP: Final = "irqtop"

SUMMARY_NOTE = (
    "Read-only. This reports whether the irqbalance daemon is enabled and "
    "running, where the kernel currently has each interrupt pinned, and the "
    "configuration files the unit actually reads.\n"
    "It never starts, stops or reconfigures irqbalance, and it never writes an "
    "IRQ's CPU affinity - which is the one thing the daemon exists to do."
)

STATE_NOTE = (
    "irqbalance is a daemon: it starts at boot, then rewrites each IRQ's CPU "
    "affinity every few seconds. Enabled and running are two different "
    "questions, and so is enabled-and-inactive, which is the normal state "
    "inside a container and on a single-CPU machine - the unit's own conditions "
    "skip it there."
)

AFFINITY_NOTE = (
    "This is `/proc/interrupts` joined with each IRQ's `smp_affinity_list`: how "
    "many interrupts that device has taken, and which CPUs the kernel will let "
    "them run on.\n"
    "A one-CPU list is NOT evidence that irqbalance ran. Drivers set those "
    "themselves, one per queue: a machine with irqbalance not installed at all "
    "still shows nvme and iwlwifi queue interrupts each pinned to its own CPU. "
    "What is spread below is the kernel's state, not the daemon's work."
)

CONFIG_NOTE = (
    "irqbalance 1.9.5 keeps its configuration in environment variables, not in "
    "a banlist file. The unit reads the shipped `irqbalance.env` and an optional "
    "`/etc/default/irqbalance`; bans are command-line flags added through "
    "`IRQBALANCE_ARGS`.\n"
    "The `/etc/irqbalance/*.banlist` paths belong to older packaging and are "
    "listed so that their absence is not mistaken for a deleted file."
)

ACTIONS_NOTE = (
    "Deliberately not run here: `irqbalance --debug` shows what the daemon is "
    "doing by doing it, and what it does is write an IRQ's "
    "`smp_affinity_list` under `/proc/irq`.\n"
    "`irqtop` is the tool for watching that happen, and it is interactive. Both "
    "are yours to run in a terminal; a settings window is the one place where "
    "rebalancing the machine behind your back is not a reasonable default."
)

SOURCES_NOTE = (
    "  systemctl is-enabled irqbalance.service   will it start at boot\n"
    "  systemctl is-active irqbalance.service    is it running now\n"
    "  /usr/lib/systemd/system/irqbalance.service  the unit, read as a file\n"
    "  /usr/share/irqbalance/irqbalance.env      the shipped defaults\n"
    "  /etc/default/irqbalance                   optional local overrides\n"
    "  /proc/interrupts                          interrupts per CPU per device\n"
    "  /proc/irq/N/smp_affinity_list             the CPUs an IRQ may run on\n"
    "  /sys/devices/system/cpu/online            the CPUs that are up\n"
    "\n"
    "This page changes nothing, writes nothing, and starts nothing."
)

# `is-enabled` answers that are not a state. Kept verbatim and worded where they
# are used, because only `enabled` means the daemon will be started at boot.
NON_STATES: Final[frozenset[str]] = frozenset({
    "not-found", "static", "indirect", "generated", "transient", "alias",
    "linked", "linked-runtime", "masked", "masked-runtime", "bad",
})

# The two answers that mean the same thing, so a check cannot forget the
# `-runtime` variant: systemd will start the unit at boot.
ENABLED_STATES: Final[frozenset[str]] = frozenset({"enabled", "enabled-runtime"})

# Same, for `is-active`.
NOT_RUNNING: Final[frozenset[str]] = frozenset({
    "inactive", "activating", "deactivating", "failed", "unknown",
})

# Every icon this page uses, in one place, so a test can check each one exists
# in the theme that is actually installed.
ICONS: Final[tuple[str, ...]] = (
    "view-continuous-symbolic",
    "emblem-system-symbolic",
    "dialog-warning-symbolic",
    "dialog-information-symbolic",
)


# --- parsing -----------------------------------------------------------------

# The header row of `/proc/interrupts`: `            CPU0       CPU1 ... CPU7`.
_CPU_HEADER_RE = re.compile(r"CPU(\d+)")
# An IRQ row's label. The colon is part of the token, so `1:` and not `1` - which
# is what keeps `ERR:` and `NMI:` out, and they are both in the file.
_IRQ_ROW_RE = re.compile(r"^(\d+):$")
# An assignment in an environment file. The shipped `irqbalance.env` sets one
# variable and comments the rest out, so a commented line must not count.
_ENV_SET_RE = re.compile(r"^\s*(IRQBALANCE_[A-Z0-9_]+)\s*=(.*)$")
# A `--flag` word inside an `IRQBALANCE_ARGS`-style value. Dashes only, so the
# `0-edge` in a chip description cannot be read as an option.
_FLAG_RE = re.compile(r"--[a-z][a-z0-9-]*")


def parse_interrupts(text: str) -> tuple[list[dict], list[str]]:
    """IRQ rows out of `/proc/interrupts`, and the CPU numbers from its header.

    Returns `(rows, cpus)`, where `cpus` is the header's own list and `rows` are
    the numeric IRQ lines only, in file order.

    **The number of per-CPU columns is read, not assumed.** A plausible-looking
    implementation splits a row and takes the last two whitespace tokens as chip
    and device; on this capture that works for the IRQ rows and then reads
    `ERR:          0` - which has **no** per-CPU columns at all - as a device
    called `0`. Both shapes are in the capture, and the header is the only thing
    in the file that says how many columns a row carries.

    The twenty named lines (`NMI:`, `LOC:`, `ERR:`, `VPMI:` and the rest) are
    **not** IRQs and have no `/proc/irq/` directory, so they are dropped here.
    `grep -c . /proc/interrupts` counts 61 on the capture host; 40 of those are
    IRQs.

    A row whose device description is empty - which the kernel does produce for
    an unbound MSI IRQ - is kept with an empty `device` rather than dropped, so
    the row count stays the count the kernel reported.
    """
    lines = (text or "").splitlines()
    cpus = _CPU_HEADER_RE.findall(lines[0]) if lines else []
    rows: list[dict] = []
    for raw in lines[1:]:
        tokens = raw.split()
        if not tokens:
            continue
        m = _IRQ_ROW_RE.match(tokens[0])
        if not m:
            continue
        counts: list[int] = []
        rest: list[str] = []
        for offset, token in enumerate(tokens[1:]):
            if not rest and token.isdigit():
                counts.append(int(token))
            else:
                rest = tokens[1 + offset:]
                break
        rows.append({
            "irq": int(m.group(1)),
            "counts": counts,
            "total": sum(counts),
            "device": " ".join(rest),
        })
    return rows, cpus


def parse_unit_conditions(text: str) -> list[tuple[str, str]]:
    """The `Condition*=` lines out of a unit file, in file order.

    Read only from the `[Unit]` section. A `Condition` belongs to the unit as a
    whole and the shipped file has exactly one such section, so stopping at the
    next section header is bookkeeping rather than a claim that conditions can
    be scoped to a section.
    """
    found: list[tuple[str, str]] = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith(("#", ";")):
            continue
        if line.startswith("["):
            if line == "[Unit]":
                continue
            break
        if line.startswith("Condition"):
            key, _, value = line.partition("=")
            found.append((key, value))
    return found


def parse_env_file(text: str) -> dict:
    """The `IRQBALANCE_*` variables an environment file actually assigns.

    The shipped `irqbalance.env` is almost entirely comment, and every variable
    except `IRQBALANCE_ARGS` is commented out. "Documented in the file" and "set
    by the file" are therefore different facts, and a parser that kept the
    commented ones would report five settings the daemon was never given.
    """
    out: dict[str, str] = {}
    for raw in (text or "").splitlines():
        m = _ENV_SET_RE.match(raw)
        if m:
            out[m.group(1)] = m.group(2).strip().strip('"')
    return out


def flag_words(value: str) -> list[str]:
    """The `--flag` words inside an `IRQBALANCE_ARGS`-style value.

    The value is quoted in the shipped env file and expands a shell word list,
    so this cannot be a split on whitespace: `"-i 43 -i 44"` is two flags and
    `IRQBALANCE_ARGS=""` is none.
    """
    return _FLAG_RE.findall(value or "")


def affinity_cpus(affinity: str) -> set[int]:
    """The CPU numbers in a `smp_affinity_list` value.

    `0-7` is a range and `0,3,5` is a list, and the kernel allows both - the
    capture has 24 ranges and 16 single numbers.
    """
    members: set[int] = set()
    for part in (affinity or "").split(","):
        part = part.strip()
        if "-" in part:
            low, _, high = part.partition("-")
            if low.strip().isdigit() and high.strip().isdigit():
                members.update(range(int(low), int(high) + 1))
        elif part.isdigit():
            members.add(int(part))
    return members


def affinity_phrase(affinity: str, machine_cpus: int) -> str:
    """A CPU list as words, plus how many of the machine's CPUs it covers.

    The count is a **breadth**, never a balance: it says how many CPUs an IRQ
    may run on, not how evenly its interrupts landed. `/proc/interrupts` holds
    the per-CPU counts for that and this page does not summarise them away - the
    group description says so in as many words, so nobody reads a breadth as a
    fairness measurement.
    """
    if not affinity:
        return "not readable, so which CPUs it may use is unknown"
    members = affinity_cpus(affinity)
    if not members:
        return f"{affinity}, which names no CPU this page can count"
    total = machine_cpus or len(members)
    return (f"CPU {affinity} - {len(members)} of {total} "
            f"{'CPU' if len(members) == 1 else 'CPUs'}")


# --- reading -----------------------------------------------------------------


def _read(path: str) -> tuple[bool, bool, str]:
    """`(present, readable, text)` for a file, with no exception escaping.

    Three states and not two, because "absent" and "present but unreadable" are
    different facts: `/etc/default/irqbalance` being absent is the normal state
    the unit's `-` prefix asks for, and a file this user cannot read is a
    permission problem worth naming rather than folding into the same row.
    """
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return True, True, fh.read()
    except FileNotFoundError:
        return False, False, ""
    except (IsADirectoryError, PermissionError):
        return True, False, ""
    except OSError:
        return True, False, ""


def _irq_numbers() -> list[int]:
    """The numbered directories under `/proc/irq`, ascending."""
    try:
        entries = os.listdir(IRQ_DIR)
    except OSError:
        return []
    return sorted(int(e) for e in entries if e.isdigit())


def _affinity_of(irq: int) -> str:
    """One IRQ's `smp_affinity_list`, or "" when it could not be read.

    All 51 directories on the capture host had a readable file, so the unreadable
    case is a possibility rather than an invention, and it is reported as unknown
    for that IRQ rather than as "every CPU".
    """
    present, readable, text = _read(os.path.join(IRQ_DIR, str(irq),
                                                 "smp_affinity_list"))
    return text.strip() if (present and readable) else ""


def read_interrupts() -> dict:
    """`/proc/interrupts` joined with each IRQ's affinity.

    The join is one-sided on purpose. `/proc/irq` holds directories for IRQs
    `/proc/interrupts` has no row for - eleven of them on the capture host - and
    those have no device name, because the interrupts file is the only place a
    name comes from. They are counted and listed in the payload rather than
    added as unnamed rows or dropped: an IRQ the kernel will pin and this page
    cannot name is a fact, and both alternatives to reporting it are wrong.

    A `problem` string means the interrupts file itself could not be read, which
    is different from it being empty.
    """
    present, readable, text = _read(INTERRUPTS)
    if not present:
        return {"rows": [], "cpus": [], "problem": f"{INTERRUPTS} is not there",
                "unnamed": [], "affinity_dirs": 0}
    if not readable:
        return {"rows": [], "cpus": [],
                "problem": f"{INTERRUPTS} could not be read by this user",
                "unnamed": [], "affinity_dirs": 0}

    rows, cpus = parse_interrupts(text)
    named = set()
    for row in rows:
        row["affinity"] = _affinity_of(row["irq"])
        named.add(row["irq"])

    directories = _irq_numbers()
    return {
        "rows": rows,
        "cpus": cpus,
        "problem": "",
        "unnamed": [irq for irq in directories if irq not in named],
        "affinity_dirs": len(directories),
    }


# --- the reader --------------------------------------------------------------


def _systemctl(args: list[str], done: Callable) -> None:
    """One `systemctl` read, through the shared reader.

    Both of this page's `systemctl` reads answer on **stdout** with empty stderr
    and a non-zero exit status - `not-found` and `inactive`, status 4 - which
    `run_text()` treats as a value, because it only calls empty stdout a failure.
    """
    ss.run_text([ss.tool_path_or_self(SYSTEMCTL), *args], done)


def irqbalance_state(done: Callable[[dict, str], None]) -> None:
    """Everything this page shows, in one payload. Read-only.

    `done(payload, error)` takes two arguments, as every reader here must: a
    reader that hands its callback one raises `TypeError` *inside* a GTK
    callback, GLib swallows it, and the page renders nothing with nothing in the
    log.

    `/proc/interrupts` and the unit file are read **synchronously**, because
    they are file reads and not process spawns. Only the two `systemctl` reads
    spawn anything, and they are gathered with a counter rather than nested
    continuations: passing one callback as the continuation of both would call it
    twice, and if it also chained, re-enter itself for ever - which reads
    perfectly in review.
    """
    interrupts = read_interrupts()
    online_present, _, online_text = _read(CPU_ONLINE)
    unit_present, unit_readable, unit_text = _read(UNIT_FILE)
    env_present, env_readable, env_text = _read(SHIPPED_ENV)
    local_present, local_readable, local_text = _read(LOCAL_ENV)

    payload: dict = {
        "interrupts_path": INTERRUPTS,
        "interrupts_present": os.path.exists(INTERRUPTS),
        "interrupts_problem": interrupts["problem"],
        "cpus": interrupts["cpus"],
        "rows": interrupts["rows"],
        "unnamed": interrupts["unnamed"],
        "affinity_dirs": interrupts["affinity_dirs"],
        "irq_dir": IRQ_DIR,
        "cpu_online": online_text.strip() if online_present else "",
        "unit_path": UNIT_FILE,
        "unit_present": unit_present,
        "unit_readable": unit_readable,
        "conditions": parse_unit_conditions(unit_text) if unit_readable else [],
        "env_path": SHIPPED_ENV,
        "env_present": env_present,
        "env_readable": env_readable,
        "env": parse_env_file(env_text) if env_readable else {},
        "local_env_path": LOCAL_ENV,
        "local_env_present": local_present,
        "local_env_readable": local_readable,
        "local_env": parse_env_file(local_text) if local_readable else {},
        "unused_paths": [{"path": p, "present": os.path.exists(p)}
                         for p in UNUSED_BANLIST_PATHS],
        "irqtop": IRQTOP,
        "enabled": None,
        "active": None,
        "enabled_error": "",
        "active_error": "",
        "errors": [interrupts["problem"]] if interrupts["problem"] else [],
    }

    waiting = 2

    def arrived() -> None:
        nonlocal waiting
        waiting -= 1
        if waiting > 0:
            return
        done(payload, "; ".join(e for e in payload["errors"] if e))

    def got_enabled(text: Optional[str], err: str) -> None:
        if text is None:
            payload["enabled_error"] = err
            payload["errors"].append(f"is-enabled: {err}")
        else:
            payload["enabled"] = text.strip()
        arrived()

    def got_active(text: Optional[str], err: str) -> None:
        if text is None:
            payload["active_error"] = err
            payload["errors"].append(f"is-active: {err}")
        else:
            payload["active"] = text.strip()
        arrived()

    _systemctl(["is-enabled", UNIT], got_enabled)
    _systemctl(["is-active", UNIT], got_active)


# --- text that can reach a label --------------------------------------------


def _plain(text: object) -> str:
    """Text Pango cannot misread.

    `Adw.ActionRow`'s title and subtitle labels report `use_markup = True` -
    asserted from the widget itself in `tests/test_irqbalance_page.py` rather
    than assumed here - so an unescaped `&` or `<` makes GLib refuse the
    assignment and print `Failed to set text ... from markup due to error
    parsing markup`.

    Exactly three characters are escaped, in that order - `&` first, or the
    escapes introduced afterwards would be escaped a second time. Apostrophes
    and quotes are left alone: they are valid markup, and escaping "the
    kernel's" for no gain makes the strings this page's own tests read back
    unreadable.
    """
    raw = str(text)
    return raw.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _row(title: object, subtitle: object = "", icon: str = "") -> Adw.ActionRow:
    """The only place this module builds a row, and so the only way text enters.

    Title and subtitle are escaped here, and the single `set_subtitle()` call
    site in `_on_state` escapes as well. Between the two there is nowhere in
    this module that a string can reach a label unescaped.

    A prefix image is added only when an icon is given, so a row without one has
    no prefix widget at all rather than an invisible one.
    """
    row = Adw.ActionRow(title=_plain(title), subtitle=_plain(subtitle))
    if icon:
        row.add_prefix(Gtk.Image.new_from_icon_name(icon))
    return row


# --- the page ----------------------------------------------------------------


class IrqBalanceTab(Gtk.Box):
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
            title="irqbalance", description=_plain(SUMMARY_NOTE))
        self._row_state = _row("Status", "Reading…")
        self._summary.add(self._row_state)
        self._page.append(self._summary)

        self._daemon = Adw.PreferencesGroup(
            title="The daemon", description=_plain(STATE_NOTE))
        self._daemon_rows: list[Adw.ActionRow] = []
        self._page.append(self._daemon)

        self._config = Adw.PreferencesGroup(
            title="Configuration the unit reads",
            description=_plain(CONFIG_NOTE))
        self._config_rows: list[Adw.ActionRow] = []
        self._page.append(self._config)

        self._affinity = Adw.PreferencesGroup(
            title="Where each IRQ is pinned",
            description=_plain(AFFINITY_NOTE))
        self._affinity_rows: list[Adw.ActionRow] = []
        self._page.append(self._affinity)

        self._actions = Adw.PreferencesGroup(
            title="Deliberately not run here",
            description=_plain(ACTIONS_NOTE))
        self._actions_rows: list[Adw.ActionRow] = []
        self._page.append(self._actions)

        self._page.append(Adw.PreferencesGroup(
            title="Where this comes from", description=_plain(SOURCES_NOTE)))

    def load(self) -> bool:
        irqbalance_state(self._on_state)
        return False

    # -- render ------------------------------------------------------------
    @staticmethod
    def _clear(group: Adw.PreferencesGroup, rows: list) -> None:
        for row in rows:
            group.remove(row)
        rows.clear()

    def _add(self, group: Adw.PreferencesGroup,
             rows: list[Adw.ActionRow], row: Adw.ActionRow) -> Adw.ActionRow:
        group.add(row)
        rows.append(row)
        return row

    def _on_state(self, payload: dict, err: str) -> None:
        self._row_state.set_subtitle(_plain(self._verdict(payload)))
        self._render_daemon(payload)
        self._render_config(payload)
        self._render_affinity(payload)
        self._render_actions(payload)

    # -- the one line that says which state this machine is in --------------
    def _verdict(self, payload: dict) -> str:
        enabled = payload.get("enabled")
        active = payload.get("active")
        unit = payload.get("unit_path", UNIT_FILE)

        if enabled is None and active is None:
            return ("Could not read the daemon's state - systemctl answered "
                    "nothing this page recognises, which is not the same as "
                    "it being stopped")
        if enabled == "not-found":
            return (f"{unit} is not installed, so there is no daemon on this "
                    "machine to balance anything")
        if enabled in ("masked", "masked-runtime"):
            return ("The unit is masked, so the daemon is deliberately switched "
                    "off rather than merely absent")
        if enabled in ("static", "indirect", "generated", "transient", "alias",
                       "linked", "linked-runtime"):
            return (f"The unit is installed and systemd reports it as {enabled}, "
                    "which means it has no [Install] section: it exists, it "
                    "cannot be enabled this way, and it will not start at boot")
        if enabled is not None and enabled not in NON_STATES \
                and enabled not in ENABLED_STATES:
            return (f"systemctl is-enabled answered {enabled!r}, which this page "
                    "does not recognise, so whether it starts at boot is unknown")
        if active == "failed":
            return ("Installed, but systemd's last attempt at starting it did "
                    "not succeed - so it is not running and it is not the "
                    "container or single-CPU case either")
        if active == "active":
            if enabled in ("enabled", "enabled-runtime"):
                return ("Running, and enabled at boot. It is rewriting each "
                        "IRQ's CPU affinity every few seconds")
            return (f"Running now, but systemctl reports the unit as {enabled} "
                    "at boot, so this run is not one that will be repeated")
        if active in NOT_RUNNING:
            return (f"Installed and {enabled or 'not enabled'} at boot, but "
                    f"systemctl says the unit is {active}. That is the normal "
                    "state inside a container and on a single-CPU machine: the "
                    "unit's own conditions skip it there")
        return (f"systemctl is-active answered {active!r}, which this page does "
                "not recognise, so the daemon's state is unknown")

    def _render_daemon(self, payload: dict) -> None:
        self._clear(self._daemon, self._daemon_rows)

        enabled = payload.get("enabled")
        if enabled is None:
            state = f"Could not be read: {payload.get('enabled_error') or 'no answer'}"
        elif enabled in ("enabled", "enabled-runtime"):
            state = "Enabled - systemd will start it at boot"
        elif enabled == "not-found":
            state = "The unit is not installed"
        elif enabled in ("masked", "masked-runtime"):
            state = "Masked - it is deliberately switched off"
        else:
            state = (f"Answered {enabled}, which is not 'enabled', so systemd "
                     "will not start it at boot")
        self._add(self._daemon, self._daemon_rows,
                  _row("irqbalance.service - at boot", state,
                       "emblem-system-symbolic"))

        active = payload.get("active")
        if active is None:
            running = f"Could not be read: {payload.get('active_error') or 'no answer'}"
        elif active == "active":
            running = "Active - the daemon is running now"
        elif active == "failed":
            running = ("Failed - systemd's last attempt at starting it did not "
                       "succeed")
        elif active in NOT_RUNNING:
            running = f"{active.capitalize()} - it is not running now"
        else:
            running = f"Answered {active}, which this page does not recognise"
        self._add(self._daemon, self._daemon_rows,
                  _row("irqbalance.service - right now", running,
                       "emblem-system-symbolic"))

        conditions = payload.get("conditions") or []
        condition_lines = {f"{k}={v}" for k, v in conditions}
        if conditions:
            self._add(self._daemon, self._daemon_rows, _row(
                "Conditions on the unit",
                "; ".join(f"{key}" for key, _ in conditions)
                + ". A unit whose condition is not met is skipped rather than "
                  "started, so 'enabled' and 'running' can disagree here"))
        else:
            self._add(self._daemon, self._daemon_rows, _row(
                "Conditions on the unit",
                "None were found in "
                f"{payload.get('unit_path')}"
                + ("" if payload.get("unit_readable")
                   else ", which could not be read - so this is unknown, not "
                        "an absence of conditions")))
        for key, reason in UNIT_CONDITIONS:
            present = key in condition_lines
            self._add(self._daemon, self._daemon_rows, _row(
                key, ("Found in the unit - " if present
                      else "Not in the unit file that was read - ") + reason,
                "dialog-information-symbolic" if present
                else "dialog-warning-symbolic"))

        if not payload.get("unit_present"):
            self._add(self._daemon, self._daemon_rows, _row(
                payload.get("unit_path", UNIT_FILE),
                "Not present, so no unit file describes the daemon. The rows "
                "above came from systemd itself."))

    def _render_config(self, payload: dict) -> None:
        self._clear(self._config, self._config_rows)

        env = payload.get("env") or {}
        local = payload.get("local_env") or {}
        for path, present, readable, parsed in (
                (payload.get("env_path", SHIPPED_ENV), payload.get("env_present"),
                 payload.get("env_readable"), env),
                (payload.get("local_env_path", LOCAL_ENV),
                 payload.get("local_env_present"), payload.get("local_env_readable"),
                 local)):
            if not present:
                sub = ("Not present. The unit's EnvironmentFile line for this "
                       "path is optional, so its absence is what the unit asks "
                       "for and not a missing setting")
            elif not readable:
                sub = "Present but not readable by this user, so its settings are unknown"
            elif not parsed:
                sub = ("Present and readable. It sets no IRQBALANCE_ variable - "
                       "every variable in it is commented out, which is the "
                       "shipped state")
            else:
                bits = [f"{key}={value}" for key, value in sorted(parsed.items())]
                sub = "; ".join(bits)
                if path == payload.get("env_path"):
                    flags = flag_words(parsed.get("IRQBALANCE_ARGS", ""))
                    known = [f for f in VARS_THAT_MATTER if f in parsed]
                    if known:
                        sub += (". Set here: " + ", ".join(known))
                    if flags:
                        sub += f" - which the daemon reads as the flags {' '.join(flags)}"
                    elif "IRQBALANCE_ARGS" in parsed:
                        sub += (". IRQBALANCE_ARGS is empty, so the daemon runs "
                                "with no extra flags and no bans")
            self._add(self._config, self._config_rows, _row(path, sub))

        for flag, what in BAN_FLAGS:
            self._add(self._config, self._config_rows, _row(
                flag, f"{what}. This is where irqbalance 1.9.5 keeps a ban, "
                      "and it reaches the daemon through IRQBALANCE_ARGS"))

        for entry in payload.get("unused_paths") or []:
            path = entry.get("path", "")
            if entry.get("present"):
                sub = ("Present on this system. This irqbalance does not read "
                       "it, so whatever is in it has no effect")
            else:
                sub = ("Absent, and expected to be: the irqbalance package "
                       "ships no /etc/irqbalance directory. Do not read this as "
                       "a deleted file")
            self._add(self._config, self._config_rows, _row(path, sub))

    def _render_affinity(self, payload: dict) -> None:
        self._clear(self._affinity, self._affinity_rows)
        cpus = payload.get("cpus") or []
        rows = payload.get("rows") or []

        if payload.get("interrupts_problem"):
            self._add(self._affinity, self._affinity_rows, _row(
                "Could not read them",
                f"{payload.get('interrupts_problem')} - so which CPUs each "
                "interrupt may run on is unknown, not empty"))
            return

        if not rows:
            self._add(self._affinity, self._affinity_rows, _row(
                "No interrupt rows",
                f"{payload.get('interrupts_path')} has no IRQ line in it, which "
                "is what a kernel without any looks like"))
            return

        machine = len(cpus) or len(affinity_cpus(rows[0].get("affinity", "")))
        spread = {"single": 0, "broad": 0, "unknown": 0}
        for row in rows:
            width = len(affinity_cpus(row.get("affinity", "")))
            spread["unknown" if width == 0 else
                   "single" if width == 1 else "broad"] += 1
        summary = (
            f"{len(rows)} IRQ lines in {payload.get('interrupts_path')} across "
            f"{len(cpus)} CPU{'s' if len(cpus) != 1 else ''}. "
            f"{spread.get('single', 0)} of them may use exactly one CPU and "
            f"{spread.get('broad', 0)} may use more than one; "
            f"{spread.get('unknown', 0)} could not be read. "
            "How the interrupts actually fell across those CPUs is in the "
            "count beside each row - the affinity is the ceiling, not the split"
        )
        self._add(self._affinity, self._affinity_rows,
                  _row("Spread", summary, "view-continuous-symbolic"))

        online = payload.get("cpu_online")
        self._add(self._affinity, self._affinity_rows, _row(
            "CPUs online",
            (f"{online} per {CPU_ONLINE}" if online
             else f"Could not be read from {CPU_ONLINE}, so the CPU count above "
                  "comes from the interrupts file's own header")))

        directories = payload.get("affinity_dirs") or 0
        unnamed = payload.get("unnamed") or []
        if directories and directories != len(rows):
            self._add(self._affinity, self._affinity_rows, _row(
                "IRQs with no row in that file",
                f"{payload.get('irq_dir')} holds {directories} numbered "
                f"directories and the interrupts file has {len(rows)} rows. "
                f"{len(unnamed)} of them have no row, so they have no device "
                "name to show: "
                + (", ".join(str(i) for i in unnamed)
                   if unnamed else "none on this machine")))
        else:
            self._add(self._affinity, self._affinity_rows, _row(
                "IRQs with no row in that file",
                f"None: the {directories} numbered directories in "
                f"{payload.get('irq_dir')} match the {len(rows)} rows in the "
                "interrupts file"))

        for row in sorted(rows, key=lambda r: r.get("irq", 0)):
            device = row.get("device") or "no device named by the kernel"
            subtitle = (f"{affinity_phrase(row.get('affinity', ''), machine)}"
                        f" - {row.get('total', 0):,} interrupts counted"
                        f" - {device}")
            self._add(self._affinity, self._affinity_rows,
                      _row(f"IRQ {row.get('irq')}", subtitle))

    def _render_actions(self, payload: dict) -> None:
        self._clear(self._actions, self._actions_rows)
        self._add(self._actions, self._actions_rows, _row(
            "irqbalance --debug",
            "Not run. It prints what the daemon is doing by doing it, and what "
            "it does is write /proc/irq/<n>/smp_affinity_list"))
        self._add(self._actions, self._actions_rows, _row(
            f"{IRQTOP}",
            "The interactive viewer for interrupt routing. Not run either - it "
            "takes over the terminal and refreshes continuously"))
        self._add(self._actions, self._actions_rows, _row(
            "systemctl cat irqbalance.service",
            "Not used by this page. With no unit installed it answers "
            "'No files found for irqbalance.service.' on stderr with nothing on "
            "stdout, which the shared reader reports as a failed read; the unit "
            "is read from " + str(payload.get("unit_path", UNIT_FILE)) + " instead"))
        self._add(self._actions, self._actions_rows, _row(
            "Starting, stopping or pinning an IRQ",
            "Not offered. Those belong to systemctl and to writing an IRQ's "
            "smp_affinity_list yourself, in a terminal"))