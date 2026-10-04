"""Kernel lockdown, and what sbctl does and does not tell you about it.

**The premise this page had to be corrected against, and the correction is the
page.** It was built to "report kernel lockdown state via sbctl". Measured on the
real Arch `sbctl` 0.18-2 package (extracted from `shani-pkgbuilds/cache/
pacman_cache/pkg/sbctl-0.18-2-x86_64.pkg.tar.zst` and run):

    $ sbctl status --json
    {
      "installed": false,
      "guid": "",
      "setup_mode": false,
      "secure_boot": false,
      "vendors": [
        "microsoft"
      ],
      "firmware_quirks": []
    }

Six fields, and **not one of them is kernel lockdown**. `strings` over the
10.8 MB binary finds **zero** occurrences of the word `lockdown`; the four rows
`sbctl status` prints without `--json` are `Installed`, `Setup Mode`, `Secure
Boot` and `Vendor Keys`, all of them firmware facts. So the tool named after this
page cannot answer the question the page is named for, and a page that presented
sbctl's output as the lockdown state would be reporting something else under this
page's name. The lockdown answer therefore comes from the kernel's own file, and
sbctl's answer is shown as sbctl's answer, in its own group, with a row saying
out loud that it has no lockdown field.

**The kernel's answer is one file, and its shape was measured rather than
assumed.** `/sys/kernel/security/lockdown` on this machine reads, `cat -A`:

    [none] integrity confidentiality$

The available modes, with the one in force in square brackets. A parser that took
the first token as the answer would report `none` on a machine whose kernel is in
`confidentiality` mode - which is the exact inversion that matters, because the
first mode is also the one that means "off". The bracketed token is the answer and
the whole line is shown verbatim beside it.

**Three answers that are not one answer.** Whether the kernel has lockdown
compiled in (the file exists), which mode is in force (the bracketed token), and
what the boot asked for (`lockdown=` on `/proc/cmdline`) are separate facts, and
two of the four states of this page are "the kernel has it and is not using it"
and "the kernel does not have it". A kernel without the feature is **not** a
kernel with the feature switched off, and only the first is reported by the
absence of a file - so a page that read a missing file as `none` would tell a
user their kernel cannot be locked down when it can, and vice versa.

**`lsm=` is not `lockdown=`, and a substring search cannot tell them apart.**
`lockdown` appears inside `lsm=landlock,lockdown,yama,integrity,apparmor,bpf`
- that is the list Shanios asks for - so `"lockdown" in cmdline` is true on a
machine that requested nothing. The request is read token by token, and
`tests/test_sbctl_page.py` pins the case with a cmdline that has an `lsm=` and no
`lockdown=`.

**sbctl's absent-or-present is a first-class state, and on Shanios it is the
likely one - but not for the reason this page expected.** Measured:

* `shani-pkgbuilds/shani-core/PKGBUILD:25` **does** declare `sbctl`, in a
  `# Secure Boot` group beside `shim-signed`, `efibootmgr`, `mokutil`,
  `sbsigntool` and `efitools`, and all five desktop profiles install
  `shani-core` (`image_profiles/*/Packages-Base:5`). So sbctl is a *declared*
  Shanios dependency, not a third-party package Shanios refuses.
* Nothing in the ecosystem calls it. `grep -rn sbctl` over `shani-pkgbuilds`,
  `shani-settings` and `shani-deploy` matches that one dependency line and
  nothing else. `gen-efi.sh:39`'s required-tools list is `blkid dracut sbsign
  sbverify bootctl ls grep sort tail awk mkdir cat cryptsetup stat btrfs lsblk
  findmnt df` - **no sbctl** - and MOK enrolment goes through
  `mokutil --generate-hash=shanios` / `mokutil --import` (`gen-efi.sh:263`,
  `:270`, `:783`, `:795`, `:811`). **gen-efi and mokutil are Shanios's Secure
  Boot system of record; sbctl is not**, and this page says so in a group of its
  own rather than letting a green tick from a tool nothing else consults read as
  the state of the enrolled keys.
* In the one built rootfs on this machine
  (`shani-install-media/cache/temp/gnome/x86_64/airootfs`) sbctl is **absent**:
  no `usr/bin/sbctl`, and no entry in `var/lib/pacman/local`. Neither are
  `mokutil`, `sbsigntool` or `efitools`, while `shim-signed`, `edk2-shell` and
  `efibootmgr` are present. That directory is an **intermediate stage, not a
  booted image** - 417 packages, no `systemd`, no desktop shell - so the honest
  claim is bounded to exactly that: the package is declared, and it was not in
  the rootfs that was on disk.

So "sbctl is not installed" is rendered as a state with its own wording, and
never as a read that failed. The lockdown rows above it are answered either way.

**sbctl puts its warning on stderr, which is why this page asks for JSON.**
Measured with the streams split:

    $ sbctl status 2>/dev/null
    Installed:   sbctl is not installed      <- the tick/cross glyphs are U+2713/U+2717
    Setup Mode:    Disabled
    Secure Boot:   Disabled
    Vendor Keys: microsoft
    $ sbctl status 2>&1 1>/dev/null
    old configuration detected. Please use `sbctl setup --migrate`

Every row is `Label:` + **TAB** + glyph + space + value, and the migration
warning is on **stderr** with stdout still valid JSON (both verified by piping
`--json` on stdout alone into `json.load`, which succeeded). A merged-stream
reader would have failed to parse the JSON and reported "no lockdown", i.e. the
warning would have become the answer. `ss.run_json()` keeps the streams apart, so
`status --json` is the one read this page makes.

**Read-only, and the whole page is a consequence of that.** Lockdown's mode is
chosen by a kernel command-line parameter and takes effect at boot; there is no
runtime switch, so a page that could change it would be a page editing a boot
entry. The only argv this module can build is `[sbctl, status, --json]`, and
`status` is the one subcommand that reads. Nothing here writes to
`/sys/kernel/security/lockdown` (which would need root and would still be undone
at the next boot), enrols a key, or signs anything.

**What is *not* verified here.** The `lockdown=` command-line parameter name is
the kernel's own, but no machine available to this session had one on its cmdline
(`/proc/cmdline` here is `BOOT_IMAGE=/vmlinuz-7.0.0-34-generic
root=/dev/mapper/ubuntu--vg-ubuntu--lv ro quiet splash vt.handoff=7`), so that
name is asserted, not measured; the modes themselves are read from the file
rather than from any documentation. Whether **Arch's** kernel builds lockdown in
is also unmeasured: the `linux` package in the cache ships no `config` file, its
`modules.builtin` has no security entries, and `/boot/vmlinuz-*` on this host is
mode 0600. This page does not care - it reports whatever the running kernel
publishes, and "no lockdown support" is one of its states.
"""

from __future__ import annotations

import logging
import os
import re
from typing import Callable, Final, Optional

from gi.repository import Adw, GLib, Gtk  # noqa: F401  (Gtk.Box is the page base)

from shani_cassini import system_status as ss

logger = logging.getLogger(__name__)

# The tool. Arch's `extra` package `sbctl 0.18-2`, whose .PKGINFO names
# github.com/Foxboron/sbctl and an Arch packager.
SBCTL: Final = "sbctl"

# The kernel's own answers. Module constants rather than literals inside the
# reader, so a test can point the reader at a tree it owns - a test cannot create
# an entry in the real /sys.
SECURITYFS_PATH: Final = "/sys/kernel/security"
LOCKDOWN_PATH: Final = "/sys/kernel/security/lockdown"
LSM_PATH: Final = "/sys/kernel/security/lsm"
CMDLINE_PATH: Final = "/proc/cmdline"

# The section this page would register as. Not registered: adding a section is a
# human's call (AGENTS.md, Boundaries), and `tests/test_sbctl_page.py` fails the
# day it is, so the two cannot drift apart quietly.
SLUG: Final = "sbctl"

# Verified present in this host's Adwaita theme through
# `Gtk.IconTheme.get_for_display(...).has_icon()`, and present in Arch's
# `adwaita-icon-theme 50.0-1` package, whose file list contains
# `usr/share/icons/Adwaita/symbolic/status/system-lock-screen-symbolic.svg`.
# Not one of the icons already in use in `notebook.SECTIONS`, where
# `security-high-symbolic` appears four times.
ICON: Final = "system-lock-screen-symbolic"

# sbctl's six fields, in the order its JSON printed them.
SBCTL_FIELDS: Final[tuple[str, ...]] = (
    "installed", "guid", "setup_mode", "secure_boot", "vendors",
    "firmware_quirks",
)

SUMMARY_NOTE = (
    "Read-only. This reports the kernel's own lockdown state, and what sbctl "
    "says about the firmware's Secure Boot setup when sbctl happens to be "
    "installed.\n"
    "It changes nothing. The lockdown mode is chosen by a kernel command-line "
    "parameter and takes effect at boot, and this page offers no control for it."
)

LOCKDOWN_NOTE = (
    "Lockdown is a kernel feature that refuses kernel, module and firmware "
    "operations once it is in a stricter mode. Three separate answers, kept "
    "apart here: whether this kernel has the feature at all, which mode is in "
    "force now, and what the boot asked for.\n"
    "A kernel without lockdown support and a kernel with lockdown support that "
    "is switched off are different machines, and only the first of them is "
    "reported by a file being absent."
)

REQUESTED_NOTE = (
    "What the boot asked for, and the only place on this page a change could "
    "come from. The mode is set by the lockdown parameter on the kernel command "
    "line, so changing it means editing the boot entry and rebooting.\n"
    "The lsm parameter is a different one that also names lockdown. This page "
    "reads the lockdown parameter out of the command line token by token, and "
    "never out of a substring search, because the two cannot be told apart any "
    "other way."
)

SBCTL_NOTE = (
    "What sbctl itself reports about the firmware, field for field and in its "
    "own words. sbctl is a Secure Boot key manager: it holds, creates and signs "
    "Secure Boot keys.\n"
    "sbctl is a separate Arch package. shani-core declares it as a dependency, "
    "and nothing in the ecosystem calls it - see the next group. Its absence is "
    "an ordinary state for this page, not a read that failed."
)

NOT_THE_SYSTEM_OF_RECORD_NOTE = (
    "On Shanios, Secure Boot keys are enrolled by gen-efi using mokutil. "
    "gen-efi's own required-tools list does not name sbctl at all, and a search "
    "of the deploy scripts, the settings overlay and the package builds finds "
    "exactly one reference to it: the dependency line in shani-core.\n"
    "So a machine whose sbctl says Secure Boot is disabled is reporting on "
    "itself and on the firmware. It is not a statement about what the installer "
    "enrolled, and it is not a statement about kernel lockdown, which sbctl does "
    "not report. The Secure Boot page is where the enrolled keys are."
)

SOURCES_NOTE = (
    "  /sys/kernel/security/            whether a lockdown file exists at all\n"
    "  /sys/kernel/security/lockdown    the kernel's own lockdown answer\n"
    "  /sys/kernel/security/lsm         which modules this kernel is running\n"
    "  /proc/cmdline                    what the boot asked for\n"
    "  sbctl status --json              the firmware's Secure Boot state\n"
    "\n"
    "This page starts nothing, writes nothing, and changes no mode."
)

# A bracketed token, or a bare one. `finditer` over the whole line rather than a
# split, so a bracketed run is taken as a unit rather than as several tokens.
_TOKEN = re.compile(r"\[(?P<bracketed>[^\[\]]*)\]|(?P<bare>\S+)")


def _plain(text: object) -> str:
    """Text Pango cannot misread.

    `Adw.ActionRow` parses its title and subtitle as **markup** (its subtitle
    label reports `use_markup = True`), and so does
    `Adw.PreferencesGroup.description`. Two of this page's strings come from the
    machine rather than from here: the kernel's own lockdown line and the whole
    kernel command line, and a command line is free text - a root device named
    `a & b` or an initrd path with a bracket in it would otherwise make GLib
    refuse the assignment.

    Exactly three characters are escaped, `&` first, or the escapes introduced
    afterwards would be escaped a second time. Apostrophes are left alone: they
    are valid markup, and `GLib.markup_escape_text` would turn "the kernel's"
    into an entity for nothing.

    Every string that reaches a row goes through here, and the AST gate in
    `tests/test_sbctl_page.py` proves there is nowhere else one could enter.
    """
    raw = str(text)
    return raw.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _row(title: object, subtitle: object = "") -> Adw.ActionRow:
    """The only place this module builds a row, and so the only way text enters.

    Title and subtitle are escaped here, and the single `set_subtitle()` call
    site in `_on_state` escapes as well. Between the two there is nowhere in this
    module that a string can reach a label unescaped.
    """
    return Adw.ActionRow(title=_plain(title), subtitle=_plain(subtitle))


def parse_lockdown(text: Optional[str]) -> dict:
    """The kernel's lockdown file: the modes on offer, and the one in force.

    The real content, `cat -A`, from this machine::

        [none] integrity confidentiality$

    **The bracket is the whole answer, and reading the first token instead
    inverts the page.** The modes are listed in order and the first is `none`, so
    a parser that returned the first token would say "no lockdown" on a machine
    whose kernel is in `confidentiality` - the strictest mode there is. The
    bracketed token is what the kernel says is in force.

    Three states are kept apart rather than collapsed, because each is a
    different machine:

    * a line with a bracketed mode - the answer;
    * a line with no brackets - this page cannot tell which mode is in force,
      which is **not** the same as saying `none`;
    * an empty read - sysfs never publishes an empty mode list, so an empty file
      means this is not the interface it is pretending to be. Reported as
      unknown rather than guessed.
    """
    raw = (text or "").strip()
    modes: list[str] = []
    active = ""
    for token in _TOKEN.finditer(raw):
        if token.group("bracketed") is not None:
            active = token.group("bracketed").strip()
            modes.append(active)
        else:
            modes.append(token.group("bare"))
    problem = ""
    if not raw:
        problem = "the file is empty, and sysfs never publishes an empty mode list"
    elif not active:
        problem = ("no mode is in brackets, so which one is in force cannot be "
                   "told from this file")
    return {"raw": raw, "modes": modes, "mode": active, "problem": problem}


def parse_lsm(text: Optional[str]) -> list[str]:
    """`/sys/kernel/security/lsm`: the modules this kernel is running.

    The real content, verbatim and **with no trailing newline** - which is
    visible here because `cat` ran the next command's output onto the same line:

        lockdown,capability,landlock,yama,apparmor,ima,evm

    That is what the kernel *accepted*, which is not what the boot asked for;
    `tabs/lsm.py` is the page about that list as a whole, and this page only
    asks whether `lockdown` is in it. An empty read yields an empty list, and the
    caller reports that the question could not be asked rather than concluding
    lockdown is out.
    """
    raw = (text or "").strip()
    return [part.strip() for part in raw.split(",") if part.strip()]


def parse_cmdline_lockdown(text: Optional[str]) -> str:
    """The value of the `lockdown=` parameter, or "" when the boot asked for none.

    Token by token, never a substring search, and the reason is a real shape:
    the `lsm=` parameter also names lockdown, as in the list Shanios asks for,
    `lsm=landlock,lockdown,yama,integrity,apparmor,bpf`. `"lockdown" in
    cmdline` is true on a machine that requested no lockdown at all - which is
    what this host's command line looks like - and a page that reported a request
    from that would be inventing the one input that decides the mode.

    An empty string means "the boot did not ask", never "the mode is none": the
    kernel has its own default, and only the file says which.
    """
    for token in (text or "").split():
        if token.startswith("lockdown="):
            return token[len("lockdown="):].strip()
    return ""


def sbctl_fields(data: Optional[dict]) -> dict:
    """sbctl's six fields, plus the ones this build did not send.

    A missing key is reported as missing rather than defaulted. An earlier shape
    of this helper read `data.get(key)` for all six, so a build that answered with
    three of them produced three rows of `False` and three of "none" - and "Secure
    Boot: No" on a machine where sbctl never said. `missing` is what the page
    shows for those, and it is a real answer.
    """
    if not isinstance(data, dict):
        return {"present": False, "fields": {}, "missing": list(SBCTL_FIELDS)}
    return {
        "present": True,
        "fields": {key: data[key] for key in SBCTL_FIELDS if key in data},
        "missing": [key for key in SBCTL_FIELDS if key not in data],
    }


def _yes_no(value: object) -> str:
    """sbctl's boolean in words, and a refusal for anything that is not one.

    `is True` / `is False` rather than truthiness, so a build that sent the
    string "false", or the number 0, does not become a confident "No". What the
    tool did not say as a boolean is not said at all.
    """
    if value is True:
        return "Yes"
    if value is False:
        return "No"
    return "Not something sbctl reported as a yes or a no"


def _names(value: object) -> str:
    """A list field, and "None reported" for an empty one.

    An empty list is sbctl reporting nothing, so it is rendered as exactly that.
    It is not "there are none": a tool that failed to enumerate its own list and a
    tool that enumerated it and found nothing print the same bytes, and only the
    first is worth a warning.
    """
    if isinstance(value, (list, tuple)):
        items = [str(item) for item in value if str(item).strip()]
        return ", ".join(items) if items else "None reported"
    if value is None:
        return "None reported"
    text = str(value).strip()
    return text if text else "Reported empty by sbctl"


def _read(path: str) -> tuple[str, str]:
    """One file, read directly. Returns `(text, problem)`.

    File reads, not subprocesses, and synchronous on purpose for the same reason
    `system_status.hardware_card()`'s `/proc` reads are: this is a handful of
    bytes from a kernel interface and there is nothing to block on. The problem
    string is empty on success, and carries the reason otherwise - an absent file
    is not an error, so the caller is the one that decides what it means.
    """
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            return handle.read(), ""
    except FileNotFoundError:
        return "", f"{path} does not exist"
    except OSError as exc:
        return "", f"{path}: {exc.strerror or exc}"


def lockdown_state(done: Callable[[dict, str], None]) -> None:
    """Everything this page shows, in one payload. Read-only.

    Four sources, and only one of them is a process:

    * `/sys/kernel/security/` and `/sys/kernel/security/lockdown` - read
      directly, always answerable, and the only source that can say "this kernel
      has no lockdown support";
    * `/sys/kernel/security/lsm` - whether `lockdown` is among the modules this
      kernel is running, which is a different question from whether the feature
      is compiled in;
    * `/proc/cmdline` - what was requested;
    * `sbctl status --json`, **only when sbctl is installed**. Its absence is
      delivered as a value, not as an error, because on Shanios it is an ordinary
      state: the package is declared by `shani-core` and called by nothing.

    `done(payload, error)` takes two arguments, as every reader here must: a
    reader that hands its callback one raises `TypeError` *inside* a GTK
    callback, GLib swallows it, and the page renders nothing with nothing in the
    log.
    """
    lockdown_text, lockdown_problem = _read(LOCKDOWN_PATH)
    parsed = parse_lockdown(lockdown_text)
    if not lockdown_problem and not os.path.isdir(SECURITYFS_PATH):
        lockdown_problem = f"{SECURITYFS_PATH} is not a directory"

    lsm_text, lsm_problem = _read(LSM_PATH)
    active_modules = parse_lsm(lsm_text)

    cmdline, cmdline_problem = _read(CMDLINE_PATH)

    payload: dict = {
        "lockdown_path": LOCKDOWN_PATH,
        "securityfs_present": os.path.isdir(SECURITYFS_PATH),
        "lockdown_problem": lockdown_problem,
        "lockdown": parsed,
        "lsm_readable": not lsm_problem and bool(active_modules),
        "lsm_problem": lsm_problem,
        "lsm": active_modules,
        "lockdown_in_lsm": "lockdown" in active_modules,
        "cmdline": cmdline.strip(),
        "cmdline_problem": cmdline_problem,
        "requested": parse_cmdline_lockdown(cmdline),
        "sbctl_installed": ss.have_tool(SBCTL),
        "sbctl": {"present": False, "fields": {}, "missing": list(SBCTL_FIELDS)},
        "sbctl_error": "",
    }
    if not payload["sbctl_installed"]:
        # An absent sbctl is a state, and this page is written so that every
        # other row above is already in the payload by the time this returns.
        done(payload, "")
        return

    def got(data: Optional[dict], err: str) -> None:
        if err:
            # sbctl was on PATH and could not answer. That is a fact about this
            # read, and it is kept apart from the tool being absent - the two
            # have very different words and a user reads them differently.
            payload["sbctl_error"] = err
        else:
            payload["sbctl"] = sbctl_fields(data)
        done(payload, err)

    ss.run_json([ss.tool_path_or_self(SBCTL), "status", "--json"], got)


class SbctlTab(Gtk.Box):
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
            title="Kernel lockdown", description=_plain(SUMMARY_NOTE))
        self._row_state = _row("Reading", "Reading the kernel's lockdown state")
        self._summary.add(self._row_state)
        self._page.append(self._summary)

        self._kernel = Adw.PreferencesGroup(
            title="What the kernel says", description=_plain(LOCKDOWN_NOTE))
        self._kernel_rows: list[Adw.ActionRow] = []
        self._page.append(self._kernel)

        self._requested = Adw.PreferencesGroup(
            title="What the boot asked for",
            description=_plain(REQUESTED_NOTE))
        self._requested_rows: list[Adw.ActionRow] = []
        self._page.append(self._requested)

        self._sbctl = Adw.PreferencesGroup(
            title="What sbctl reports", description=_plain(SBCTL_NOTE))
        self._sbctl_rows: list[Adw.ActionRow] = []
        self._page.append(self._sbctl)

        self._page.append(Adw.PreferencesGroup(
            title="What this is not",
            description=_plain(NOT_THE_SYSTEM_OF_RECORD_NOTE)))
        self._page.append(Adw.PreferencesGroup(
            title="Where this comes from", description=_plain(SOURCES_NOTE)))

    def load(self) -> bool:
        lockdown_state(self._on_state)
        return False

    def _on_state(self, payload: dict, err: str) -> None:
        self._row_state.set_title(_plain(self._verdict(payload)))
        self._row_state.set_subtitle(_plain(self._verdict_detail(payload)))

        self._clear(self._kernel, self._kernel_rows)
        for title, subtitle in self._kernel_rows_for(payload):
            row = _row(title, subtitle)
            self._kernel.add(row)
            self._kernel_rows.append(row)

        self._clear(self._requested, self._requested_rows)
        for title, subtitle in self._requested_subtitles(payload):
            row = _row(title, subtitle)
            row.set_subtitle_selectable(True)
            self._requested.add(row)
            self._requested_rows.append(row)

        self._clear(self._sbctl, self._sbctl_rows)
        for title, subtitle in self._sbctl_subtitles(payload):
            row = _row(title, subtitle)
            self._sbctl.add(row)
            self._sbctl_rows.append(row)

    # -- the one line that says which machine this is ------------------------

    def _verdict(self, payload: dict) -> str:
        lockdown = payload.get("lockdown") or {}
        mode = lockdown.get("mode") or ""
        if payload.get("lockdown_problem"):
            return "The kernel publishes no lockdown state"
        if not mode:
            return "The kernel's lockdown file could not be read as a mode"
        if mode == "none":
            return "Lockdown is available and switched off"
        return f"Lockdown is on, in {mode} mode"

    def _verdict_detail(self, payload: dict) -> str:
        lockdown = payload.get("lockdown") or {}
        modes = lockdown.get("modes") or []
        problem = lockdown.get("lockdown_problem") or lockdown.get("problem") or ""
        mode = lockdown.get("mode") or ""
        offered = ", ".join(modes)

        if payload.get("lockdown_problem"):
            return (f"{payload['lockdown_problem']}. A kernel publishing no "
                    f"lockdown state is not the same as lockdown being off: "
                    f"there is nothing here to switch on")
        if problem:
            return f"{problem} - the file said: {offered or 'nothing'}"
        if mode == "none":
            return (f"This kernel offers {offered} and is in none of them. "
                    f"Switching it on is a kernel command-line parameter and a "
                    f"reboot, which is why there is no control on this page")
        if mode == "integrity":
            return (f"This kernel offers {offered} and is refusing kernel, "
                    f"module and firmware operations at the integrity level")
        if mode == "confidentiality":
            return (f"This kernel offers {offered} and is refusing them at the "
                    f"confidentiality level, the last of the modes it lists")
        return (f"The kernel reports a lockdown mode this page has no name for: "
                f"{mode}. The modes it offers are {offered}")

    # -- the kernel's own group ---------------------------------------------

    def _kernel_rows_for(self, payload: dict) -> list[tuple[str, str]]:
        lockdown = payload.get("lockdown") or {}
        rows: list[tuple[str, str]] = []

        if payload.get("lockdown_problem"):
            rows.append((
                "Kernel lockdown support",
                f"{payload['lockdown_problem']}. Either this kernel was built "
                f"without it or securityfs is not mounted here; the two are not "
                f"distinguishable from this file, and neither is the same as "
                f"lockdown being switched off"))
        else:
            rows.append((
                "Modes the kernel offers",
                lockdown.get("raw") or "the file is empty"))
            rows.append((
                "Mode in force",
                self._mode_row_subtitle(lockdown)))

        if payload.get("lsm_readable"):
            listed = ", ".join(payload.get("lsm") or [])
            if payload.get("lockdown_in_lsm"):
                rows.append((
                    "lockdown in the running module list",
                    f"Yes - /sys/kernel/security/lsm names it. The list is "
                    f"{listed}"))
            else:
                rows.append((
                    "lockdown in the running module list",
                    f"No - the kernel is running {listed}, and lockdown is not "
                    f"among them"))
        else:
            rows.append((
                "lockdown in the running module list",
                f"Could not be read "
                f"({payload.get('lsm_problem') or 'the file is empty'}), so "
                f"whether this kernel is running lockdown as a module is "
                f"unknown - which is not the same as it being out"))

        rows.append((
            "The file this page reads",
            f"{payload.get('lockdown_path')} - the kernel's own answer, read "
            f"directly, with no tool and no password"))
        return rows

    def _mode_row_subtitle(self, lockdown: dict) -> str:
        problem = lockdown.get("problem") or ""
        mode = lockdown.get("mode") or ""
        if problem:
            return (f"{problem}. The kernel's own line is "
                    f"\"{lockdown.get('raw')}\" and nothing in it is in force, "
                    f"so the mode is unknown rather than off")
        if mode == "none":
            return ("none - the feature is here and is not being used. Only the "
                    "bracketed mode counts: the first token of this line is "
                    "also none, and on a locked machine it is not")
        if mode in ("integrity", "confidentiality"):
            return (f"{mode} - the kernel is refusing the operations this mode "
                    f"refuses. Which operations those are is the kernel's own "
                    f"policy and this page does not enumerate them")
        return f"{mode} - a mode this page has no name for, reported as it stands"

    # -- what the boot asked for --------------------------------------------

    def _requested_subtitles(self, payload: dict) -> list[tuple[str, str]]:
        requested = payload.get("requested") or ""
        rows: list[tuple[str, str]] = []
        if requested:
            rows.append((
                "Lockdown requested",
                f"lockdown={requested} - the boot asked for this mode, and the "
                f"row above says what the kernel is actually running"))
        else:
            rows.append((
                "Lockdown requested",
                "No lockdown parameter on the kernel command line, so the boot "
                "asked for nothing and the kernel used its own default. That is "
                "not the same as asking for none"))
        rows.append((
            "The kernel command line",
            payload.get("cmdline")
            or (payload.get("cmdline_problem") or "could not be read")))
        return rows

    # -- what sbctl says -----------------------------------------------------

    def _sbctl_subtitles(self, payload: dict) -> list[tuple[str, str]]:
        rows: list[tuple[str, str]] = []
        if not payload.get("sbctl_installed"):
            rows.append((
                "sbctl",
                "Not installed, so there is nothing for it to report. This is "
                "not a read that failed and it does not affect any row above: "
                "the kernel answers those on its own"))
            return rows

        rows.append((
            "sbctl",
            "Installed, and what follows is its own answer about the firmware. "
            "It is not what manages Secure Boot on Shanios - gen-efi and "
            "mokutil are"))

        state = payload.get("sbctl") or {}
        if payload.get("sbctl_error"):
            rows.append((
                "sbctl status",
                f"sbctl is installed and did not answer: "
                f"{payload['sbctl_error']}"))
            return rows

        fields = state.get("fields") or {}
        missing = state.get("missing") or []
        if missing:
            rows.append((
                "Fields this build did not send",
                f"{', '.join(missing)} - sbctl answered without them, so they "
                f"are shown as unanswered rather than as a value"))
        rows.append((
            "Kernel lockdown, in sbctl's answer",
            "sbctl has no such field. Its status reports installed, guid, "
            "setup_mode, secure_boot, vendors and firmware_quirks, and says "
            "nothing about the kernel's lockdown mode - which is why the rows "
            "above come from the kernel"))
        rows.append((
            "Secure Boot",
            f"{_yes_no(fields.get('secure_boot'))} - sbctl's answer about the "
            f"firmware setting, not about the keys Shanios enrolled"))
        rows.append((
            "Setup Mode",
            f"{_yes_no(fields.get('setup_mode'))} - whether the firmware is in "
            f"its setup mode"))
        rows.append((
            "Vendor keys",
            _names(fields.get("vendors"))))
        rows.append((
            "Firmware quirks",
            _names(fields.get("firmware_quirks"))))
        rows.append((
            "GUID",
            f"{_names(fields.get('guid'))} - sbctl's own field, shown as it "
            f"filled it in and not interpreted"))
        rows.append((
            "sbctl's own installed field",
            f"{_yes_no(fields.get('installed'))} - sbctl's opinion about its "
            f"own setup. It answers this field whether or not the package is "
            f"installed, which was measured by running an sbctl taken out of a "
            f"package file with nothing set up"))
        return rows

    @staticmethod
    def _clear(group: Adw.PreferencesGroup,
               rows: list[Adw.ActionRow]) -> None:
        """Empty a group, and forget the rows the page is tracking for it.

        Without this a second read appended the same rows again: the page is
        rendered once per read, and the tell of that is a *duplication* - the
        mirror of this repo's more usual "a row was built and never given a
        parent". `group.remove()` takes a row, not whatever `get_first_child()`
        happens to return, so the rows are tracked rather than walked.
        """
        for row in rows:
            group.remove(row)
        rows.clear()
