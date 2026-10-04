"""Process priority: what ananicy-cpp is, and whether it is doing anything.

**Neither desktop has a panel for it, and the gap is measured rather than
recalled.** Shanios ships `ananicy-cpp` as a dependency of `shani-settings`, and
neither GNOME Control Center's 28 panels nor Plasma's 62 System Settings KCMs
has anything for process scheduling or priority. There is no page for it on
either desktop, which is why this one exists.

**ananicy-cpp applies nice/ionice/scheduling to other processes, so it needs
privilege, and that is the whole reason this page cannot write anything.**
Its own unit - read out of the real `ananicy-cpp-1.2.0-1-x86_64.pkg.tar.zst`,
not from a manual - carries:

    CapabilityBoundingSet=CAP_SYS_NICE CAP_SYS_RESOURCE CAP_DAC_READ_SEARCH
                           CAP_SYS_ADMIN CAP_DAC_OVERRIDE

`CAP_SYS_NICE` is what `setpriority()` and `sched_setscheduler()` need;
`CAP_SYS_ADMIN` is what moving a process between cgroups needs. A program that
re-prioritises *other people's* processes is privileged by construction, and a
GUI that offered to "apply" a priority from the desktop session would be asking
the user to type their password to do something the daemon already does
continuously. So: **no button, no `pkexec`, no write of any kind**, and an AST
gate in the tests holds it there.

**What it actually is, measured.** The upstream Python ananicy is superseded by
this C++ rewrite (`pkgdesc` from the package's own `.PKGINFO`: *"Ananicy Cpp is
a full rewrite of Ananicy in C++, featuring lower CPU and RAM usage."*). It
watches for new processes and gives each one the nice value, I/O class and
scheduling policy its rules ask for.

**`/etc/ananicy.d` is measured, and the honest finding is how little ships.**
The `ananicy-cpp` package contains exactly **three** files:

    /usr/bin/ananicy-cpp
    /usr/lib/systemd/system/ananicy-cpp.service
    /etc/ananicy.d/                                   <- an EMPTY directory

There is no `ananicy.conf` and there is no `.rules` file in it. A separate
`ananicy-cpp-rules` package is what carries rules, and it is **not** in either of
Shanios' two populated pacman caches (`shani-pkgbuilds/cache/pacman_cache/pkg`
and `shani-install-media/cache/pacman_cache/pkg`, each searched). So a Shanios
machine can easily have the daemon enabled and *zero* rules, which is a state
no desktop panel would ever show a user and which this page has to state
plainly rather than rounding to "running".

**What the image really says, and where.** `shani-install-media/chronoa-matrix/
chronoa-matrix.json` (generated 2026-10-03, merged gnome profile, image
20260925) records `ananicy-cpp` at `1.2.0-1` with
`"required_by": ["shani-settings"]`, its unit among the image's system units,
and `{"unit": "ananicy-cpp.service", "scope": "system", "by":
"multi-user.target"}` among `enabled_units`. So it is **enabled** on Shanios,
by exactly the `[Install] WantedBy=multi-user.target` its unit file states.
Whether it is **active** is not recorded there and is not claimed here: that
host has no ananicy-cpp at all (`is-enabled` answers `not-found`, exit 4), so
"active on Shanios" would be a claim nobody measured. The page reads the answer
at runtime instead.

**The config file path is not a guess.** The binary itself contains the two
literals `/etc/ananicy.d` and `/etc/ananicy.d/ananicy.conf` - read out of
`strings` on the real 1.2.0-1 binary, which is the only authority on where this
build reads from. Nothing else in the page hardcodes a rules location.

**The `apply_*` switch names are measured too**, out of the same binary's
strings: `apply_cgroup`, `apply_cpuset`, `apply_ionice`, `apply_latnice`,
`apply_nice`, `apply_oom_score_adj`, `apply_sched`, plus `check_freq`,
`cgroup_load` and `cpu_capacity`. The page reports which of them a config file
actually sets and **says "not set in this file" for the ones it does not**, which
is the honest answer: the daemon's built-in default for an absent key is not
knowable from the file and is not invented here.

**The same binary also carries its own skip messages**, and they are the reason
the cgroup group exists at all:

    cgroup2 at {} doesn't have a cpu controller available, skipping
    cgroup2 at {} lacks cpu.max, skipping

So the daemon's cgroup work is conditional on the `cpu` controller being
available. `/sys/fs/cgroup/cgroup.controllers` is the kernel's own list of what
is delegated to this hierarchy, it needs no tool and no password, and reading it
is what lets this page say whether the `cpu` controller is there instead of
assuming it is.

**`ExecStart=/usr/bin/ananicy-cpp start`** - note the **subcommand**. `start` is
how the daemon is told to daemonise, so an argv that runs the bare binary is not
a read. The same binary lists its verbs as `dump [sub-action]`, `start` and
`--reload`, and the dump sub-actions as `rules, types, cgroups, proc,
autogroup`. Only `dump` is run here, and its answer is shown **verbatim** rather
than parsed into a schema: `dump` attaches the running daemon's shared memory
segment (the binary says `Failed to get shared memory segment`), so what it
prints has not been observed on any machine available to this workspace and
guessing at its shape would be inventing a fact.

**A rule file is JSON, one object per line.** That is the shape the rule
directives above come from, and the page's per-file tally counts directives by
**looking for those keys in each line**, so a file that is not the JSON this
page expects is reported as unreadable rather than as zero rules.

**`journalctl -u ananicy-cpp.service -n 20 --no-pager` prints `-- No entries --`
on stdout and exits 0** when the unit has never run. Measured, streams split:
that line is on **stdout**, so a reader that treated "printed something" as
"there is a log" would show a log entry reading `-- No entries --`. It is
recognised here and reported as the absence of entries.

**Why the page is not registered.** Adding a section is a human's call and
`notebook.py` belongs to someone else's change, so this module stands alone;
`tests/test_ananicy_page.py` asserts the opposite direction, that the page is
*not* in `SECTIONS`, so that claim cannot go stale quietly.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Callable, Final, Optional

from gi.repository import Adw, GLib, Gtk  # type: ignore

from shani_cassini import system_status as ss

logger = logging.getLogger(__name__)

UNIT: Final = "ananicy-cpp.service"
# Absolute, so `os.path.exists` is the right question about it - the same
# reasoning camera.py uses for `/sys/class/video4linux`.
BINARY: Final = "/usr/bin/ananicy-cpp"
# Both literals are in the binary itself; see the module docstring.
CONFIG_DIR: Final = "/etc/ananicy.d"
CONFIG_FILE: Final = "/etc/ananicy.d/ananicy.conf"
SHARE_DIR: Final = "/usr/share/ananicy.d"
CGROUP_CONTROLLERS: Final = "/sys/fs/cgroup/cgroup.controllers"
JOURNAL_LINES: Final = 20
DUMP_LINES: Final = 20

# Icons verified to resolve in the installed **Adwaita** theme - see
# `test_the_icons_exist_in_the_adwaita_theme`, which forces
# `gtk-icon-theme-name=Adwaita` rather than trusting whatever theme a dev box
# happens to be running.
ICON_STOPWATCH: Final = "preferences-system-time-symbolic"
ICON_OK: Final = "object-select-symbolic"
ICON_WARN: Final = "dialog-warning-symbolic"
ICON_ERROR: Final = "dialog-error-symbolic"

# The directive keys a rule object may carry, as read out of the real binary's
# strings. Only these are counted; anything else in a rule line is left alone.
RULE_KEYS: Final[tuple[str, ...]] = (
    "nice", "sched", "sched_priority", "ioclass", "ionice",
    "oom_score_adj", "rtprio", "latnice", "cpu", "cgroup", "cgroup_load",
    "cpuset", "type", "cmd",
)

# The `apply_*` switches a config file may set. Same provenance.
APPLY_KEYS: Final[tuple[str, ...]] = (
    "apply_nice", "apply_sched", "apply_ionice", "apply_oom_score_adj",
    "apply_latnice", "apply_cpuset", "apply_cgroup",
)

OTHER_CONFIG_KEYS: Final[tuple[str, ...]] = (
    "check_freq", "cgroup_load", "cpu_capacity", "cgroup_realtime_workaround",
    "cgroup_realtime_ltime_workaround",
)

# The controllers the daemon's own strings say it needs for its cgroup work.
NEEDED_CONTROLLERS: Final[tuple[str, ...]] = ("cpu", "io")

# Every string this module can place in an argv, declared. The test walks the
# AST of each `ss.run_text(...)` call and fails on anything outside it, so a
# write verb cannot be added without this set changing too. It is the read-only
# promise as a *closed* list, which is stronger than searching for the verbs
# that would break it - and searching for `restart` would in any case match
# nothing while `enable` would match the read-only `is-enabled`.
READ_ONLY_ARGS: Final[frozenset[str]] = frozenset({
    "systemctl", "is-enabled", "is-active", "cat", UNIT,
    "journalctl", "-u", "-n", "--no-pager", str(JOURNAL_LINES),
    "ananicy-cpp", "dump", "rules",
})

# The four subprocess reads, as the exact literals that go into argv.
ARGV_IS_ENABLED: Final = ["systemctl", "is-enabled", UNIT]
ARGV_IS_ACTIVE: Final = ["systemctl", "is-active", UNIT]
ARGV_CAT: Final = ["systemctl", "cat", UNIT]
ARGV_JOURNAL: Final = ["journalctl", "-u", UNIT, "-n", str(JOURNAL_LINES),
                       "--no-pager"]
ARGV_DUMP: Final = ["ananicy-cpp", "dump", "rules"]

SUMMARY_NOTE = (
    "Read-only. This reports the daemon's unit state, its own unit file, the "
    "rules it has and how many directives they carry, and what the kernel has "
    "delegated to this cgroup hierarchy.\n"
    "It applies no priority and offers no way to. Re-prioritising another "
    "process needs CAP_SYS_NICE and moving one between cgroups needs "
    "CAP_SYS_ADMIN, which is why the daemon is privileged - so a settings "
    "window asking you to authorise a priority change would be asking you to "
    "type a password to do something the daemon already does continuously."
)

UNIT_NOTE = (
    "What systemd says about ananicy-cpp.service, and what the unit file it "
    "ships actually asks for. Enabled and active are different answers and are "
    "drawn separately: a unit can be enabled on every boot and not running now."
)

RULES_NOTE = (
    "Where rules are read from, and how many directives each file carries. The "
    "ananicy-cpp package itself ships an EMPTY /etc/ananicy.d - no ananicy.conf "
    "and no .rules - so rules arrive from a separate ananicy-cpp-rules "
    "package. An enabled daemon with no rules is a real state, and it is not "
    "the same as a daemon that is not running."
)

CONFIG_NOTE = (
    "The apply_* switches are read out of the real 1.2.0-1 binary. A key this "
    "file does not set is reported as not set - the daemon's own default for an "
    "absent key cannot be read out of the file, so it is not guessed."
)

DUMP_NOTE = (
    "ananicy-cpp's own dump of the rules it loaded, shown as it printed it. It "
    "reads the running daemon's shared memory segment, so with no daemon there "
    "is nothing to dump, and that is reported as a refusal rather than as an "
    "empty rule set. Nothing here is parsed into a shape: its output has not "
    "been observed on any machine available to this workspace."
)

CGROUP_NOTE = (
    "ananicy-cpp's own strings say it skips cgroup work when the cpu controller "
    "is unavailable and when cpu.max is missing, so this list is what decides "
    "whether that work happens at all. Read from sysfs: no tool, no password."
)

JOURNAL_NOTE = (
    "The daemon's last few log lines. journalctl prints '-- No entries --' on "
    "stdout and exits 0 when a unit has never run, so that line means there is "
    "no log rather than being a log entry."
)

PRIVILEGE_NOTE = (
    "Deliberately absent: any way to apply, change, reload or disable a rule.\n"
    "The unit carries ExecReload=/usr/bin/ananicy-cpp --reload and "
    "CapabilityBoundingSet=CAP_SYS_NICE CAP_SYS_RESOURCE CAP_DAC_READ_SEARCH "
    "CAP_SYS_ADMIN CAP_DAC_OVERRIDE. Editing a rule and reloading the daemon "
    "is a system administration action, it belongs in a terminal, and this page "
    "names the commands instead."
)

SOURCES_NOTE = (
    "  systemctl is-enabled ananicy-cpp.service    whether it starts at boot\n"
    "  systemctl is-active ananicy-cpp.service     whether it is running now\n"
    "  systemctl cat ananicy-cpp.service           the unit file itself\n"
    "  /etc/ananicy.d/*.rules                      rules, one JSON object a line\n"
    "  /etc/ananicy.d/ananicy.conf                 the apply_* switches\n"
    "  ananicy-cpp dump rules                      the daemon's own answer\n"
    "  journalctl -u ananicy-cpp.service -n 20     its recent log lines\n"
    "  /sys/fs/cgroup/cgroup.controllers           what this hierarchy has\n"
    "\n"
    "To change a priority: edit a .rules file, then\n"
    "  systemctl reload ananicy-cpp\n"
)

# --- the states systemctl answers with -------------------------------------
#
# `is-enabled` does not answer yes/no. These are the words it prints, measured
# one at a time on this host: `not-found` for a unit no package installed, and
# `inactive` from `is-active` for the same unit. `is-enabled` and `is-active`
# both exit 4 in those cases, which `run_text()` deliberately ignores - it
# reports empty stdout, not a non-zero status - so the word is the whole answer.
ENABLED_WORDS: Final[frozenset[str]] = frozenset({
    "enabled", "enabled-runtime", "disabled", "disabled-runtime",
    "static", "indirect", "generated", "transient", "masked", "masked-runtime",
    "linked", "linked-runtime", "alias", "not-found",
})
ACTIVE_WORDS: Final[frozenset[str]] = frozenset({
    "active", "activating", "deactivating", "inactive", "failed", "reloading",
})
# An answer outside these sets is *kept* and worded as unrecognised, never
# mapped onto the nearest state that sounds like it.
JOURNAL_EMPTY: Final = "-- No entries --"


def _plain(text: object) -> str:
    """Text Pango cannot misread.

    A row's title and subtitle go into a **markup** label - measured on both
    stacks this repo runs on, not assumed: `Adw.ActionRow`'s title and subtitle
    labels both report `use_markup = True`. An unescaped `&` makes GLib print
    `Failed to set text ... from markup due to error parsing markup` and refuse
    the assignment, so a unit description or a path containing one costs a wall
    of warnings in the log.

    Exactly three characters are escaped, in that order - `&` first, or the
    escapes introduced afterwards would be escaped a second time. Apostrophes
    and quotes are left alone: they are valid markup, and turning every "the
    daemon's" on this page into an entity buys nothing.

    Every string that reaches a row goes through here, and the AST gates in
    `tests/test_ananicy_page.py` prove there is nowhere else one could enter.
    """
    raw = str(text)
    return raw.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _row(title: object, subtitle: object = "", icon: str = "") -> Adw.ActionRow:
    """The only place this module builds a row, and so the only way text enters.

    Title and subtitle are escaped here; the two setter sites in `_set_status`
    escape as well. Between them there is nowhere in this module that a string
    can reach a label unescaped.
    """
    row = Adw.ActionRow(title=_plain(title), subtitle=_plain(subtitle))
    if icon:
        row.add_prefix(Gtk.Image.new_from_icon_name(icon))
    return row


def parse_unit_state(text: str, known: frozenset[str]) -> str:
    """One word out of `systemctl is-enabled`/`is-active`, or "" for neither.

    The whole of the answer is a single word on stdout, and `run_text()` hands
    it over verbatim whatever the exit status - which matters because both
    commands exit 4 for a unit that is not installed, and reporting that as a
    failure would render a machine without the daemon as one whose daemon had
    faulted.

    An unrecognised word is returned as the empty string rather than guessed at,
    so the page can say "answered something this page does not recognise"
    instead of picking the nearest state that sounds plausible.
    """
    body = (text or "").strip().splitlines()
    if not body:
        return ""
    word = body[0].strip()
    return word if word in known else ""


def parse_unit_file(text: str) -> dict:
    """`systemctl cat` output: the settings, and which files they came from.

    The unit this page exists for is a real trap for a naive parser, and the
    first description of the trap here was **wrong** - a test caught it, which
    is the point of pinning against the bytes rather than against the reading.

    The wrong version said the file's comment *prose* would become a key. It
    would not: `# Filter system calls to those absolutely required for correct
    functioning.` contains no `=`, so a parser that splits on `=` never sees it.
    What the file really does is ship **three commented-out directives among the
    live ones**:

        #SystemCallErrorNumber=EPERM
        #SystemCallFilter=@system-service
        #SystemCallFilter=~@debug @module @mount @reboot @swap @clock
        #obsolete @cpu-emulation

    Those lines *do* contain `=`, so a parser that does not drop comments first
    produces three keys reading `#SystemCallFilter` - and a parser that strips a
    leading `#` and keeps the rest produces a live-looking `SystemCallFilter`
    saying this daemon is confined by a syscall filter **it does not have**. A
    page reporting that would be reporting a sandbox this unit lacks, so
    `test_a_commented_out_directive_is_not_a_setting` holds the whole thing.

    `systemctl cat` prefixes each fragment with `# <path>` and a blank line.
    That header is **not observed on this host, which has no unit files at all**
    (`systemctl cat apcupsd.service` answers `No files found.` here too), so it
    is stripped if present and its absence is equally fine: the parser runs on
    the bare unit file, which *is* the real capture.

    The comment drop is the **only** mechanism, deliberately - see the note on
    the key guard below.
    """
    settings: dict[str, dict[str, str]] = {}
    files: list[str] = []
    section = ""
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            # A `# /path` line names the fragment this unit was assembled from.
            # Comments have already been dropped from the settings above, so
            # this only ever records a path.
            if line.startswith("# /"):
                files.append(line[2:].strip())
            continue
        if line.startswith("[") and line.endswith("]"):
            section = line[1:-1].strip()
            settings.setdefault(section, {})
            continue
        key, sep, value = line.partition("=")
        if not sep:
            continue
        key = key.strip()
        # **No second comment guard here, and that is on purpose.** An earlier
        # version also dropped `key.startswith("#")`, which made
        # `test_a_commented_out_directive_is_not_a_setting` unable to fail: the
        # line-level drop above is what removes those lines, so the key guard was
        # unreachable, and the test passed against a parser with the whole
        # comment block deleted. Two defences for one fact is not tidiness - it
        # is a gate that reports success while checking nothing. The line-level
        # drop is the only mechanism, so the test is the only defence.
        if not key:
            continue
        settings.setdefault(section, {})[key] = value.strip()
    return {"settings": settings, "files": files}


def _is_rule_line(line: str) -> bool:
    """One non-blank, non-comment line of a `.rules` file."""
    body = line.strip()
    return bool(body) and not body.startswith("#")


def parse_rule_text(text: str) -> dict:
    """One `.rules` file: its rule count and its per-directive tally.

    A rule file is one JSON object per line, so the directives that matter are
    looked for **in the parsed object** rather than as substrings of the line.
    Substring counting is not merely sloppy here: `"cpu"` occurs inside
    `"cgroup"` and inside `"cpu_capacity"`, so a page that counted `cpu` by
    `in` would claim a rule assigns a CPU set when it only names a cgroup.

    A line that will not parse is **counted as a rule and not tallied**, because
    it is a line in a rules file and the honest statement is that its
    directives are unknown - not that the file has none.
    """
    total = 0
    tally = {key: 0 for key in RULE_KEYS}
    unparsed = 0
    for raw in (text or "").splitlines():
        if not _is_rule_line(raw):
            continue
        total += 1
        try:
            rule = json.loads(raw.strip())
        except ValueError:
            unparsed += 1
            continue
        if not isinstance(rule, dict):
            unparsed += 1
            continue
        for key in RULE_KEYS:
            if key in rule:
                tally[key] += 1
    return {"rules": total, "tally": tally, "unparsed": unparsed}


def read_rules_dir(path: str) -> dict:
    """One rules directory: whether it exists, and a row per `.rules` file.

    A directory that cannot be listed is reported as a problem and kept apart
    from an empty one - `/etc/ananicy.d` missing and `/etc/ananicy.d` present
    with nothing in it are different facts, and only one of them means the
    daemon is installed.

    Line counts come from reading the files, not from `wc`: the page spawns no
    tool for this, so the count cannot disagree with what it read.
    """
    if not os.path.isdir(path):
        return {"path": path, "present": False, "problem": "", "files": [],
                "rules": 0, "tally": {}}
    try:
        entries = sorted(os.listdir(path))
    except OSError as exc:
        return {"path": path, "present": True,
                "problem": exc.strerror or str(exc), "files": [], "rules": 0,
                "tally": {}}

    files: list[dict] = []
    tally = {key: 0 for key in RULE_KEYS}
    rules = 0
    unparsed = 0
    for entry in entries:
        if not entry.endswith(".rules"):
            continue
        full = os.path.join(path, entry)
        try:
            with open(full, encoding="utf-8", errors="replace") as fh:
                body = fh.read()
            size = os.stat(full).st_size
        except OSError as exc:
            files.append({"name": entry, "read": False,
                          "problem": exc.strerror or str(exc), "rules": 0,
                          "tally": {}, "bytes": 0})
            continue
        parsed = parse_rule_text(body)
        files.append({"name": entry, "read": True, "problem": "",
                      "rules": parsed["rules"], "tally": parsed["tally"],
                      "bytes": size})
        rules += parsed["rules"]
        unparsed += parsed["unparsed"]
        for key, count in parsed["tally"].items():
            tally[key] += count
    return {"path": path, "present": True, "problem": "", "files": files,
            "rules": rules, "tally": tally, "unparsed": unparsed}


def parse_config(text: str) -> dict:
    """`ananicy.conf`: its `apply_*` switches and other keys, or that it is
    not JSON.

    Two things are deliberately not done. A key the file does not set is
    reported as **not set** rather than as the daemon's default, because a
    default is not in the file; and a file that will not parse is reported as
    unreadable rather than as an empty configuration, which would read as "no
    switches are on".
    """
    body = (text or "").strip()
    if not body:
        return {"ok": False, "problem": "the file is empty", "apply": {},
                "other": {}, "keys": []}
    try:
        data = json.loads(body)
    except ValueError as exc:
        return {"ok": False, "problem": f"not JSON: {exc}", "apply": {},
                "other": {}, "keys": []}
    if not isinstance(data, dict):
        return {"ok": False,
                "problem": f"JSON, but a {type(data).__name__} rather than an "
                           f"object, so it carries no keys",
                "apply": {}, "other": {}, "keys": []}
    apply = {key: data[key] for key in APPLY_KEYS if key in data}
    other = {key: data[key] for key in OTHER_CONFIG_KEYS if key in data}
    return {"ok": True, "problem": "", "apply": apply, "other": other,
            "keys": sorted(str(k) for k in data)}


def read_config(path: str = CONFIG_FILE) -> dict:
    """The config file: parsed if it is there and readable, and its absence said."""
    if not os.path.exists(path):
        return {"path": path, "present": False, "readable": False,
                "parsed": {"ok": False, "problem": "the file does not exist",
                           "apply": {}, "other": {}, "keys": []}}
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            body = fh.read()
    except OSError as exc:
        return {"path": path, "present": True, "readable": False,
                "parsed": {"ok": False, "problem": exc.strerror or str(exc),
                           "apply": {}, "other": {}, "keys": []}}
    parsed = parse_config(body)
    parsed["bytes"] = len(body.encode("utf-8", "replace"))
    return {"path": path, "present": True, "readable": True, "parsed": parsed}


def read_controllers(path: str = CGROUP_CONTROLLERS) -> dict:
    """What the kernel delegated to this cgroup hierarchy, and whether it is v2.

    `/sys/fs/cgroup/cgroup.controllers` is the v2 unified hierarchy's list of
    available controllers, one space-separated line. The check is **membership of
    a whitespace token set**, never a substring: `"cpu" in text` is true of both
    `cpuset` and `cpu_capacity`, so a substring test reports a CPU controller
    where the kernel delegated `cpuset` - and `cpuset` does not carry `cpu.max`,
    which is the exact thing ananicy-cpp says it needs.

    An unreadable or empty file yields an empty set rather than a guess, for the
    same reason sysfs emptiness is never interpreted as a value.
    """
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            body = fh.read()
    except OSError as exc:
        return {"path": path, "read": False, "problem": exc.strerror or str(exc),
                "controllers": [], "needed": [], "missing": list(
                    NEEDED_CONTROLLERS)}
    controllers = body.split()
    return {
        "path": path,
        "read": True,
        "problem": "",
        "controllers": controllers,
        "needed": [c for c in NEEDED_CONTROLLERS if c in controllers],
        "missing": [c for c in NEEDED_CONTROLLERS if c not in controllers],
    }


def parse_journal(text: str) -> dict:
    """`journalctl` output: the lines, and whether there were none.

    `-- No entries --` is on **stdout** with exit status 0, measured with the
    streams split, so "printed something" is not evidence of a log entry. It is
    recognised here and reported as the absence of entries, which is what it
    means: a unit that has never run.
    """
    body = (text or "").strip()
    if not body:
        return {"empty": True, "lines": [], "problem": ""}
    lines = [line for line in body.splitlines() if line.strip()]
    if lines and all(line.strip() == JOURNAL_EMPTY for line in lines):
        return {"empty": True, "lines": [], "problem": ""}
    return {"empty": False, "lines": lines, "problem": ""}


def _collect(answer: Optional[str], err: str,
             known: frozenset[str]) -> tuple[str, str]:
    """One `systemctl is-*` answer: the word, or the problem verbatim."""
    if answer is None:
        return "", err
    state = parse_unit_state(answer, known)
    if not state:
        return "", (err or f"answered something this page does not recognise: "
                           f"{(answer or '').strip()!r}")
    return state, ""


def ananicy_state(done: Callable[[dict, str], None]) -> None:
    """Everything this page shows, in one payload. Read-only, and it stays that way.

    Four subprocess reads - `is-enabled`, `is-active`, `cat` and `journalctl` -
    run concurrently behind a counter, and the file reads (the two rules
    directories, the config, the cgroup controllers) are done inline. They are
    file reads and no process spawns, which is why they need no thread; the same
    reasoning the System Info cards' `/proc` and `/sys` reads are recorded on.

    `done(payload, error)` takes two arguments, as every reader here must: a
    reader that hands its callback one raises `TypeError` *inside* a GTK
    callback, GLib swallows it, and the page renders nothing with nothing in the
    log.
    """
    payload: dict = {
        "unit": UNIT,
        "binary": BINARY,
        "binary_present": os.path.exists(BINARY),
        "enabled": "",
        "enabled_error": "",
        "active": "",
        "active_error": "",
        "unit_file": {"settings": {}, "files": []},
        "unit_file_error": "",
        "rules_dirs": [read_rules_dir(CONFIG_DIR), read_rules_dir(SHARE_DIR)],
        "config": read_config(),
        "controllers": read_controllers(),
        "journal": {"empty": True, "lines": [], "problem": ""},
        "journal_error": "",
        "dump": [],
        "dump_empty": True,
        "dump_error": "",
        "dump_installed": ss.have_tool("ananicy-cpp"),
        "errors": [],
    }
    waiting = 5

    def arrived() -> None:
        nonlocal waiting
        waiting -= 1
        if waiting > 0:
            return
        labelled = (("is-enabled", "enabled_error"),
                    ("is-active", "active_error"),
                    ("systemctl cat", "unit_file_error"),
                    ("journalctl", "journal_error"),
                    ("ananicy-cpp dump", "dump_error"))
        payload["errors"] = [
            f"{tool}: {payload[key]}" for tool, key in labelled
            if payload.get(key)
        ]
        done(payload, "; ".join(payload["errors"]))

    def from_enabled(text: Optional[str], err: str) -> None:
        payload["enabled"], payload["enabled_error"] = _collect(
            text, err, ENABLED_WORDS)
        arrived()

    def from_active(text: Optional[str], err: str) -> None:
        payload["active"], payload["active_error"] = _collect(
            text, err, ACTIVE_WORDS)
        arrived()

    def from_cat(text: Optional[str], err: str) -> None:
        if text is None:
            # `systemctl cat` on a unit no package installed puts
            # `No files found for ananicy-cpp.service.` on **stderr**, prints
            # nothing on stdout and exits 1 - measured with the streams split.
            # run_text() therefore reports it as an error carrying the tool's own
            # sentence, which is the honest reading and is kept verbatim.
            payload["unit_file_error"] = err
        else:
            payload["unit_file"] = parse_unit_file(text)
        arrived()

    def from_journal(text: Optional[str], err: str) -> None:
        if text is None:
            payload["journal_error"] = err
        else:
            payload["journal"] = parse_journal(text)
        arrived()

    def from_dump(text: Optional[str], err: str) -> None:
        if text is None:
            payload["dump_error"] = err
        else:
            lines = [line for line in (text or "").splitlines()
                     if line.strip()][:DUMP_LINES]
            payload["dump"] = lines
            payload["dump_empty"] = not lines
        arrived()

    systemctl = ss.tool_path_or_self("systemctl")
    ss.run_text([systemctl, *ARGV_IS_ENABLED[1:]], from_enabled)
    ss.run_text([systemctl, *ARGV_IS_ACTIVE[1:]], from_active)
    ss.run_text([systemctl, *ARGV_CAT[1:]], from_cat)
    ss.run_text([ss.tool_path_or_self("journalctl"), *ARGV_JOURNAL[1:]],
                from_journal)
    ss.run_text([ss.tool_path_or_self("ananicy-cpp"), *ARGV_DUMP[1:]], from_dump)


class AnanicyTab(Gtk.Box):
    """Read-only reporter for ananicy-cpp. It changes no priority and offers no
    way to change one; the reader hands it a payload and it renders that."""

    def __init__(self, state=None, auth_manager=None) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self._state = state
        self._auth_manager = auth_manager
        self._page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=24)
        self.append(self._page)
        self._aggregate_error = ""
        self._build()
        GLib.idle_add(self.load)

    def _build(self) -> None:
        self._summary = Adw.PreferencesGroup(
            title="ananicy-cpp", description=_plain(SUMMARY_NOTE))
        self._row_state = _row("Status", "Reading...")
        self._summary.add(self._row_state)
        self._page.append(self._summary)

        self._unit = Adw.PreferencesGroup(
            title="The unit systemd sees", description=_plain(UNIT_NOTE))
        self._page.append(self._unit)

        self._rules = Adw.PreferencesGroup(
            title="Rules", description=_plain(RULES_NOTE))
        self._page.append(self._rules)

        self._config = Adw.PreferencesGroup(
            title="Configuration", description=_plain(CONFIG_NOTE))
        self._page.append(self._config)

        self._dump = Adw.PreferencesGroup(
            title="What the daemon says it loaded", description=_plain(DUMP_NOTE))
        self._page.append(self._dump)

        self._cgroup = Adw.PreferencesGroup(
            title="Control groups", description=_plain(CGROUP_NOTE))
        self._page.append(self._cgroup)

        self._journal = Adw.PreferencesGroup(
            title="Recent log lines", description=_plain(JOURNAL_NOTE))
        self._page.append(self._journal)

        self._page.append(Adw.PreferencesGroup(
            title="What this page will not do", description=_plain(PRIVILEGE_NOTE)))
        self._page.append(Adw.PreferencesGroup(
            title="Where this comes from", description=_plain(SOURCES_NOTE)))

        self._unit_rows: list[Adw.ActionRow] = []
        self._rules_rows: list[Adw.ActionRow] = []
        self._config_rows: list[Adw.ActionRow] = []
        self._dump_rows: list[Adw.ActionRow] = []
        self._cgroup_rows: list[Adw.ActionRow] = []
        self._journal_rows: list[Adw.ActionRow] = []

    def load(self) -> bool:
        ananicy_state(self._on_state)
        return False

    # -- render ------------------------------------------------------------
    @staticmethod
    def _clear(group: Adw.PreferencesGroup, rows: list[Adw.ActionRow]) -> None:
        for row in rows:
            group.remove(row)
        rows.clear()

    def _set_status(self, title: object, subtitle: object) -> None:
        """The only two setter sites in this module, and both escape.

        Split out so the AST gate has exactly one `set_title` and one
        `set_subtitle` call to check, rather than one per branch.
        """
        self._row_state.set_title(_plain(title))
        self._row_state.set_subtitle(_plain(subtitle))

    def _on_state(self, payload: dict, err: str) -> None:
        # Kept, and used: every read has its own error field, but the reader
        # also hands over the joined list, and a page that accepts a second
        # argument and never reads it is a page with a hole where a diagnostic
        # should be. `_state_detail` falls back to this.
        self._aggregate_error = err or ""
        self._set_status(*self._verdict(payload))
        self._render_unit(payload)
        self._render_rules(payload)
        self._render_config(payload)
        self._render_dump(payload)
        self._render_cgroup(payload)
        self._render_journal(payload)

    def _verdict(self, payload: dict) -> tuple[str, str]:
        """The state in the title, and the sentence that matters in the subtitle.

        Split deliberately, and the reason is measured: an `Adw.ActionRow`'s
        title is `get_title()`-readable in full and can carry a clause, while a
        `PreferencesGroup` description wraps and clips. The state goes up top
        where it is always visible; the load-bearing fact - *there is nothing to
        apply*, or *the enablement could not be read* - goes below it, because
        a state that reads "running" on a machine whose rules directory is empty
        is the one thing this page exists to prevent.
        """
        enabled = payload.get("enabled") or ""
        active = payload.get("active") or ""
        dirs = payload.get("rules_dirs") or []
        rules = sum(d.get("rules") or 0 for d in dirs)
        present = any(d.get("present") for d in dirs)

        if enabled == "not-found":
            return ("Not installed",
                    "systemctl says there is no such unit, so nothing on this "
                    "page can be read. Shanios ships ananicy-cpp as a "
                    "dependency of shani-settings, so on a Shanios image this "
                    "row means the package is not installed.")

        # A missing word is a missing answer, whether or not a reason came with
        # it. Keyed on the word being absent rather than on an error string
        # being present, because the two are not the same: an older version
        # collected only the error strings, so a payload carrying an unreadable
        # state and no reason rendered as an ordinary "will not start at boot".
        unreadable = []
        for key, label in (("enabled", "is-enabled"), ("active", "is-active")):
            if payload.get(key):
                continue
            why = (payload.get(f"{key}_error") or self._aggregate_error
                   or "no answer")
            unreadable.append(f"{label}: {why}")
        if unreadable:
            state = []
            state.append(f"{enabled} at boot" if enabled
                         else "enablement not read")
            state.append("running" if active == "active"
                         else (f"{active}" if active else
                               "runtime state not read"))
            return (" and ".join(state),
                    "Part of this could not be read, so it is not shown as a "
                    f"state: {'; '.join(unreadable)}")

        running = active == "active"
        booting = enabled.startswith("enabled")
        if not booting:
            # Not "Enabled but ..." - `disabled` is the opposite of enabled and
            # the first version of this line read exactly that, which is the
            # kind of sentence that makes a page untrustworthy.
            title = (f"Will not start at boot ({enabled})" if enabled
                     else "Enablement not read")
        elif not running:
            title = "Enabled, not running now"
        elif rules == 0 and not present:
            title = "Running with no rules directory"
        elif rules == 0:
            title = "Running with nothing to apply"
        else:
            title = (f"Running, {rules} rule{'s' if rules != 1 else ''}")

        if title == "Running with nothing to apply":
            return (title,
                    "Enabled and running, and the rules directory holds no "
                    "rules at all. The ananicy-cpp package ships "
                    "/etc/ananicy.d as an EMPTY directory and no "
                    "ananicy-cpp-rules package is in either Shanios pacman "
                    "cache, so rules may never arrive on this machine.")
        if title == "Running with no rules directory":
            return (title,
                    "Enabled and running, and there is no /etc/ananicy.d, "
                    "which is what a machine with no ananicy-cpp rules package "
                    "looks like.")
        if not booting:
            return (title, "systemctl says it will not start at boot, so "
                           "nothing it does is happening now either way.")
        if not running:
            return (title,
                    f"systemctl reports it as {active}. A daemon that is not "
                    f"running applies nothing, whatever its unit file says.")
        return (title,
                "Read-only: this page reports the state and applies nothing.")

    def _render_unit(self, payload: dict) -> None:
        self._clear(self._unit, self._unit_rows)

        # The two words, verbatim, and the reason for either not being there.
        # Both answers are drawn and not summarised: `not-found` and
        # `disabled` are different facts about a machine, and `failed` is
        # neither of them.
        self._add_unit(_row(
            "is-enabled", self._state_detail(payload, "enabled"),
            self._state_icon(payload, "enabled")))
        self._add_unit(_row(
            "is-active", self._state_detail(payload, "active"),
            self._state_icon(payload, "active")))

        service = ((payload.get("unit_file") or {}).get("settings") or {}).get(
            "Service", {})
        install = ((payload.get("unit_file") or {}).get("settings") or {}).get(
            "Install", {})

        if not service:
            problem = payload.get("unit_file_error") or ""
            self._add_unit(_row(
                "Unit file",
                problem or "systemctl cat returned nothing this page recognises",
                ICON_WARN))
            return

        self._add_unit(_row(
            "ExecStart", service.get("ExecStart", "not stated"), ICON_STOPWATCH))
        self._add_unit(_row(
            "ExecReload", service.get("ExecReload", "not stated"),
            ICON_OK if "ExecReload" in service else ICON_WARN))
        self._add_unit(_row(
            "Started by", install.get("WantedBy", "not stated")))
        self._add_unit(_row(
            "Its own priority",
            f"Nice={service.get('Nice', 'not stated')} - it runs at a negative "
            f"nice value so it can reach other processes' priorities"))
        self._add_unit(_row(
            "Restart policy",
            f"{service.get('Restart', 'not stated')}, after "
            f"{service.get('RestartSec', 'not stated')}"))
        self._add_unit(_row(
            "Memory",
            f"High={service.get('MemoryHigh', 'not stated')}, "
            f"max={service.get('MemoryMax', 'not stated')}, "
            f"OOMScoreAdjust={service.get('OOMScoreAdjust', 'not stated')}"))
        caps = service.get("CapabilityBoundingSet")
        self._add_unit(_row(
            "Capabilities",
            caps or "none stated, so it holds the full set",
            ICON_WARN if caps else ICON_ERROR))
        if caps:
            self._add_unit(_row(
                "Why it needs them",
                "CAP_SYS_NICE sets another process's priority, CAP_SYS_ADMIN "
                "moves one between control groups, CAP_SYS_RESOURCE lifts the "
                "limits. This is why the page cannot write."))
        self._add_unit(_row(
            "Hardening",
            self._hardening(service)))
        self._add_unit(_row(
            "System call filter",
            "Not set - the unit ships the filter lines commented out, so the "
            "syscall filter this file appears to have is not in effect."))

    def _state_detail(self, payload: dict, key: str) -> str:
        """One `systemctl is-*` answer, or the reason there is not one."""
        word = payload.get(key) or ""
        problem = payload.get(f"{key}_error") or ""
        if word:
            return word
        return problem or self._aggregate_error or "not read"

    @staticmethod
    def _state_icon(payload: dict, key: str) -> str:
        """A summary glyph for one answer; the text beside it is the answer."""
        word = payload.get(key) or ""
        if not word:
            return ICON_ERROR
        if key == "enabled":
            if word.startswith("enabled"):
                return ICON_OK
            return ICON_WARN
        return ICON_OK if word == "active" else ICON_WARN

    @staticmethod
    def _hardening(service: dict) -> str:
        keys = ("ProtectSystem", "ProtectHome", "PrivateTmp", "PrivateDevices",
                "ProtectClock", "ProtectKernelLogs", "ProtectKernelModules",
                "ProtectKernelTunables", "NoNewPrivileges", "ProtectHostname",
                "LockPersonality", "MemoryDenyWriteExecute", "RestrictSUIDSGID",
                "ProcSubset", "RestrictAddressFamilies", "RestrictNamespaces")
        on = [f"{k}={service[k]}" for k in keys if k in service]
        off = [f"{k}=no" for k in ("PrivateUsers", "PrivateNetwork",
                                   "ProtectControlGroups", "RestrictRealtime")
               if service.get(k) == "no"]
        return "; ".join(on + off) or "none stated"

    def _add_unit(self, row: Adw.ActionRow) -> None:
        self._unit.add(row)
        self._unit_rows.append(row)

    def _render_rules(self, payload: dict) -> None:
        self._clear(self._rules, self._rules_rows)
        for directory in payload.get("rules_dirs") or []:
            path = directory.get("path", "")
            if not directory.get("present"):
                self._add_rules(_row(
                    path, "Not there - which is what a machine with no rules "
                          "package looks like"))
                continue
            if directory.get("problem"):
                self._add_rules(_row(path, directory["problem"], ICON_ERROR))
                continue
            tally = directory.get("tally") or {}
            named = [f"{count} {key}" for key, count in tally.items() if count]
            unparsed = directory.get("unparsed") or 0
            tail = ("directives: " + ", ".join(named)) if named else \
                ("no directive in RULE_KEYS is used by any rule"
                 if directory.get("rules") else "no rules")
            if unparsed:
                tail += (f"; {unparsed} rule"
                         f"{'s' if unparsed != 1 else ''} not readable as JSON, "
                         f"so their directives are unknown")
            self._add_rules(_row(
                path, f"{len(directory['files'])} rules file"
                      f"{'' if len(directory['files']) == 1 else 's'}, "
                      f"{directory.get('rules', 0)} rule"
                      f"{'s' if directory.get('rules') != 1 else ''} - {tail}",
                ICON_OK if directory.get("rules") else ICON_WARN))
            for entry in directory.get("files") or []:
                if not entry.get("read"):
                    self._add_rules(_row(
                        entry["name"],
                        f"{path}/{entry['name']} could not be read: "
                        f"{entry.get('problem', '')}", ICON_ERROR))
                    continue
                keys = [k for k, c in (entry.get("tally") or {}).items() if c]
                self._add_rules(_row(
                    f"{path}/{entry['name']}",
                    f"{entry['rules']} rule"
                    f"{'s' if entry['rules'] != 1 else ''}, {entry['bytes']} "
                    f"bytes - "
                    + (", ".join(keys) if keys
                       else "no directive in RULE_KEYS is used")))

    def _add_rules(self, row: Adw.ActionRow) -> None:
        self._rules.add(row)
        self._rules_rows.append(row)

    def _render_config(self, payload: dict) -> None:
        self._clear(self._config, self._config_rows)
        config = payload.get("config") or {}
        parsed = config.get("parsed") or {}
        if not config.get("present"):
            self._add_config(_row(
                config.get("path", CONFIG_FILE),
                "Not there. The ananicy-cpp package ships /etc/ananicy.d as an "
                "empty directory and does not create this file.", ICON_WARN))
            return
        if not config.get("readable"):
            self._add_config(_row(config.get("path", CONFIG_FILE),
                                  "Could not be read: "
                                  f"{parsed.get('problem', '')}", ICON_ERROR))
            return
        if not parsed.get("ok"):
            self._add_config(_row(config.get("path", CONFIG_FILE),
                                  parsed.get("problem", ""), ICON_ERROR))
            return

        self._add_config(_row(
            "Keys in the file", ", ".join(parsed.get("keys") or []) or "none",
            ICON_OK))
        switches = parsed.get("apply") or {}
        for key in APPLY_KEYS:
            if key in switches:
                value = switches[key]
                self._add_config(_row(
                    key, f"{value}", ICON_OK if _truthy(value) else ICON_WARN))
            else:
                # The daemon's own default for an absent key is not in the file,
                # so it is not stated here.
                self._add_config(_row(
                    key, "Not set in this file", ICON_WARN))
        for key, value in sorted((parsed.get("other") or {}).items()):
            self._add_config(_row(key, f"{value}"))

    def _add_config(self, row: Adw.ActionRow) -> None:
        self._config.add(row)
        self._config_rows.append(row)

    def _render_dump(self, payload: dict) -> None:
        self._clear(self._dump, self._dump_rows)
        if not payload.get("dump_installed"):
            self._add_dump(_row(
                "ananicy-cpp", "Not installed, so it cannot be asked", ICON_WARN))
            return
        if payload.get("dump_error"):
            self._add_dump(_row(
                "ananicy-cpp dump rules", payload["dump_error"], ICON_WARN))
            return
        lines = payload.get("dump") or []
        if not lines:
            self._add_dump(_row(
                "ananicy-cpp dump rules",
                "It printed nothing. It reads the running daemon's shared "
                "memory segment, so with no daemon there is nothing to dump - "
                "which is not the same as the daemon having no rules.",
                ICON_WARN))
            return
        self._add_dump(_row(
            f"{len(lines)} line"
            f"{'' if len(lines) == 1 else 's'} from ananicy-cpp dump rules",
            "Shown as the daemon printed it; this page does not parse it into "
            "a shape of its own.", ICON_OK))
        for line in lines:
            self._add_dump(_row(line[:120], ""))

    def _add_dump(self, row: Adw.ActionRow) -> None:
        self._dump.add(row)
        self._dump_rows.append(row)

    def _render_cgroup(self, payload: dict) -> None:
        self._clear(self._cgroup, self._cgroup_rows)
        cgroup = payload.get("controllers") or {}
        if not cgroup.get("read"):
            self._add_cgroup(_row(
                cgroup.get("path", CGROUP_CONTROLLERS),
                "Could not be read: " + str(cgroup.get("problem", "")),
                ICON_ERROR))
            return
        controllers = cgroup.get("controllers") or []
        if not controllers:
            self._add_cgroup(_row(
                cgroup.get("path", CGROUP_CONTROLLERS),
                "Empty, which is what an unreadable controller list looks like; "
                "no controller is reported as present on that basis.",
                ICON_WARN))
            return
        self._add_cgroup(_row(
            "Controllers delegated here", ", ".join(controllers), ICON_OK))
        needed = cgroup.get("needed") or []
        missing = cgroup.get("missing") or []
        if missing:
            self._add_cgroup(_row(
                "Controllers ananicy-cpp needs",
                f"{', '.join(needed) or 'none'} present; "
                f"{', '.join(missing)} missing. The daemon's own strings say it "
                f"skips cgroup work when the cpu controller is unavailable.",
                ICON_WARN))
        else:
            self._add_cgroup(_row(
                "Controllers ananicy-cpp needs",
                f"{', '.join(needed)} present, so its cgroup work is not "
                f"skipped for want of them.", ICON_OK))

    def _add_cgroup(self, row: Adw.ActionRow) -> None:
        self._cgroup.add(row)
        self._cgroup_rows.append(row)

    def _render_journal(self, payload: dict) -> None:
        self._clear(self._journal, self._journal_rows)
        if payload.get("journal_error"):
            self._add_journal(_row(
                "Could not be read", payload["journal_error"], ICON_ERROR))
            return
        journal = payload.get("journal") or {}
        if journal.get("empty"):
            self._add_journal(_row(
                "No entries",
                "journalctl answered '-- No entries --' on stdout and exited 0, "
                "which means this unit has not logged anything on this machine.",
                ICON_WARN))
            return
        lines = journal.get("lines") or []
        self._add_journal(_row(
            f"{len(lines)} most recent line"
            f"{'' if len(lines) == 1 else 's'}", "", ICON_OK))
        for line in lines:
            self._add_journal(_row(line[:160], ""))

    def _add_journal(self, row: Adw.ActionRow) -> None:
        self._journal.add(row)
        self._journal_rows.append(row)


def _truthy(value: object) -> bool:
    """Is a config switch on? Ananicy's switches are `on`/`off`.

    Recognised as the two words the binary carries, plus a real boolean, and
    nothing else: a value this page does not recognise reads as *off* in the
    icon and as its own printed value in the subtitle, so the text is never
    lost - it is the glyph that is a summary.
    """
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("on", "true", "yes", "1")