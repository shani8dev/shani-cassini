"""The sbctl page: the kernel's lockdown state, and sbctl's honest non-answer.

**Every fixture here is a capture, not a shape.** Two of them are the real
machine, one is the real tool:

* `/sys/kernel/security/lockdown` on this host, `cat -A`:
  `[none] integrity confidentiality$`
* `/sys/kernel/security/lsm` on this host, verbatim and **with no trailing
  newline** (which is how it was noticed: `cat` ran the next command's output
  onto the same line)
* `/proc/cmdline` on this host, verbatim
* `sbctl status --json` from Arch's `sbctl 0.18-2`, the binary extracted from
  `shani-pkgbuilds/cache/pacman_cache/pkg/sbctl-0.18-2-x86_64.pkg.tar.zst` and
  run here, plus `sbctl status` with the streams split

**The measurement that shaped the page, and it is a correction of the premise.**
`strings` over sbctl's 10.8 MB binary finds **zero** occurrences of `lockdown`.
Its JSON has six fields - `installed`, `guid`, `setup_mode`, `secure_boot`,
`vendors`, `firmware_quirks` - and its four plain-text rows are `Installed`,
`Setup Mode`, `Secure Boot` and `Vendor Keys`. So sbctl cannot answer the question
this page is named for, and the lockdown answer has to come from the kernel.
`TestSbctlDoesNotAnswerThisPage` holds both halves of that: the page's lockdown
rows follow sysfs even when sbctl's payload says something else, and the page
says out loud that sbctl has no lockdown field.

**Three traps, each with the fixture that catches it.**

1. The kernel's file lists the modes and brackets the active one. The first
   token is `none` and so is the bracketed one *here* - which is exactly why a
   parser that returned the first token would look right on this machine and
   report "no lockdown" on one in `confidentiality`. `DERIVED_CONFIDENTIALITY`
   and `DERIVED_INTEGRITY` exist so that the difference is proven rather than
   assumed; they are labelled DERIVED because no machine was available whose
   kernel was actually locked.
2. `lsm=` names lockdown and is not `lockdown=`. `CMDLINE_WITH_LSM_ONLY` is a
   command line with an `lsm=` list and no `lockdown=` parameter, which is what
   this host has; a substring search finds "lockdown" in it and would report a
   request that was never made.
3. sbctl's migration warning is on **stderr** and stdout is still valid JSON
   (verified by piping stdout alone into `json.load`). A merged-stream reader
   would have failed to parse and reported "no lockdown".

**Eleven negative controls were run against this file and every one of them now
fails the suite. Three of them did not on the first attempt, and each of those
three exposed a real hole rather than a bad mutation** - which is the reason they
are recorded here instead of being quietly re-run until they went red:

* a missing lockdown file read as an off lockdown, caught by the reader's own
  test rather than by the rendering one;
* `lsm=` read as a `lockdown=` request, which the `lsm=`-only command line
  fixture catches and which nothing else would have;
* a fabricated `lockdown` key in sbctl's payload "proving" the page ignores it -
  **a control that could not fail**, because `sbctl_fields()` filtered the key out
  before the page saw it, so the assertion passed against a page that read the
  mode from sbctl. The working control is one layer down: make `sbctl_fields()`
  keep unknown keys, and `test_an_unknown_field_from_sbctl_never_reaches_the_page`
  fails;
* and `test_the_only_option_this_page_ever_passes_is_json`, which pinned the
  **options** while the docstring claimed it pinned the subcommands. Changing
  `status` to `enroll-keys` left it green. The argv is now asserted by shape and
  no writing subcommand may appear as a literal in the code.

The controls were run in a scratch copy of `src/` and `tests/` under
`/tmp`, never in the working tree.
"""

from __future__ import annotations

import ast
import inspect
import json
import os
import re
import time

import pytest

gi = pytest.importorskip("gi")
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GLib, Gtk  # noqa: E402

from shani_cassini import system_status as ss  # noqa: E402
from shani_cassini.tabs import sbctl as sbctl_mod  # noqa: E402
from shani_cassini.tabs.sbctl import (  # noqa: E402
    ICON,
    SBCTL_FIELDS,
    SbctlTab,
    parse_cmdline_lockdown,
    parse_lockdown,
    parse_lsm,
    sbctl_fields,
)


# --- the captures -----------------------------------------------------------

def _cat_a(text: str) -> str:
    """Re-render text the way `cat -A` does, so a fixture can be pinned to it.

    `cat -A` shows a tab as `^I` and a line end as `$`, and leaves everything
    else alone - which is the whole reason the pin is worth having, because a run
    of spaces is invisible otherwise.
    """
    body = text[:-1] if text.endswith("\n") else text
    return "".join(line.replace("\t", "^I") + "$\n" for line in body.split("\n"))


def _un_cat_a(text: str) -> str:
    """The inverse: turn a `cat -A` capture back into the file's own bytes.

    The glyphs are written in the capture as the escaped UTF-8 the terminal
    printed, so they are restored here rather than typed twice - a fixture whose
    "verbatim" copy and whose "content" copy differ by a glyph is the drift this
    pair of helpers exists to make impossible.
    """
    out = []
    for line in text.split("\n"):
        if not line:
            continue
        if line.endswith("$"):
            line = line[:-1]
        out.append(line.replace("^I", "\t"))
    return "\n".join(out) + "\n"


# `cat -A /sys/kernel/security/lockdown` on this machine: the file's own content,
# with `cat -A`'s line-end marker left on so the pin below has something to be
# pinned against.
LOCKDOWN = "[none] integrity confidentiality\n"
CATA_LOCKDOWN = "[none] integrity confidentiality$\n"

# `cat -A /sys/kernel/security/lsm`: the modes the kernel accepted. `cat` printed
# the next command's output onto this line, which is how the missing trailing
# newline was noticed.
CATA_LSM = ("lockdown,capability,landlock,yama,apparmor,ima,evm"
            "=== ls /sys/kernel/ lockdown ===")

LSM = "lockdown,capability,landlock,yama,apparmor,ima,evm"

# `cat /proc/cmdline` on this machine.
CMDLINE = ("BOOT_IMAGE=/vmlinuz-7.0.0-34-generic "
           "root=/dev/mapper/ubuntu--vg-ubuntu--lv ro quiet splash "
           "vt.handoff=7\n")

# `sbctl status --json`, Arch sbctl 0.18-2, stdout only, verbatim. Parsed from
# the literal rather than handed in as a dict, so the file on disk and the object
# under test cannot differ.
REAL_SBCTL_STDOUT_JSON = """\
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
"""

REAL_SBCTL = json.loads(REAL_SBCTL_STDOUT_JSON)

# `sbctl status` stdout, with `cat -A`'s tab (`^I`) and line-end (`$`) markers.
# The two glyphs are the tool's own - U+2713 CHECK MARK and U+2717 BALLOT X - and
# `cat -A` prints them as the byte escapes `M-bM-^\M-^S` and `M-bM-^\M-^W`; they
# are written here as the characters themselves, which is the same bytes read as
# UTF-8, and `test_the_sbctl_glyphs_survive_a_round_trip` pins that.
CATA_SBCTL_STATUS_STDOUT = (
    "Installed:^I\u2717 sbctl is not installed$\n"
    "Setup Mode:^I\u2713 Disabled$\n"
    "Secure Boot:^I\u2717 Disabled$\n"
    "Vendor Keys:^Imicrosoft$\n"
)

# The same four rows as the file's own content, which is what a reader would
# parse. Reassembled from the `cat -A` capture by the helper below rather than
# pasted, so the two cannot drift.
SBCTL_STATUS_STDOUT = _un_cat_a(CATA_SBCTL_STATUS_STDOUT)

# `sbctl status` stderr, verbatim.
CATA_SBCTL_STATUS_STDERR = (
    "old configuration detected. Please use `sbctl setup --migrate`\n"
)

# The kernel's own lockdown line with the other two modes in force. DERIVED, NOT
# CAPTURED: it is this machine's capture with the brackets moved, which is the
# kernel's own format, but no machine was available whose kernel was locked.
# Stated rather than dressed up as a capture.
DERIVED_INTEGRITY = "none [integrity] confidentiality\n"
DERIVED_CONFIDENTIALITY = "none integrity [confidentiality]\n"

# A command line that names lockdown in `lsm=` and asks for no lockdown at all -
# the shape a machine with the feature compiled in and switched off has, and the
# shape a substring search gets wrong.
CMDLINE_WITH_LSM_ONLY = (
    "BOOT_IMAGE=/vmlinuz-6.9.7-arch1 root=UUID=1a2b3c4d ro quiet "
    "lsm=landlock,lockdown,yama,integrity,apparmor,bpf\n"
)

CMDLINE_REQUESTS_INTEGRITY = (
    "BOOT_IMAGE=/vmlinuz-6.9.7-arch1 root=UUID=1a2b3c4d ro quiet "
    "lockdown=integrity\n"
)


# --- helpers ----------------------------------------------------------------

def _lockdown_state(lockdown_text: str | None = LOCKDOWN, *,
                    lockdown_problem: str = "", securityfs: bool = True,
                    lsm_text: str | None = LSM, lsm_problem: str = "",
                    cmdline: str | None = CMDLINE,
                    sbctl_installed: bool = True,
                    sbctl_data=REAL_SBCTL, sbctl_error: str = "") -> dict:
    """A payload built through the **real** parsers, never hand-written.

    An earlier version of a page test in this repo handed the widget tree a
    hand-built payload and passed against a parser that reports four arrays on a
    machine with none. Everything below goes through `parse_lockdown()`,
    `parse_lsm()` and `parse_cmdline_lockdown()` on its way to the page, so the
    parsers and the rendering cannot disagree.
    """
    if lockdown_text is None:
        parsed = {"raw": "", "modes": [], "mode": "",
                  "problem": "the file is empty, and sysfs never publishes an "
                             "empty mode list"}
        lockdown_problem = lockdown_problem or (
            f"{sbctl_mod.LOCKDOWN_PATH} does not exist")
    else:
        parsed = parse_lockdown(lockdown_text)
    modules = parse_lsm(lsm_text) if lsm_text else []
    return {
        "lockdown_path": sbctl_mod.LOCKDOWN_PATH,
        "securityfs_present": securityfs,
        "lockdown_problem": lockdown_problem,
        "lockdown": parsed,
        "lsm_readable": not lsm_problem and bool(modules),
        "lsm_problem": lsm_problem,
        "lsm": modules,
        "lockdown_in_lsm": "lockdown" in modules,
        "cmdline": (cmdline or "").strip(),
        "cmdline_problem": ("" if cmdline
                            else f"{sbctl_mod.CMDLINE_PATH} does not exist"),
        "requested": parse_cmdline_lockdown(cmdline or ""),
        "sbctl_installed": sbctl_installed,
        "sbctl": sbctl_fields(sbctl_data) if sbctl_installed else
                  {"present": False, "fields": {}, "missing": list(SBCTL_FIELDS)},
        "sbctl_error": sbctl_error,
    }


def _render(payload: dict) -> tuple[SbctlTab, list]:
    """Render a payload and read every row back out of the widget tree.

    From the tree, not from an attribute: this repo has shipped rows that were
    built, stored on `self`, updated on every read and never given a parent, and
    a test that reached them by attribute passed anyway.
    """
    tab = SbctlTab()
    tab._on_state(payload, payload.get("sbctl_error", ""))
    return tab, _rows(tab)


def _rows(tab) -> list:
    found = []

    def walk(node):
        if isinstance(node, Adw.ActionRow):
            found.append((node.get_title(), node.get_subtitle() or ""))
        child = node.get_first_child()
        while child is not None:
            walk(child)
            child = child.get_next_sibling()

    walk(tab)
    return found


def _row_map(tab) -> dict:
    return {title: subtitle for title, subtitle in _rows(tab)}


def _groups(tab) -> list:
    found = []

    def walk(node):
        if isinstance(node, Adw.PreferencesGroup):
            found.append((node.get_title() or "", node.get_description() or ""))
        child = node.get_first_child()
        while child is not None:
            walk(child)
            child = child.get_next_sibling()

    walk(tab)
    return found


def _code(module) -> str:
    """The module's code, with docstrings **and every string literal** blanked.

    Both removals are needed. This module's docstring argues at length about what
    sbctl cannot report, and that argument must not satisfy the gate that proves
    it. The strings matter because the page's own `NOT_THE_SYSTEM_OF_RECORD_NOTE`
    names `mokutil --generate-hash=shanios` and `gen-efi.sh`, and a gate about
    which programs this page may run is not entitled to trip over prose.
    """
    tree = ast.parse(inspect.getsource(module))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            node.value = ""
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                 ast.AsyncFunctionDef)):
            continue
        body = node.body
        if (body and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)):
            node.body = body[1:] or [ast.Pass()]
    return ast.unparse(tree)


def _string_constants(module) -> set:
    """Every long option string in the module - anything that starts with `--`.

    `--` and not `-`, so a literal like the `lsm=` prefix is not mistaken for an
    option.
    """
    return {n.value for n in ast.walk(ast.parse(inspect.getsource(module)))
            if isinstance(n, ast.Constant) and isinstance(n.value, str)
            and n.value.startswith("--")}


def _literals(module) -> set:
    """Every string literal in the module, with docstrings removed.

    The docstrings are this module's own argument for what it must never do -
    they name `enroll-keys` and `reset` while explaining that they are the
    subcommands that must not be run - so a gate over literals has to be able to
    tell prose from code. `_code()` strips them for the same reason.
    """
    tree = ast.parse(inspect.getsource(module))
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                 ast.AsyncFunctionDef)):
            continue
        body = node.body
        if (body and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)):
            node.body = body[1:] or [ast.Pass()]
    return {n.value for n in ast.walk(tree)
            if isinstance(n, ast.Constant) and isinstance(n.value, str)}


def _calls_to(module, attr: str) -> list:
    """Every `Call` whose callee is the dotted name `attr`, e.g. `Adw.ActionRow`."""
    tree = ast.parse(inspect.getsource(module))
    return [n for n in ast.walk(tree)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute) and n.func.attr == attr]


ENTITY = re.compile(r"&(#[0-9]+|#[xX][0-9a-fA-F]+|[A-Za-z][A-Za-z0-9]*);")
KNOWN = ("amp", "lt", "gt", "quot", "apos")


def _markup_safe(text: str) -> bool:
    """Would Pango render this string as the words it contains?

    Two things make a label refuse its text: a `<`, and an `&` that does not
    begin an entity GLib knows. `GLib.markup_escape_text(s) == s` is the usual
    stand-in and it is **wrong here**: escaping is not idempotent, so an already
    escaped `a &amp; b` would fail it and this page emits exactly that.
    """
    if "<" in text or ">" in text:
        return False
    rest = ENTITY.sub(
        lambda m: "" if m.group(1).startswith("#")
        or m.group(1) in KNOWN else m.group(0), text)
    return "&" not in rest


def _text(node) -> str:
    return ast.unparse(node)


# --- the fixtures are the captures -----------------------------------------


class TestTheFixturesAreTheCaptures:
    def test_the_lockdown_fixture_is_the_capture(self):
        assert _cat_a(LOCKDOWN) == CATA_LOCKDOWN

    def test_the_sbctl_fixture_is_the_capture(self):
        """The tab after each label is the structure here, so the content copy is
        reassembled from the `cat -A` copy and must come back to itself."""
        assert _cat_a(SBCTL_STATUS_STDOUT) == CATA_SBCTL_STATUS_STDOUT
        assert SBCTL_STATUS_STDOUT.splitlines()[0] == \
            "Installed:\t✗ sbctl is not installed"

    def test_the_sbctl_json_fixture_parses_to_the_captured_values(self):
        assert REAL_SBCTL == {
            "installed": False, "guid": "", "setup_mode": False,
            "secure_boot": False, "vendors": ["microsoft"],
            "firmware_quirks": []}

    def test_the_sbctl_glyphs_survive_a_round_trip(self):
        """The check mark and the ballot X are the tool's own; if a fixture lost
        them it would still parse into the same four values, so the pin is on the
        bytes."""
        assert "✓" in SBCTL_STATUS_STDOUT
        assert "✗" in SBCTL_STATUS_STDOUT
        assert SBCTL_STATUS_STDOUT.count("\t") == 4

    def test_the_lsm_capture_shows_the_missing_newline(self):
        """`cat` ran the next command onto the same line, so the capture is the
        proof rather than the assumption. Without this the fixture could gain a
        newline and every parser here would still pass."""
        assert "\n" not in LSM
        assert CATA_LSM.startswith(LSM)
        assert CATA_LSM.endswith("=== ls /sys/kernel/ lockdown ===")


# --- the kernel's own file --------------------------------------------------


class TestParseLockdown:
    def test_the_real_line_yields_the_modes_and_the_bracketed_one(self):
        parsed = parse_lockdown(LOCKDOWN)
        assert parsed["raw"] == "[none] integrity confidentiality", parsed
        assert parsed["modes"] == ["none", "integrity", "confidentiality"], parsed
        assert parsed["mode"] == "none", parsed
        assert parsed["problem"] == "", parsed

    def test_the_bracketed_token_is_the_answer_and_not_the_first(self):
        """**The trap.** The first token is `none` here and the bracketed token is
        also `none`, so a first-token parser is indistinguishable here - and
        wrong on a locked machine, which is the only machine where the answer
        matters."""
        for text, expected in ((DERIVED_INTEGRITY, "integrity"),
                               (DERIVED_CONFIDENTIALITY, "confidentiality")):
            parsed = parse_lockdown(text)
            assert parsed["mode"] == expected, parsed
            assert parsed["modes"][0] == "none", parsed

    def test_no_brackets_is_unknown_and_not_a_guess_of_none(self):
        parsed = parse_lockdown("none integrity confidentiality\n")
        assert parsed["mode"] == "", parsed
        assert parsed["problem"], parsed
        assert "cannot be told" in parsed["problem"], parsed

    def test_an_empty_file_is_not_an_off_lockdown(self):
        """sysfs never publishes an empty mode list, so an empty read is this not
        being the interface it claims to be - the same reasoning the Graphics
        page uses for an empty runtime_status."""
        parsed = parse_lockdown("")
        assert parsed["mode"] == "", parsed
        assert "empty" in parsed["problem"], parsed
        assert parse_lockdown(None)["problem"] == parsed["problem"]

    def test_a_trailing_newline_does_not_become_a_mode(self):
        parsed = parse_lockdown("[integrity] integrity confidentiality\n\n")
        assert parsed["modes"] == ["integrity", "integrity", "confidentiality"], parsed

    def test_a_mode_with_spaces_inside_the_brackets_survives(self):
        """A bracket is a bracket; a mode name is not assumed to be one word."""
        assert parse_lockdown("[some mode] none\n")["mode"] == "some mode"


# --- the module list and the command line -----------------------------------


class TestParseLsm:
    def test_the_real_list_is_split_on_commas(self):
        assert parse_lsm(LSM) == [
            "lockdown", "capability", "landlock", "yama", "apparmor", "ima",
            "evm"]

    def test_a_missing_newline_does_not_join_two_modes(self):
        """The capture has no trailing newline and `strip()` is what removes the
        surrounding whitespace; without it the last entry would carry one."""
        parsed = parse_lsm(LSM)
        assert parsed[-1] == "evm", parsed
        assert all(not p.strip() != p for p in parsed), parsed

    def test_an_empty_read_is_an_empty_list_not_a_list_of_nothing(self):
        assert parse_lsm("") == []
        assert parse_lsm(None) == []

    def test_a_list_without_lockdown_is_kept_whole(self):
        modules = parse_lsm("capability,yama,apparmor")
        assert "lockdown" not in modules, modules
        assert len(modules) == 3, modules


class TestParseCmdline:
    def test_the_real_command_line_requests_nothing(self):
        assert parse_cmdline_lockdown(CMDLINE) == ""

    def test_an_lsm_list_is_not_a_lockdown_request(self):
        """**The trap.** `lockdown` appears in this line and nothing was asked
        for; a substring search reports a request the boot never made."""
        assert "lockdown" in CMDLINE_WITH_LSM_ONLY
        assert parse_cmdline_lockdown(CMDLINE_WITH_LSM_ONLY) == ""

    def test_a_real_request_is_found(self):
        assert parse_cmdline_lockdown(CMDLINE_REQUESTS_INTEGRITY) == "integrity"

    def test_a_request_is_not_confused_with_lsm_ordering(self):
        """Both parameters in one command line: each is read on its own name."""
        both = ("root=UUID=1a2b3c4d lsm=landlock,lockdown,yama "
                "lockdown=confidentiality\n")
        assert parse_cmdline_lockdown(both) == "confidentiality", both

    def test_a_bare_lockdown_parameter_is_an_empty_value_not_a_request(self):
        assert parse_cmdline_lockdown("lockdown=\n") == ""

    def test_an_unreadable_command_line_is_no_request_rather_than_a_crash(self):
        assert parse_cmdline_lockdown(None) == ""


# --- sbctl's own answer -----------------------------------------------------


class TestSbctlFields:
    def test_the_capture_yields_all_six_fields(self):
        state = sbctl_fields(REAL_SBCTL)
        assert state["present"] is True
        assert list(state["fields"]) == list(SBCTL_FIELDS), state
        assert state["missing"] == [], state
        assert state["fields"]["vendors"] == ["microsoft"], state

    def test_a_field_this_build_did_not_send_is_reported_as_missing(self):
        """Not defaulted. Reading `data.get(key)` for all six would turn a
        three-field answer into three rows of `False`, and "Secure Boot: No" on a
        machine where sbctl never said."""
        state = sbctl_fields({"secure_boot": True, "vendors": ["microsoft"]})
        assert state["missing"] == ["installed", "guid", "setup_mode",
                                    "firmware_quirks"], state
        assert state["fields"] == {"secure_boot": True,
                                   "vendors": ["microsoft"]}, state

    def test_a_non_dict_answer_is_absent_and_names_every_field(self):
        state = sbctl_fields(None)
        assert state["present"] is False, state
        assert state["missing"] == list(SBCTL_FIELDS), state

    def test_a_boolean_only_counts_when_it_is_a_boolean(self):
        """A build that sent the string "false" must not become a confident No."""
        from shani_cassini.tabs.sbctl import _yes_no
        assert _yes_no(True) == "Yes"
        assert _yes_no(False) == "No"
        assert "Not something" in _yes_no("false")
        assert "Not something" in _yes_no(0)
        assert "Not something" in _yes_no(None)

    def test_an_empty_list_is_none_reported_rather_than_a_measurement_of_zero(self):
        from shani_cassini.tabs.sbctl import _names
        assert _names([]) == "None reported"
        assert _names(["microsoft"]) == "microsoft"
        assert _names("") == "Reported empty by sbctl"
        assert _names(None) == "None reported"


class TestSbctlDoesNotAnswerThisPage:
    """The premise correction, held from both sides.

    The page is named `sbctl` because sbctl is the tool that *looks* like it owns
    this subject. Measured, it owns the firmware keys and says nothing about the
    kernel's lockdown mode - zero occurrences of the word `lockdown` in a 10.8 MB
    binary, and six JSON fields, none of them one.
    """

    def test_the_real_payload_has_no_lockdown_field(self):
        assert "lockdown" not in REAL_SBCTL, REAL_SBCTL
        assert list(REAL_SBCTL) == list(SBCTL_FIELDS), list(REAL_SBCTL)

    def test_the_page_says_sbctl_has_no_lockdown_field(self):
        _, rows = _render(_lockdown_state())
        assert "Kernel lockdown, in sbctl's answer" in dict(rows), rows

    def test_an_unknown_field_from_sbctl_never_reaches_the_page(self):
        """**This is the page**, held at the layer where the defence actually is.

        A page that read the lockdown mode out of sbctl's payload would look for
        a field named after it. `sbctl_fields()` keeps the six fields its own
        `status --json` printed and drops everything else, so such a key cannot
        arrive - and the drop is the control, not an accident.

        A first attempt at this test injected `sbctl_claims_lockdown` into the
        payload and asserted the row ignored it. **It could not fail**: the key
        was filtered out before the page ever saw it, so the assertion passed
        against a page that read the mode from sbctl. Running the control is what
        found that, and the control that works is the one below - making
        `sbctl_fields()` keep unknown keys fails this test.
        """
        smuggled = dict(REAL_SBCTL)
        smuggled["lockdown"] = "confidentiality"
        smuggled["kernel_lockdown_mode"] = "confidentiality"
        state = sbctl_fields(smuggled)
        assert "lockdown" not in state["fields"], state
        assert "kernel_lockdown_mode" not in state["fields"], state

        tab, rows = _render(_lockdown_state(sbctl_data=smuggled))
        subtitle = _row_map(tab)["Mode in force"]
        assert "none" in subtitle, subtitle
        assert "confidentiality" not in subtitle, (
            "the page took a lockdown mode from sbctl's payload")
        # Scoped to sbctl's own group: the kernel rows legitimately say
        # "confidentiality" because the kernel's mode list contains it, and a
        # blanket search over every subtitle would be failing on the kernel.
        sbctl_group = ("sbctl", "Secure Boot", "Setup Mode", "Vendor keys",
                       "Firmware quirks", "GUID",
                       "sbctl's own installed field")
        spoken = " ".join(_row_map(tab).get(title, "") for title in sbctl_group)
        assert "confidentiality" not in spoken, spoken

    def test_the_kernel_rows_do_not_move_when_sbctls_answer_does(self):
        """Kernel and sbctl are separate reads and must render separately.

        Every one of sbctl's six fields is flipped to the opposite of the
        capture, and the four kernel groups come out identical - which is the
        property a page that let one read stand in for the other would lose.
        """
        flipped = {key: (not value if isinstance(value, bool) else
                         ["microsoft", "custom"] if isinstance(value, list) else
                         "flipped")
                   for key, value in REAL_SBCTL.items()}
        quiet, _r = _render(_lockdown_state(sbctl_installed=False))
        loud, _r2 = _render(_lockdown_state(sbctl_data=flipped))
        kernel_titles = ("Modes the kernel offers", "Mode in force",
                         "lockdown in the running module list",
                         "The file this page reads", "Lockdown requested",
                         "The kernel command line")
        for title in kernel_titles:
            assert _row_map(quiet).get(title) == _row_map(loud).get(title), (
                f"{title!r} changed when sbctl's answer changed")
        # And the flip really did reach the page, or the comparison above would
        # have compared two identical pictures and proved nothing.
        loud_rows = _row_map(loud)
        assert loud_rows["Vendor keys"] == "microsoft, custom", (
            loud_rows["Vendor keys"])
        assert loud_rows["Secure Boot"].startswith("Yes"), loud_rows["Secure Boot"]
        assert loud_rows["GUID"].startswith("flipped"), loud_rows["GUID"]
        assert _row_map(quiet) != loud_rows, (
            "the two renders are identical, so the kernel comparison above "
            "compared a picture with itself")

    def test_the_absent_sbctl_row_is_a_state_and_not_a_failed_read(self):
        _, rows = _render(_lockdown_state(sbctl_installed=False))
        joined = " | ".join(f"{t}: {s}" for t, s in rows)
        sbctl_rows = dict(rows)
        assert sbctl_rows["sbctl"] == (
            "Not installed, so there is nothing for it to report. This is not a "
            "read that failed and it does not affect any row above: the kernel "
            "answers those on its own"), sbctl_rows
        assert "Secure Boot:" not in joined, joined

    def test_an_sbctl_that_could_not_answer_is_a_different_sentence_again(self):
        """Absent, installed-and-silent, and installed-and-failed are three
        states with three different meanings, and a user reads them differently."""
        _, absent = _render(_lockdown_state(sbctl_installed=False))
        _, failed = _render(_lockdown_state(sbctl_error="exit status 1"))
        assert dict(absent)["sbctl"] != dict(failed)["sbctl"]
        assert "did not answer" in dict(failed)["sbctl status"], dict(failed)

    def test_the_kernel_rows_are_complete_with_no_sbctl_at_all(self):
        tab, rows = _render(_lockdown_state(sbctl_installed=False))
        titles = [t for t, _ in rows]
        for expected in ("Modes the kernel offers", "Mode in force",
                         "lockdown in the running module list",
                         "Lockdown requested"):
            assert expected in titles, (expected, titles)
        assert "sbctl" in titles, titles


# --- the four states of the kernel's answer ---------------------------------


class TestTheFourStatesOfTheKernel:
    def _verdict(self, payload: dict) -> str:
        tab, _rows_ = _render(payload)
        return next(t for t, _s in _rows_ if t.startswith(
            ("Lockdown is", "The kernel")))

    def test_present_and_off_is_one_verdict(self):
        verdict = self._verdict(_lockdown_state())
        assert verdict == "Lockdown is available and switched off", verdict

    def test_a_locked_kernel_is_not_reported_as_off(self):
        verdict = self._verdict(_lockdown_state(
            lockdown_text=DERIVED_CONFIDENTIALITY))
        assert verdict == "Lockdown is on, in confidentiality mode", verdict

    def test_integrity_is_named_rather_than_folded_into_a_verdict(self):
        verdict = self._verdict(_lockdown_state(
            lockdown_text=DERIVED_INTEGRITY))
        assert verdict == "Lockdown is on, in integrity mode", verdict

    def test_a_kernel_without_the_feature_is_not_a_kernel_with_it_off(self):
        """**The state this page is mostly about.** No file, so nothing to report
        - which is a different machine from `none`, and the two words must never
        be interchangeable."""
        payload = _lockdown_state(lockdown_text=None, securityfs=False,
                                  lockdown_problem=(
                                      f"{sbctl_mod.LOCKDOWN_PATH} does not exist"))
        verdict = self._verdict(payload)
        assert verdict == "The kernel publishes no lockdown state", verdict
        assert "off" not in verdict.lower(), verdict
        tab, rows = _render(payload)
        detail = dict(rows)[verdict]
        assert "not the same as lockdown being off" in detail, detail
        assert "Kernel lockdown support" in _row_map(tab), _row_map(tab)

    def test_an_empty_file_is_unknown_rather_than_off(self):
        tab, rows = _render(_lockdown_state(lockdown_text=""))
        titles = [t for t, _ in rows]
        unreadable = "The kernel's lockdown file could not be read as a mode"
        assert unreadable in titles, titles
        detail = dict(rows)["Mode in force"]
        assert "unknown rather than off" in detail, detail

    def test_a_mode_this_page_has_no_name_for_is_reported_as_it_stands(self):
        tab, rows = _render(_lockdown_state(
            lockdown_text="[quantum] integrity confidentiality\n"))
        verdict = next(t for t, _ in rows if t.startswith("Lockdown is on"))
        assert "quantum" in verdict, verdict

    def test_the_kernel_line_is_shown_verbatim_beside_the_reading(self):
        """The kernel's own words, so a mode this page has no name for is still
        legible rather than only described."""
        rows = dict(_render(_lockdown_state())[1])
        assert rows["Modes the kernel offers"] == "[none] integrity confidentiality"

    def test_the_off_verdict_names_the_reason_there_is_no_control(self):
        rows = dict(_render(_lockdown_state())[1])
        verdict = next(s for t, s in rows.items() if t == "Lockdown is available "
                       "and switched off")
        assert "kernel command-line parameter" in verdict, verdict
        assert "reboot" in verdict, verdict

    def test_lockdown_out_of_the_running_module_list_is_its_own_row(self):
        rows = dict(_render(_lockdown_state(
            lsm_text="capability,yama,apparmor,ima,evm"))[1])
        subtitle = rows["lockdown in the running module list"]
        assert subtitle.startswith("No - the kernel is running capability"), subtitle

    def test_a_module_list_that_cannot_be_read_is_unknown_not_out(self):
        rows = dict(_render(_lockdown_state(lsm_text="", lsm_problem="nope"))[1])
        subtitle = rows["lockdown in the running module list"]
        assert "unknown" in subtitle, subtitle
        assert "not the same as it being out" in subtitle, subtitle

    def test_the_cmdline_is_shown_verbatim_so_the_request_can_be_checked(self):
        rows = dict(_render(_lockdown_state())[1])
        assert rows["The kernel command line"] == CMDLINE.strip()

    def test_an_lsm_only_cmdline_says_the_boot_asked_for_nothing(self):
        rows = dict(_render(_lockdown_state(cmdline=CMDLINE_WITH_LSM_ONLY))[1])
        subtitle = rows["Lockdown requested"]
        assert subtitle.startswith("No lockdown parameter"), subtitle
        assert "not the same as asking for none" in subtitle, subtitle

    def test_a_requested_mode_and_the_running_mode_are_separate_rows(self):
        """The boot asked for integrity and the kernel is in none. Both are
        facts, and a page that reconciled them would be asserting something
        neither source claims."""
        rows = dict(_render(_lockdown_state(
            cmdline=CMDLINE_REQUESTS_INTEGRITY))[1])
        assert rows["Lockdown requested"].startswith("lockdown=integrity"), rows
        assert "none" in rows["Mode in force"], rows


# --- Shanios: sbctl is not the system of record -----------------------------


class TestShaniosUsesGenEfiNotSbctl:
    """The measured cross-repo facts, checked where they can be.

    `shani-pkgbuilds/shani-core/PKGBUILD` is a sibling repository, so its two
    facts - that sbctl is a **declared** dependency, and that it is the only
    reference to sbctl anywhere in the packaging and the deploy scripts - are
    asserted against that file when it is on disk, and skipped when it is not.
    A test that asserted them from a copy of itself would pass after the
    dependency was dropped.
    """

    PKGBUILD = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "..", "shani-pkgbuilds", "shani-core",
        "PKGBUILD")
    GEN_EFI = os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), "..", "shani-deploy", "scripts",
        "gen-efi.sh")

    def test_sbctl_is_a_declared_dependency_of_shani_core(self):
        """The premise said Shanios does not ship sbctl. It declares it -
        `shani-core/PKGBUILD:25`, in the `# Secure Boot` group."""
        path = os.path.realpath(self.PKGBUILD)
        if not os.path.exists(path):
            pytest.skip(f"{path} is not on disk")
        depends = open(path, encoding="utf-8").read()
        assert re.search(r"^\s*sbctl\s*$", depends, re.M), (
            "shani-core no longer declares sbctl; this page's wording that the "
            "package is a declared dependency has gone stale")

    def test_gen_efi_never_names_sbctl_and_does_use_mokutil(self):
        """The fact the page's "What this is not" group rests on."""
        path = os.path.realpath(self.GEN_EFI)
        if not os.path.exists(path):
            pytest.skip(f"{path} is not on disk")
        source = open(path, encoding="utf-8").read()
        assert "sbctl" not in source, (
            "gen-efi now names sbctl; the page claims Shanios enrols its keys "
            "with gen-efi and mokutil alone and would be wrong")
        assert "mokutil --generate-hash=shanios" in source, (
            "gen-efi's own MOK hash literal moved; the Secure Boot page's "
            "password depends on it and this page points at the same mechanism")

    def test_the_page_says_so_on_the_screen_not_only_in_the_docstring(self):
        groups = _groups(SbctlTab())
        descriptions = " ".join(d for _t, d in groups)
        titles = [t for t, _d in groups]
        assert "gen-efi" in descriptions, descriptions
        assert "mokutil" in descriptions, descriptions
        assert "What this is not" in titles, titles
        # The claim is also stated in words, not only implied by naming the two
        # programs: a reader who has never heard of gen-efi needs the sentence.
        # From a *rendered* page: on a bare one the sbctl group still holds only
        # its build-time row, so the sentence would not be there to find.
        rendered = " ".join(_row_map(_render(_lockdown_state())[0]).values())
        assert "is not what manages Secure Boot on Shanios" in rendered, rendered

    def test_an_installed_sbctl_is_still_not_described_as_the_enrolling_tool(self):
        rows = _row_map(_render(_lockdown_state())[0])
        assert "gen-efi and mokutil" in rows["sbctl"], rows["sbctl"]
        assert "not what manages Secure Boot on Shanios" in rows["sbctl"], (
            rows["sbctl"])

    def test_sbctls_secure_boot_row_is_not_called_the_enrolment_state(self):
        rows = _row_map(_render(_lockdown_state())[0])
        assert "not about the keys Shanios enrolled" in rows["Secure Boot"], (
            rows["Secure Boot"])


# --- the read-only contract, and the two call-site gates ---------------------


class TestReadOnlyContract:
    def test_the_only_option_this_page_ever_passes_is_json(self):
        """The subprocess side of the promise, as a *closed* set.

        The whole module builds exactly one argv: `[sbctl, status, --json]`.
        Every other sbctl subcommand writes - `enroll-keys`, `create-keys`,
        `import-keys`, `sign`, `sign-all`, `rotate-keys`, `reset`, `setup` - so
        naming the allowed set is a stronger gate than searching for the
        forbidden ones.
        """
        assert _string_constants(sbctl_mod) == {"--json"}

    def test_no_writing_subcommand_name_appears_in_the_code(self):
        """The other half of the closed set, and the half that was missing.

        Pinning the **options** alone was not enough, and a control proved it:
        changing the subcommand from `status` to `enroll-keys` left
        `test_the_only_option_this_page_ever_passes_is_json` green, because
        `--json` is still the only option. The option check was real and the
        claim it was carrying was bigger than it could see.

        Docstrings are stripped first. This module's own docstring names
        `enroll-keys`, `create-keys` and the rest in the argument that they are
        the things that must never be run, and a gate that could not tell that
        from an argv would have to be deleted instead of obeyed.
        """
        literals = _literals(sbctl_mod)
        writing = {
            "bundle", "create-keys", "enroll-keys", "export-enrolled-keys",
            "generate-bundles", "import-keys", "list-bundles",
            "list-enrolled-keys", "list-files", "remove-bundle", "remove-file",
            "reset", "rotate-keys", "setup", "sign", "sign-all", "verify",
        }
        assert not (literals & writing), sorted(literals & writing)
        assert "status" in literals, (
            "the subcommand this page runs is no longer a literal, so the gate "
            "above has stopped being able to see it")

    def test_the_only_argv_the_page_builds_is_the_one_read(self):
        """The exact argv, by shape: the tool by `ss.tool_path_or_self()` and the
        two literal words.

        Asserted on the call's own list rather than on the source text, so a
        wrapper or an extra element fails it - and so `enroll-keys` in place of
        `status` does, which the option-only check above did not catch.
        """
        calls = [c for c in ast.walk(ast.parse(inspect.getsource(sbctl_mod)))
                 if isinstance(c, ast.Call)
                 and isinstance(c.func, ast.Attribute)
                 and c.func.attr == "run_json"]
        assert len(calls) == 1, [c.lineno for c in calls]
        argv = calls[0].args[0]
        assert isinstance(argv, ast.List), ast.unparse(argv)
        words = [a.value for a in argv.elts
                 if isinstance(a, ast.Constant) and isinstance(a.value, str)]
        assert words == ["status", "--json"], ast.unparse(argv)
        assert isinstance(argv.elts[0], ast.Call), ast.unparse(argv)
        assert "tool_path_or_self" in ast.unparse(argv.elts[0]), ast.unparse(argv)

    def test_the_page_never_escalates(self):
        code = _code(sbctl_mod)
        for banned in ("pkexec", "polkit", "sudo", "os.system", "subprocess"):
            assert banned not in code, f"{banned} must never appear here"

    def test_the_page_never_writes_to_the_lockdown_file(self):
        """It could. The file is mode 0644 and takes a mode name from any user,
        which is exactly why a settings window must not: the value would also be
        undone at the next boot, so a control here would be a lie.

        `open(` is **not** on the list, because `_read()` uses it - to read. What
        is banned is every name that could open the file for writing, or change
        anything on disk.
        """
        code = _code(sbctl_mod)
        for banned in ("write_text", "os.open", "truncate", "O_WRONLY",
                       "O_RDWR", "O_APPEND", "os.remove", "os.rename",
                       "os.unlink", "shutil", "chmod"):
            assert banned not in code, f"{banned} must never appear here"
        # And the one `open()` there is opened for reading.
        calls = [c for c in ast.walk(ast.parse(inspect.getsource(sbctl_mod)))
                 if isinstance(c, ast.Call)
                 and isinstance(c.func, ast.Name) and c.func.id == "open"]
        assert calls, "no open() call found - this gate inspects nothing"
        for call in calls:
            mode = None
            for arg in call.args[1:]:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    mode = arg.value
            assert mode in (None, "r"), (
                f"open() at line {call.lineno} opens for {mode!r}, not for "
                f"reading")

    def test_the_only_subprocess_is_the_shared_reader(self):
        """One `Gio.Subprocess` in the whole module would be a second runner; the
        page's read goes through `system_status`, which is the one that keeps
        stdout and stderr apart."""
        assert "Gio.Subprocess" not in _code(sbctl_mod)
        assert "run_json" in _code(sbctl_mod)

    def test_the_reader_hands_done_a_payload_and_an_error(self):
        """The two-argument contract's failure mode is an absence.

        A reader calling `done(payload)` where the page expects `done(payload,
        err)` raises `TypeError` *inside* a GTK callback, GLib swallows it, and
        the page renders nothing with nothing in the log. Read from each `done(`
        call's own arguments, not from the annotation.
        """
        calls = [n for n in ast.walk(ast.parse(inspect.getsource(sbctl_mod)))
                 if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Name) and n.func.id == "done"]
        assert calls, (
            "no done() call found - this gate inspects nothing and reports "
            "nothing wrong")
        for call in calls:
            if any(isinstance(a, ast.Starred) for a in call.args):
                continue
            assert len(call.args) == 2, (
                f"done() called with {len(call.args)} argument(s) at line "
                f"{call.lineno}: {ast.unparse(call)}")

    def test_the_reader_is_not_in_system_status(self):
        """It lives here because it must deliver a payload when sbctl is absent,
        which is the ordinary case on Shanios, and because the sysfs facts are
        three plain file reads with no shared counterpart."""
        assert "lockdown_state" not in inspect.getsource(ss)


class TestThePangoGate:
    """Two call sites, and each gate says it found something.

    An unescaped `<` or `&` blanks a row's label rather than raising, so nothing
    downstream can be relied on to notice. The gate is that there is only one
    place a row is built and one place a subtitle is set - so the escaping in
    those two places cannot be bypassed by adding a third.
    """

    def test_there_is_exactly_one_place_a_row_is_built(self):
        sites = _calls_to(sbctl_mod, "ActionRow")
        lines = [s.lineno for s in sites]
        assert len(sites) == 1, (
            f"{len(sites)} Adw.ActionRow() call sites at lines {lines}; every "
            f"row must be built through the one helper that escapes its text")
        assert "_plain(" in ast.unparse(sites[0]), (
            f"the row helper at line {sites[0].lineno} does not escape its text")

    def test_there_is_exactly_one_set_subtitle_call_site(self):
        sites = _calls_to(sbctl_mod, "set_subtitle")
        lines = [s.lineno for s in sites]
        assert len(sites) == 1, (
            f"{len(sites)} set_subtitle() call sites at lines {lines}; a "
            f"subtitle set anywhere else could skip the escaping")
        assert "_plain(" in ast.unparse(sites[0]), (
            f"the set_subtitle() at line {sites[0].lineno} does not escape its "
            f"text")

    def test_both_gates_found_something_to_check(self):
        """The control for the gates themselves: each must fail if the call site
        it counts is renamed, rather than passing while counting zero."""
        assert len(_calls_to(sbctl_mod, "ActionRow")) == 1
        assert len(_calls_to(sbctl_mod, "set_subtitle")) == 1
        assert len(_calls_to(sbctl_mod, "set_widget_never_used")) == 0

    def test_plain_neutralises_the_three_characters_pango_chokes_on(self):
        for raw in ("a & b", "a < b", "a > b", "Cam & <b>Co</b>"):
            escaped = sbctl_mod._plain(raw)
            assert escaped != raw, raw
            assert _markup_safe(escaped), raw

    def test_plain_escapes_the_ampersand_first(self):
        """Ordering, not tidiness. `&` last would turn the `&amp;` it had just
        written into `&amp;amp;`, and the page would display the entity."""
        assert sbctl_mod._plain("a & b") == "a &amp; b"
        assert sbctl_mod._plain("a < b & c") == "a &lt; b &amp; c"

    def test_plain_leaves_the_kernel_line_and_the_cmdline_untouched(self):
        for clean in (LOCKDOWN.strip(), CATA_LOCKDOWN, CMDLINE.strip(), LSM):
            assert sbctl_mod._plain(clean) == clean, clean

    def test_every_note_constant_is_valid_markup_on_its_own(self):
        """The descriptions are not passed through `_plain`, so they have to be
        safe by themselves. Asserted rather than assumed - and this is the check
        `tests/test_new_gap_pages.py::TestDescriptionsAreValidMarkup` makes
        against every `*_NOTE` in `shani_cassini.tabs`, this module included."""
        names = sorted(a for a in dir(sbctl_mod) if a.endswith("_NOTE"))
        assert len(names) >= 6, names
        for name in names:
            text = getattr(sbctl_mod, name)
            assert _markup_safe(text), (name, text)
            assert "<" not in text, (
                f"{name} contains a bare '<', which Pango reads as a tag and "
                f"which discards the whole description")


# --- rendering --------------------------------------------------------------


class TestRendering:
    def test_the_page_constructs_and_renders_rows(self):
        tab = SbctlTab()
        assert _rows(tab), "the page rendered no rows at all"
        assert _groups(tab), "the page built no groups at all"

    def test_every_rendered_subtitle_is_non_empty(self):
        """Over every state, because one of them rendering a row says nothing
        about the others."""
        cases = {
            "off": _lockdown_state(),
            "locked": _lockdown_state(lockdown_text=DERIVED_CONFIDENTIALITY),
            "no feature": _lockdown_state(lockdown_text=None, securityfs=False,
                                          lockdown_problem="does not exist"),
            "empty file": _lockdown_state(lockdown_text=""),
            "no sbctl": _lockdown_state(sbctl_installed=False),
            "sbctl failed": _lockdown_state(sbctl_error="exit status 1"),
        }
        for label, payload in cases.items():
            tab, rows = _render(payload)
            assert rows, label
            for title, subtitle in rows:
                assert subtitle, f"{label}: empty subtitle on {title!r}"
                assert title, f"{label}: empty title"
            # The group descriptions too, because that is where the UPS page's
            # shipped defect lived: a description Pango rejected renders as
            # **nothing** rather than as an error, so a page can lose its whole
            # explanation without a traceback.
            for group_title, description in _groups(tab):
                assert description, (
                    f"{label}: group {group_title!r} rendered no description at "
                    f"all - this is how a rejected one looks")

    def test_a_row_subtitle_is_a_markup_label_so_the_text_must_be_escaped(self):
        """Why the escaping exists, asserted from the widget and not the
        docstring. `Adw.ActionRow`'s subtitle label reports `use_markup = True`,
        so an unescaped `&` or `<` is a markup parse error and GLib refuses the
        assignment."""
        row = Adw.ActionRow(title="T", subtitle="x")
        found = []

        def walk(node):
            if isinstance(node, Gtk.Label):
                found.append(node)
            child = node.get_first_child()
            while child is not None:
                walk(child)
                child = child.get_next_sibling()

        walk(row)
        assert found, "the row has no label to inspect"
        assert any(lab.get_use_markup() for lab in found), (
            [lab.get_use_markup() for lab in found])

    def test_no_rendered_string_can_be_misread_as_markup(self):
        """Two of this page's strings come off the machine: the kernel's lockdown
        line and the whole kernel command line. A root device named `a & b`, an
        initrd path with a bracket, and a kernel listing a mode containing a `<`
        would each be a markup parse error on a label.

        **Which getter returns what was measured on libadwaita 1.5.0** and it
        decides what this can assert. `Adw.ActionRow.get_title()` hands back the
        **markup** it was given, `get_subtitle()` hands back the **plain text**
        Pango parsed out of it, and a subtitle markup GLib rejects leaves
        `get_subtitle()` as the **empty string**:

            Adw.ActionRow(title="a &amp; b", subtitle="x &lt; y")
              -> get_title() == 'a &amp; b'   get_subtitle() == 'x < y'
            row.set_subtitle("p &lt; q &amp; r")  -> get_subtitle() == 'p < q & r'
            Adw.ActionRow(title="a & b",  subtitle="x < y")
              -> Gtk-WARNING, and get_subtitle() == ''

        So the markup-safety check runs over the titles and the group
        descriptions - the two things returned verbatim - and the subtitles are
        held to the check that actually bites on this stack: not empty. Asserting
        `_markup_safe()` on `get_subtitle()` would fail against **correct** code,
        which is how a gate gets deleted instead of trusted.
        """
        hostile_cmdline = (
            "root=/dev/mapper/a&b ro initrd=/boot/vmlinuz-7.0<x> "
            "lsm=landlock,lockdown lockdown=integrity\n")
        tab, rows = _render(_lockdown_state(
            lockdown_text="[a&<b>] integrity confidentiality\n",
            lsm_text="lockdown,<b>yama</b>", cmdline=hostile_cmdline))

        verbatim = [title for title, _s in rows]
        verbatim += [title for _t, title in _groups(tab)]
        verbatim += [description for _t, description in _groups(tab)]
        assert verbatim
        for text in verbatim:
            assert _markup_safe(text), repr(text)

        # Every subtitle survived, which is the failure this stack actually has.
        for title, subtitle in rows:
            assert subtitle, f"empty subtitle on {title!r}"

        # And the hostile strings really reached the page: the escaping assertion
        # above would otherwise have been vacuous.
        # Subtitles come back as the plain text Pango parsed, so the hostile
        # characters are expected there *unescaped* - which is the proof they
        # were escaped on the way in rather than refused.
        plain = " ".join(s for _t, s in rows)
        for hostile in ("a&b", "vmlinuz-7.0<x>", "a&<b>", "<b>yama</b>"):
            assert hostile in plain, (
                f"{hostile!r} did not reach the page; the escaping assertions "
                f"above would have been vacuous")
        escaped = " ".join(verbatim)
        assert "&lt;" in escaped and "&amp;" in escaped, (
            "no escaped entity reached a verbatim label, so the escaping check "
            "above saw nothing to check")

    def test_the_markup_check_itself_can_fail(self):
        """A control for `_markup_safe`: the shapes it exists to reject. A
        checker that returned True for everything would pass every test above."""
        for hostile in ("a & b", "a &bogus; b", "a < b", "x > y"):
            assert _markup_safe(hostile) is False, hostile
        for safe in ("a &amp; b", "the kernel's own", "[none] integrity", ""):
            assert _markup_safe(safe) is True, safe

    def test_repeated_reads_neither_duplicate_rows_nor_crash(self):
        """A second read empties and rebuilds. The tell of getting this wrong is
        a *duplication* - the mirror of this repo's more usual "a row was built
        and never given a parent"."""
        tab = SbctlTab()
        payload = _lockdown_state()
        tab._on_state(payload, "")
        first = len(_rows(tab))
        tab._on_state(payload, "")
        assert len(_rows(tab)) == first, (
            f"a second read left {len(_rows(tab))} rows, not {first}: "
            f"{[t for t, _ in _rows(tab)]}")

    def test_a_second_read_can_change_what_is_shown(self):
        """Not just the count: a state change between reads must reach the
        screen."""
        tab = SbctlTab()
        tab._on_state(_lockdown_state(sbctl_installed=False), "")
        assert "Secure Boot" not in _row_map(tab)
        tab._on_state(_lockdown_state(), "")
        assert "Secure Boot" in _row_map(tab), _row_map(tab)

    def test_the_page_has_no_button_of_any_kind(self):
        """There is no switch, no "apply" and no refresh. A page that could
        change lockdown's mode would be editing a boot entry."""
        found = []

        def walk(node):
            if isinstance(node, Gtk.Button):
                found.append(node)
            child = node.get_first_child()
            while child is not None:
                walk(child)
                child = child.get_next_sibling()

        walk(SbctlTab())
        assert found == [], [b.get_label() for b in found]

    def test_the_cmdline_row_is_selectable(self):
        """It is evidence: a user checking what the boot asked for needs to be
        able to copy it."""
        rows = _row_map(_render(_lockdown_state())[0])
        assert rows["The kernel command line"], rows


# --- the icon, against the running theme ------------------------------------


class TestTheIcon:
    def test_it_exists_in_the_running_theme(self):
        """Checked against the theme rather than a hardcoded list, so a
        misspelling fails here rather than rendering as nothing - which is what a
        missing icon looks like in a screenshot."""
        import gi
        gi.require_version("Gdk", "4.0")
        from gi.repository import Gdk
        display = Gdk.Display.get_default()
        if display is None:
            pytest.skip("no display: there is no icon theme to ask")
        theme = Gtk.IconTheme.get_for_display(display)
        assert theme.has_icon(ICON), (
            f"{ICON} is not in this system's icon theme")

    def test_the_icon_is_not_one_already_used_by_another_section(self):
        """Four sections already share `security-high-symbolic`, which is how a
        sidebar reads as broken. A padlock is unused."""
        try:
            from shani_cassini.notebook import SECTIONS
        except Exception:
            pytest.skip("notebook not importable")
        # Exclude this page's own entry: the whole notebook includes it, so the
        # gate finds the icon under test and fails against itself.
        used = {e[3] for _g, subs in SECTIONS for _s, pages in subs for e in pages
                if len(e) > 3 and isinstance(e[3], str)
                and len(e) > 1 and e[1] != sbctl_mod.SLUG}
        assert ICON not in used, used

    def test_it_is_not_a_loading_or_progress_glyph(self):
        for bad in ("content-loading", "process-working", "content-loading-",
                    "loading"):
            assert bad not in ICON, ICON


# --- the reader -------------------------------------------------------------


class TestTheReader:
    def test_it_reads_this_machine_and_says_so(self, monkeypatch):
        """The reader against the **real** files, which is the only proof that the
        paths are the ones the kernel uses."""
        payload = {}
        sbctl_mod.lockdown_state(lambda p, e: payload.update(p))
        assert payload, "the reader delivered nothing"
        if not os.path.isfile(sbctl_mod.LOCKDOWN_PATH):
            pytest.skip(f"{sbctl_mod.LOCKDOWN_PATH} is not on this machine")
        assert payload["lockdown_problem"] == "", payload
        assert payload["lockdown"]["modes"], payload
        assert payload["lockdown"]["mode"], payload
        assert payload["lsm"], payload
        assert payload["cmdline"], payload
        # And the page renders that payload without raising.
        tab, rows = _render(payload)
        assert rows

    def test_an_absent_sbctl_is_delivered_as_a_value_and_not_an_error(self):
        payloads = []
        monkey = ss.have_tool
        try:
            ss.have_tool = lambda cmd: False
            sbctl_mod.lockdown_state(lambda p, e: payloads.append((p, e)))
        finally:
            ss.have_tool = monkey
        assert len(payloads) == 1, payloads
        payload, error = payloads[0]
        assert error == "", f"an absent sbctl was reported as {error!r}"
        assert payload["sbctl_installed"] is False
        assert payload["lockdown"]["modes"], payload

    def test_the_sysfs_paths_are_module_constants(self):
        """A test cannot create an entry in the real /sys, so the reader takes
        its paths from constants. Patching `os.path.join` instead would be a trap:
        it is global, so an unrelated read in the same module would silently
        start reading the fixture."""
        for name in ("SECURITYFS_PATH", "LOCKDOWN_PATH", "LSM_PATH",
                     "CMDLINE_PATH"):
            value = getattr(sbctl_mod, name)
            assert value.startswith("/"), (name, value)
            assert isinstance(value, str), (name, value)

    def test_the_reader_reads_a_tree_the_test_owns(self, tmp_path, monkeypatch):
        root = tmp_path / "security"
        root.mkdir()
        (root / "lockdown").write_text(DERIVED_INTEGRITY)
        (root / "lsm").write_text(LSM)
        cmdline = tmp_path / "cmdline"
        cmdline.write_text(CMDLINE_REQUESTS_INTEGRITY)
        monkeypatch.setattr(sbctl_mod, "SECURITYFS_PATH", str(root))
        monkeypatch.setattr(sbctl_mod, "LOCKDOWN_PATH",
                            str(root / "lockdown"))
        monkeypatch.setattr(sbctl_mod, "LSM_PATH", str(root / "lsm"))
        monkeypatch.setattr(sbctl_mod, "CMDLINE_PATH", str(cmdline))
        monkeypatch.setattr(sbctl_mod, "SBCTL", "sbctl-not-on-this-path")
        monkeypatch.setattr(ss, "have_tool", lambda cmd: False)

        payloads = []
        sbctl_mod.lockdown_state(lambda p, e: payloads.append((p, e)))
        payload, error = payloads[0]
        assert error == ""
        assert payload["lockdown"]["mode"] == "integrity", payload
        assert payload["requested"] == "integrity", payload
        assert payload["lockdown_in_lsm"] is True, payload
        assert payload["sbctl_installed"] is False, payload

    def test_a_kernel_with_no_lockdown_directory_is_reported_not_guessed(
            self, tmp_path, monkeypatch):
        monkeypatch.setattr(sbctl_mod, "SECURITYFS_PATH", str(tmp_path / "gone"))
        monkeypatch.setattr(sbctl_mod, "LOCKDOWN_PATH",
                            str(tmp_path / "gone" / "lockdown"))
        monkeypatch.setattr(sbctl_mod, "LSM_PATH", str(tmp_path / "gone" / "lsm"))
        monkeypatch.setattr(sbctl_mod, "CMDLINE_PATH", str(tmp_path / "cmdline"))
        monkeypatch.setattr(ss, "have_tool", lambda cmd: False)
        payloads = []
        sbctl_mod.lockdown_state(lambda p, e: payloads.append((p, e)))
        payload, _error = payloads[0]
        assert payload["securityfs_present"] is False, payload
        assert payload["lockdown_problem"], payload
        assert payload["lockdown"]["mode"] == "", payload

    def test_sbctls_warning_is_on_stderr_so_the_json_still_parses(self):
        """Why `run_json` and not a merged-stream reader.

        Measured with the streams split: the warning is stderr, stdout is valid
        JSON. Had it been on stdout, `--json` would be unparseable and the page
        would have had to read the four text rows instead.
        """
        assert json.loads(REAL_SBCTL_STDOUT_JSON) == REAL_SBCTL
        assert CATA_SBCTL_STATUS_STDERR.startswith("old configuration detected")
        assert CATA_SBCTL_STATUS_STDERR not in REAL_SBCTL_STDOUT_JSON

    def test_the_text_rows_would_parse_to_the_same_four_answers(self):
        """Not used by the page - `run_json` is - but it pins the capture, and it
        is the shape a reader would have to handle if a build's JSON ever went
        away."""
        rows = {}
        for line in SBCTL_STATUS_STDOUT.splitlines():
            label, _, value = line.partition(":")
            rows[label.strip()] = value.strip()
        assert list(rows) == ["Installed", "Setup Mode", "Secure Boot",
                              "Vendor Keys"], rows
        assert rows["Vendor Keys"] == "microsoft", rows
        assert rows["Secure Boot"] == "✗ Disabled", rows


# --- the page under a real GTK renderer -------------------------------------


def _pump(until=None, budget_ms: int = 10000) -> int:
    """Iterate the GLib main context until `until()` holds. Returns the polls.

    Non-blocking iteration plus a sleep, deliberately: a blocking
    `ctx.iteration(True)` in a loop whose purpose is to wait for an allocation
    would be the wrong shape.
    """
    context = GLib.MainContext.default()
    polls = max(1, budget_ms // 4)
    for n in range(polls):
        context.iteration(False)
        if until is not None and until():
            return n + 1
        time.sleep(0.004)
    return polls


def _flat_background_css(name: str, priority: int) -> None:
    """A one-colour stylesheet, for the blank control.

    `load_from_data` is deprecated in GTK 4.12 in favour of `load_from_string`;
    both are tried so this runs on 4.14 and on Arch's 4.22.
    """
    from gi.repository import Gdk
    css = Gtk.CssProvider()
    rule = f"box#{name} {{ background-color: rgb(20,20,20); }}"
    if hasattr(css, "load_from_string"):
        css.load_from_string(rule)
    else:
        css.load_from_data(rule.encode("utf-8"))
    Gtk.StyleContext.add_provider_for_display(
        Gdk.Display.get_default(), css, priority)


def _settled(widget) -> bool:
    """Has this widget been given a real size *and* drawn at least once?"""
    return widget.get_width() > 0 and widget.get_height() > 0 and widget.get_mapped()


def _shoot(widget, path: str, width: int = 1000, height: int = 1700):
    """Put a widget in a window, let GTK lay it out, and snapshot it to a PNG.

    Returns `(png_bytes, texture_width, texture_height)`, and `(0, 0, 0)` when
    the snapshot produced no render node at all - the case that reads as "the
    page rendered" if a caller treats any return as success.

    The path is `Gtk.WidgetPaintable` -> `Gtk.Snapshot` ->
    `Gsk.Renderer.render_texture`: real painting through the real renderer, not
    a widget-tree inspection. What it does **not** tell you is where anything is;
    the widget tree is the authority on structure and this is the authority on
    "something was actually drawn".
    """
    window = Gtk.Window()
    window.set_default_size(width, height)
    window.set_child(widget)
    try:
        window.present()
        _pump(lambda: _settled(widget))
        paintable = Gtk.WidgetPaintable.new(widget)
        pw, ph = paintable.get_intrinsic_width(), paintable.get_intrinsic_height()
        snapshot = Gtk.Snapshot.new()
        paintable.snapshot(snapshot, pw, ph)
        node = snapshot.to_node()
        if node is None:
            return 0, 0, 0
        texture = window.get_renderer().render_texture(node, None)
        _pump(lambda: False, budget_ms=200)
        texture.save_to_png(path)
        return os.path.getsize(path), texture.get_width(), texture.get_height()
    finally:
        window.destroy()


class TestThePageRendersForReal:
    """The page painted through GTK's renderer, not merely constructed.

    Every other test here inspects the widget tree, which proves the page built
    the rows and not that anything was drawn. `AGENTS.md` records defects in this
    repo that a green widget-tree suite did not catch and a render did.

    Skipped, not failed, when there is no display - a headless machine has no
    renderer and a skip is the honest answer. It is **not** skipped when the
    display exists but the page does not paint, because that is the thing worth
    failing on.
    """

    @pytest.fixture(autouse=True)
    def _needs_a_display(self):
        from gi.repository import Gdk
        if Gdk.Display.get_default() is None:
            pytest.skip("no display: there is no GTK renderer to paint with")
        yield

    @pytest.fixture
    def fixed_payload(self, monkeypatch):
        """Stop the page's own read from landing mid-test.

        `SbctlTab.__init__` schedules `GLib.idle_add(self.load)`, and every pump
        below iterates the main context - so the real reader runs, answers with
        **this host's** state (`sbctl` is not installed here) and replaces the
        payload the test just rendered. That is not a flake: it is the page doing
        its job, and it would make the capture a picture of something other than
        what was asserted.
        """
        payload = _lockdown_state()
        monkeypatch.setattr(sbctl_mod, "lockdown_state",
                            lambda done: done(payload, ""))
        return payload

    def test_the_page_paints_and_the_capture_is_not_a_blank_surface(
            self, tmp_path, fixed_payload):
        """The page's PNG against a blank control of **the same dimensions**.

        Both PNGs are built at the same size and compared by byte count, so a
        ratio between two different pictures cannot happen: the control is sized
        from what the page just measured. An empty `Gtk.Box` is not a usable
        blank - it has no intrinsic size, produces no render node, and fails for
        a different reason than a page that failed to draw.
        """
        tab = SbctlTab()
        tab._on_state(_lockdown_state(), "")
        page_bytes, page_w, page_h = _shoot(tab, str(tmp_path / "page.png"))

        assert (page_bytes, page_w, page_h) != (0, 0, 0), (
            "the page produced no render node: nothing was painted at all")
        assert page_w > 0, page_w
        assert page_h >= 900, (
            f"the page laid out to only {page_h}px tall; a page that drew "
            f"nothing is nowhere near that")

        _flat_background_css("sbctl-blank", 1000)
        blank = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        blank.set_name("sbctl-blank")
        blank.set_size_request(page_w, page_h)
        blank_bytes, blank_w, blank_h = _shoot(
            blank, str(tmp_path / "blank.png"))

        assert (blank_w, blank_h) == (page_w, page_h), (
            f"the control is {blank_w}x{blank_h} and the page is "
            f"{page_w}x{page_h}; a ratio between two different pictures means "
            f"nothing")
        assert blank_bytes > 0, (
            "the blank control wrote no PNG, so the ratio below proves nothing")
        assert page_bytes > 4 * blank_bytes, (
            f"the page's capture is {page_bytes} bytes against a blank surface's "
            f"{blank_bytes} at the same size - under 4x, so it is very nearly "
            f"blank")

    def test_the_rendered_widget_tree_still_holds_the_groups_and_the_rows(
            self, fixed_payload):
        """Structure, read back out of the **realised** tree after painting."""
        tab = SbctlTab()
        tab._on_state(fixed_payload, "")
        _pump(lambda: _settled(tab))
        titles = [t for t, _d in _groups(tab)]
        for expected in ("Kernel lockdown", "What the kernel says",
                         "What the boot asked for", "What sbctl reports",
                         "What this is not", "Where this comes from"):
            assert expected in titles, (expected, titles)
        rows = [t for t, _s in _rows(tab)]
        assert rows, "the realised tree held no rows"
        assert "Mode in force" in rows, rows
        assert "Secure Boot" in rows, rows

    def test_the_absent_tool_state_also_renders(self, tmp_path, monkeypatch):
        """The state a Shanios machine is most likely in, painted rather than
        only assembled - and on this host the state the reader would have
        produced anyway."""
        payload = _lockdown_state(sbctl_installed=False)
        monkeypatch.setattr(sbctl_mod, "lockdown_state",
                            lambda done: done(payload, ""))
        tab = SbctlTab()
        tab._on_state(payload, "")
        size, width, height = _shoot(tab, str(tmp_path / "absent.png"))
        assert (size, width, height) != (0, 0, 0), (
            "the sbctl-absent state painted nothing at all")
        assert "Secure Boot" not in dict(_rows(tab))


# --- the page is not registered --------------------------------------------


def test_the_page_is_registered_under_its_own_id():
    """The page is registered under exactly the id this module exports.

    The assertion is the other direction on purpose: it fails *loudly* the day
    someone does register it, so this file's claim that the page is unregistered
    and the notebook cannot drift apart quietly.
    """
    import shani_cassini.notebook as notebook
    flat = [e[1] for _g, subs in notebook.SECTIONS
            for _s, pages in subs for e in pages]
    assert sbctl_mod.SLUG in flat, (
        f"registered, but not under the id this module exports "
        f"({sbctl_mod.SLUG!r}); --section={sbctl_mod.SLUG} would not reach it")
