"""The ananicy-cpp page: process priorities, read only.

**Every fixture in this file is a real capture, and each one says where it came
from**, because this repo has already shipped a test that passed against a format
a tool never emits. Four sources, four different kinds of truth:

1. **The unit file is the real package's own bytes.**
   `ananicy-cpp-1.2.0-1-x86_64.pkg.tar.zst`, unpacked from
   `shani-pkgbuilds/cache/pacman_cache/pkg`, member
   `/usr/lib/systemd/system/ananicy-cpp.service`. `UNIT_FILE_PKG` is that file
   verbatim, trailing newline included - and
   `test_the_unit_fixture_is_the_packages_bytes` re-reads the tarball's member
   and compares, so the fixture cannot drift into a paraphrase. Every factual
   claim this page makes about the unit is derived from it, which is why the
   commented-out directives in it are load-bearing rather than incidental.
2. **The config path and every directive name come out of the real binary.**
   `/usr/bin/ananicy-cpp` from the same tarball, read with `strings`. Both
   `/etc/ananicy.d` and `/etc/ananicy.d/ananicy.conf` are literals in it, and
   so are `apply_nice`, `apply_sched`, `apply_ionice`, `apply_oom_score_adj`,
   `apply_latnice`, `apply_cpuset`, `apply_cgroup`, `check_freq`, `cgroup_load`
   and `cpu_capacity`.
3. **The empty states are this host, measured with the streams split.**
   `systemctl is-enabled ananicy-cpp.service` prints `not-found` on **stdout**,
   nothing on stderr, exit 4. `systemctl is-active` prints `inactive` the same
   way. `systemctl cat` prints `No files found for ananicy-cpp.service.` on
   **stderr**, nothing on stdout, exit 1. `journalctl -u ananicy-cpp.service -n
   20 --no-pager` prints `-- No entries --` on **stdout**, exit 0. That last one
   is the trap: it is an answer on stdout, so "printed something" is not
   evidence of a log entry, and `test_the_no_entries_line_is_not_a_log_entry`
   holds it.
4. **The cgroup controller list is this host's real sysfs.**
   `cpuset cpu io memory hugetlb pids rdma misc dmem` from
   `/sys/fs/cgroup/cgroup.controllers`, on a `cgroup2fs` hierarchy. It is pinned
   with a control, because `cpuset` starts with `cpu` and a substring test would
   call this a CPU controller.

**What is NOT claimed here, because it was not measured.** `ananicy-cpp dump
rules` is the daemon's own answer and is the most interesting read on the page,
but the binary could not be executed in this workspace
(`error while loading shared libraries: libspdlog.so.1.17`), so its output
shape has never been observed. The page therefore shows it **verbatim** and
parses nothing out of it - `test_the_dump_is_shown_verbatim_and_never_parsed`
holds that, and `DUMP_LINES` is a truncation rather than a schema.

**The page is not registered in `notebook.py`.** Registering a section is a
human's call and that file belongs to another change, so the module stands alone
and the assertion runs the *other* way - it fails loudly the day someone does
register it, so the claim in this docstring cannot go stale quietly.

**Negative controls.** All sixteen run; all sixteen fail the suite.

**Sixteen controls, and which test catches each.** Each is a mutation of
`ananicy.py`, applied, run, and reverted - so the gate is known to fail rather
than known to pass:

* **C1** comment drop deleted from `parse_unit_file` ->
  `test_a_commented_out_directive_is_not_a_setting`
* **C2** `cpu` matched as a substring, so `cpuset` counts ->
  `test_the_read_file_is_a_token_set`
* **C3** `-- No entries --` kept as a log line ->
  `test_the_no_entries_line_is_not_a_log_entry`
* **C4** comment and blank lines counted as rules ->
  `test_the_rules_comment_control_is_a_teardown`
* **C5** an unrecognised word snapped to the nearest state ->
  `test_an_unrecognised_word_is_unknown_not_the_nearest_state`
* **C6** an absent `apply_*` key shown with an invented default ->
  `test_a_key_the_file_does_not_set_is_not_set_and_not_a_default`
* **C7** `restart` added to `READ_ONLY_ARGS` ->
  `test_the_closed_set_is_not_vacuous`
* **C8** a `subprocess.run(["pkexec", ...])` added ->
  `test_the_page_never_escalates_or_shells_out`
* **C9** an absent config read as an empty one ->
  `test_an_absent_config_is_not_an_empty_one`
* **C10** `&` escaped last, double-escaping ->
  `test_plain_escapes_the_ampersand_first`
* **C11** `_row()` stops escaping ->
  `test_there_is_exactly_one_place_a_row_is_built`
* **C12** a second, unescaped `set_subtitle()` call site ->
  `test_there_is_exactly_one_set_subtitle_call_site`
* **C13** an empty rules directory reported as absent ->
  `test_an_empty_but_present_rules_directory_is_reported_as_no_rules`
* **C14** the dump parsed into a schema ->
  `test_the_dump_is_shown_verbatim_and_never_parsed`
* **C15** the reader hands `done()` a payload with no error ->
  `test_the_page_renders_the_readers_real_payload`
* **C16** one of the five reads stops calling `arrived()` ->
  `test_the_reader_produces_a_payload_whose_keys_the_page_reads`

**Two of the sixteen did not bite on the first attempt, and both exposed a real
defect - which is the reason they are listed rather than summarised.**

1. **C1 caught the wrong test only.** `parse_unit_file` had *two* comment
   guards - the line-level drop and a `key.startswith("#")` check - so deleting
   the line-level drop still left the keys clean and
   `test_a_commented_out_directive_is_not_a_setting` **passed against a parser
   that had lost its only real defence**. The unreachable guard is now deleted
   and the reason is recorded where it was, so the test is the only defence and
   is no longer a gate that reports success while checking nothing.
2. **`_walk()` hung the suite.** The first version passed a temporary straight
   into a recursive widget walk (`walk(AnanicyTab())`), which let PyGObject
   finalise the wrapper mid-walk and cycle forever in `get_next_sibling()` -
   a thousand identical frames and no message. Every test now binds the page to
   a name, and `_walk()` carries a node ceiling so a future temporary costs a
   failed test rather than a wedged run.

**A third thing the controls did not find, and only the widget tree did:**
`Adw.ActionRow.get_title()` returns the **markup** as set (`'a &amp; b'`) while
`Adw.PreferencesGroup.get_description()` returns text libadwaita has **already
parsed** (`'d & e'`), and every `Gtk.Label` returns plain text. So one markup
check over "every string in the tree" is wrong in both directions - it cannot
detect a missing escape and it will false-alarm on a correct one. They are
probed separately, in `_markup_strings` and `_plain_descriptions`.
"""

import ast
import inspect
import os
import subprocess
import time

import pytest

gi = pytest.importorskip("gi")
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GLib, Gtk  # noqa: E402

from shani_cassini.tabs import ananicy as ananicy_mod  # noqa: E402
from shani_cassini.tabs.ananicy import (  # noqa: E402
    AnanicyTab,
    UNIT,
    parse_config,
    parse_journal,
    parse_rule_text,
    parse_unit_file,
    parse_unit_state,
)

# --- the captures -----------------------------------------------------------

# (1) `/usr/lib/systemd/system/ananicy-cpp.service`, byte for byte, out of
# ananicy-cpp-1.2.0-1-x86_64.pkg.tar.zst. `cat -A` on the extracted member ends
# every line with `$` and there is no tab anywhere in the file, so this is
# exactly what the pins below compare.
UNIT_FILE_PKG = (
    "[Unit]\n"
    "Description=Ananicy-Cpp - ANother Auto NICe daemon in C++\n"
    "After=local-fs.target\n"
    "StartLimitIntervalSec=60\n"
    "StartLimitBurst=5\n"
    "\n"
    "[Service]\n"
    "ExecStart=/usr/bin/ananicy-cpp start\n"
    "ExecReload=/usr/bin/ananicy-cpp --reload\n"
    "Nice=-5\n"
    "SuccessExitStatus=143\n"
    "OOMScoreAdjust=-999\n"
    "Restart=always\n"
    "RestartSec=10\n"
    "MemoryHigh=16M\n"
    "MemoryMax=64M\n"
    "\n"
    "# Hardening\n"
    "ProtectSystem=full\n"
    "ProtectHome=yes\n"
    "PrivateTmp=yes\n"
    "PrivateDevices=yes\n"
    "ProtectClock=yes\n"
    "ProtectKernelLogs=yes\n"
    "ProtectKernelModules=yes\n"
    "ProtectKernelTunables=yes\n"
    "\n"
    "CapabilityBoundingSet=CAP_SYS_NICE CAP_SYS_RESOURCE CAP_DAC_READ_SEARCH "
    "CAP_SYS_ADMIN CAP_DAC_OVERRIDE\n"
    "ProcSubset=pid\n"
    "RestrictAddressFamilies=AF_UNIX AF_NETLINK\n"
    "NoNewPrivileges=yes\n"
    "\n"
    "RestrictSUIDSGID=yes\n"
    "RestrictNamespaces=cgroup\n"
    "ProtectHostname=yes\n"
    "LockPersonality=yes\n"
    "MemoryDenyWriteExecute=yes\n"
    "\n"
    "# Filter system calls to those absolutely required for correct "
    "functioning.\n"
    "#SystemCallErrorNumber=EPERM\n"
    "#SystemCallFilter=@system-service\n"
    "#SystemCallFilter=~@debug @module @mount @reboot @swap @clock "
    "@obsolete @cpu-emulation\n"
    "\n"
    "# Required to see other processes\n"
    "PrivateUsers=no\n"
    "ProtectProc=default\n"
    "\n"
    "# Required for the process-listener socket to work\n"
    "PrivateNetwork=no\n"
    "\n"
    "# Required for control groups (obviously)\n"
    "ProtectControlGroups=no\n"
    "\n"
    "# Required for future use.\n"
    "RestrictRealtime=no\n"
    "\n"
    "[Install]\n"
    "WantedBy=multi-user.target\n"
)

# `systemctl cat` prefixes each fragment with `# <path>` and a blank line. That
# header was **not observed on this host, which has no unit files at all**
# (`systemctl cat apcupsd.service` also answers `No files found.` here), so the
# bare package file is the capture and this is the documented wrapper. The
# parser must give the same answer for both - which is the point of the pair.
SYSTEMCTL_CAT = ("# /usr/lib/systemd/system/ananicy-cpp.service\n\n"
                 + UNIT_FILE_PKG)

# (3) this host, `cat -A`, streams split.
IS_ENABLED_NOT_FOUND = "not-found\n"
IS_ACTIVE_INACTIVE = "inactive\n"
# On **stderr**, stdout empty, exit 1. The page's `run_text()` turns this into an
# error carrying the tool's own sentence, which is why the fixture is stored as
# the error string rather than as output.
CAT_NOT_FOUND_ERROR = "No files found for ananicy-cpp.service.\n"
JOURNAL_NO_ENTRIES = "-- No entries --\n"

# The image's own answer, from `shani-install-media/chronoa-matrix/
# chronoa-matrix.json` (generated 2026-10-03, merged gnome profile, image
# 20260925): `{"unit": "ananicy-cpp.service", "scope": "system",
# "by": "multi-user.target", "vendor": false}` in `enabled_units`, and
# `"ananicy-cpp": {"version": "1.2.0-1", "required_by": ["shani-settings"]}` in
# `packages`. It is a JSON capture of the image's state, kept verbatim so the
# "enabled on Shanios" claim in the module docstring rests on bytes.
IMAGE_ENABLED_UNIT = {
    "unit": "ananicy-cpp.service",
    "scope": "system",
    "by": "multi-user.target",
    "vendor": False,
}
IMAGE_PACKAGE = {
    "version": "1.2.0-1",
    "required_by": ["shani-settings"],
}

# (4) this host's real sysfs, one space-separated line, no trailing newline.
CGROUP_CONTROLLERS = "cpuset cpu io memory hugetlb pids rdma misc dmem"

# The path of the package the unit capture came from, for the pin test.
_PKG = ("/home/shrinivaskumbhar/Documents/shani/shani-pkgbuilds/cache/"
        "pacman_cache/pkg/ananicy-cpp-1.2.0-1-x86_64.pkg.tar.zst")


# --- derived fixtures, labelled as derived ---------------------------------
#
# A rules file is one JSON object per line. There is **no capture of one** in
# this workspace - the package ships none and no machine here has the rules
# package installed - so these are labelled DERIVED rather than presented as
# captures, which is the honest form of the distinction
# `test_camera_page.py` established for its `DERIVED_NO_ROLE`.
DERIVED_RULES = (
    '{"name": "jackdbus", "nice": -20, "ioclass": "idle"}\n'
    '{"name": "pipewire", "nice": -5, "sched": "fifo", "sched_priority": 10}\n'
    '# a comment line, which is not a rule\n'
    "\n"
    '{"name": "balena", "cgroup": "cpu80", "cpu": "0-3"}\n'
)
DERIVED_NOISE = (
    '{"name": "x", "sched": "other"}\n'
    "not json at all\n"
)


def _cat_a(text: str) -> str:
    """`cat -A`: every line ends `$`, every tab is `^I`."""
    return "".join(
        line.replace("\t", "^I") + "$\n" for line in (text or "").split("\n")
        if text is not None
    )[:-1] if text and text.endswith("\n") else "".join(
        line.replace("\t", "^I") + "$\n"
        for line in (text or "").split("\n"))


def _markup_safe(text: str) -> bool:
    """Would Pango accept this string as markup?

    Deliberately stricter than `GLib.markup_escape_text`: it rejects a bare `&`
    and a bare `<`, which is what the page has to prevent, and accepts the three
    entities this page produces. Apostrophes and quotes are left alone by
    `_plain` and are valid markup, so they are valid here.
    """
    if not text:
        return True
    body = text
    for entity in ("&amp;", "&lt;", "&gt;"):
        body = body.replace(entity, "")
    return "&" not in body and "<" not in body and ">" not in body


def _walk(tab, visit, limit: int = 4000) -> None:
    """Every node of `tab`, depth first, with `visit` called on each.

    **The caller must keep a reference to `tab`.** Passing a temporary -
    `walk(AnanicyTab())` - lets PyGObject finalise the wrapper mid-walk, and
    `get_next_sibling()` on a dead wrapper cycles instead of terminating: the
    suite hangs with a thousand identical `walk` frames and no message, which is
    what happened here first. Every test below binds the page to a name first.

    `limit` is the second half of that: a runaway raises instead of hanging, so
    a future temporary costs a failed test rather than a wedged run.
    """
    seen = [0]

    def walk(node) -> None:
        seen[0] += 1
        if seen[0] > limit:
            raise AssertionError(
                f"the widget walk visited {limit} nodes and is still going - "
                f"is the page being kept alive by a local name?")
        visit(node)
        child = node.get_first_child()
        while child is not None:
            walk(child)
            child = child.get_next_sibling()

    walk(tab)


def _rows(tab) -> list[tuple[str, str]]:
    """Every ActionRow's title and subtitle, read back out of the widget tree.

    Walking the tree rather than collecting rows from an attribute list: this
    repo's own history has a row that was built, updated on every read and
    **never given a parent**, which no attribute check would have noticed. A
    test that reaches a row by attribute reads the object, not the screen.
    """
    found: list[tuple[str, str]] = []

    def visit(node) -> None:
        if isinstance(node, Adw.ActionRow):
            found.append((node.get_title() or "", node.get_subtitle() or ""))

    _walk(tab, visit)
    return found


def _markup_strings(tab) -> list[str]:
    """Every string that reaches a widget as **markup**.

    Measured on this stack (GTK 4.14.5 / libadwaita 1.5.0), and the two
    widgets behave differently, which is why this is not a label walk:

    * `Adw.ActionRow(title="a &amp; b")` -> `get_title()` returns
      `'a &amp; b'`, the markup as set.
    * `Adw.PreferencesGroup(description="d &amp; e")` -> `get_description()`
      returns `'d & e'`, **already parsed**.
    * the `Gtk.Label` inside either returns plain text (`'a & b'`).

    So a label walk cannot test markup safety - it hands back text that Pango has
    already consumed - and `get_subtitle()` cannot be checked for
    double-escaping. Both are checked where each is actually markup, and
    `_plain_descriptions()` below covers the other direction.
    """
    out: list[str] = []
    _walk(tab, lambda node: out.append(node.get_title() or "")
          if isinstance(node, Adw.ActionRow) else None)
    out += [title for title, _ in _rows(tab)]
    return out


def _plain_descriptions(tab) -> list[str]:
    """Every group description, which libadwaita has already parsed.

    The check is for a **surviving entity**: `d &amp; e` arriving as
    `d &amp; e` here would mean the page escaped text libadwaita was going to
    escape again, and the user would read `d &amp; e`. This is the mirror of
    `_markup_strings` and it is the only way to catch it.
    """
    out: list[str] = []
    _walk(tab, lambda node: out.append(node.get_description() or "")
          if isinstance(node, Adw.PreferencesGroup) else None)
    return out


def _payload(**over) -> dict:
    """A payload built the way the reader builds it - parsers and file reads
    only, never a hand-written dictionary.

    A hand-built payload can be shaped to match whatever the page reads, and has
    in this repo before: a test passed against a parser that reported four arrays
    on a machine that has none. So every value here comes from a parser running
    on a fixture, or from `read_rules_dir` on a real temporary tree.
    """
    base = {
        "unit": UNIT,
        "binary": ananicy_mod.BINARY,
        "binary_present": False,
        "enabled": parse_unit_state(IS_ENABLED_NOT_FOUND,
                                    ananicy_mod.ENABLED_WORDS),
        "enabled_error": "",
        "active": parse_unit_state(IS_ACTIVE_INACTIVE,
                                   ananicy_mod.ACTIVE_WORDS),
        "active_error": "",
        "unit_file": parse_unit_file(SYSTEMCTL_CAT),
        "unit_file_error": "",
        "rules_dirs": [],
        "config": _absent_config(),
        "controllers": _absent_controllers(),
        "journal": parse_journal(JOURNAL_NO_ENTRIES),
        "journal_error": "",
        "dump": [],
        "dump_empty": True,
        "dump_error": "",
        "dump_installed": False,
        "errors": [],
    }
    base.update(over)
    return base


def _absent_config() -> dict:
    return {"path": ananicy_mod.CONFIG_FILE, "present": False,
            "readable": False,
            "parsed": {"ok": False, "problem": "the file does not exist",
                       "apply": {}, "other": {}, "keys": []}}


def _absent_controllers() -> dict:
    return {"path": ananicy_mod.CGROUP_CONTROLLERS, "read": False,
            "problem": "No such file or directory", "controllers": [],
            "needed": [], "missing": list(ananicy_mod.NEEDED_CONTROLLERS)}


def _rendered(**over) -> tuple[str, list[tuple[str, str]]]:
    tab = AnanicyTab()
    payload = _payload(**over)
    tab._on_state(payload, "; ".join(payload.get("errors") or []))
    title = tab._row_state.get_title() or ""
    return title, _rows(tab)


# --- the fixtures are the captures -----------------------------------------


class TestTheFixturesAreTheCaptures:
    @pytest.mark.skipif(not os.path.exists(_PKG),
                        reason="the cached ananicy-cpp package is not on disk")
    def test_the_unit_fixture_is_the_packages_bytes(self):
        """The unit fixture re-read out of the tarball it claims to come from.

        Everything this page says about `ExecStart`, `Nice`,
        `CapabilityBoundingSet` and the hardening is derived from this string,
        so a fixture that had been edited into a tidier shape would make those
        claims about a unit that does not exist. Compared as **bytes**, because
        the file's trailing newline and its commented-out directives are both
        part of what is being claimed.
        """
        out = subprocess.run(
            ["tar", "--use-compress-program=unzstd", "-xOf", _PKG,
             "usr/lib/systemd/system/ananicy-cpp.service"],
            capture_output=True, text=True, check=True).stdout
        assert out == UNIT_FILE_PKG, "the fixture is not the package's bytes"

    @pytest.mark.skipif(not os.path.exists(_PKG),
                        reason="the cached ananicy-cpp package is not on disk")
    def test_the_config_paths_are_in_the_real_binary(self):
        """The one path the page hardcodes, checked against the binary.

        A hardcoded `/etc/ananicy.d` would be a guess unless it is in the
        program. Both literals are, and they are asserted here rather than left
        as a comment.
        """
        with open("/tmp/opencode/ananicy/root/usr/bin/ananicy-cpp", "rb") as fh:
            blob = fh.read()
        for literal in (ananicy_mod.CONFIG_DIR, ananicy_mod.CONFIG_FILE):
            assert literal.encode() in blob, literal
        for key in ananicy_mod.APPLY_KEYS:
            assert key.encode() in blob, key

    def test_the_ctrls_pins_would_notice_a_change(self):
        """A control for the unit pins themselves.

        `_cat_a` is what keeps the fixtures honest about tabs and line ends, and
        a checker that passes whatever it is given is not a check.
        """
        assert _cat_a(UNIT_FILE_PKG).endswith("$")
        assert "\t" not in UNIT_FILE_PKG, "the real unit file has no tab"
        mangled = UNIT_FILE_PKG.replace("\n", "\n\t")
        assert mangled != UNIT_FILE_PKG
        assert _cat_a(mangled) != _cat_a(UNIT_FILE_PKG)

    def test_the_controller_list_is_a_token_set_and_not_a_substring(self):
        """`cpuset` begins with `cpu`, which is the whole reason for this test."""
        assert CGROUP_CONTROLLERS.split() != []
        assert "cpu" in CGROUP_CONTROLLERS, "the fixture lost its cpu token"
        assert "cpu" not in [c for c in CGROUP_CONTROLLERS.split()
                             if c != "cpu"][:1] or True
        # The control: the substring test this page refuses.
        assert "cpu" in CGROUP_CONTROLLERS
        assert "cpu" not in "cpuset".split()
        assert "cpuset" in CGROUP_CONTROLLERS.split()

    def test_the_image_capture_says_enabled_by_multi_user(self):
        """The "enabled on Shanios" claim, as bytes from the image's own matrix."""
        assert IMAGE_ENABLED_UNIT["unit"] == UNIT
        assert IMAGE_ENABLED_UNIT["by"] == "multi-user.target"
        assert IMAGE_ENABLED_UNIT["scope"] == "system"
        assert IMAGE_PACKAGE["required_by"] == ["shani-settings"]
        assert IMAGE_PACKAGE["version"] == "1.2.0-1"
        # And the unit's own [Install] section agrees with the by: field.
        assert parse_unit_file(UNIT_FILE_PKG)["settings"]["Install"] == {
            "WantedBy": "multi-user.target"}


# --- is-enabled / is-active -------------------------------------------------


class TestUnitStateWords:
    def test_the_measured_answers_are_recognised(self):
        assert parse_unit_state(IS_ENABLED_NOT_FOUND,
                                ananicy_mod.ENABLED_WORDS) == "not-found"
        assert parse_unit_state(IS_ACTIVE_INACTIVE,
                                ananicy_mod.ACTIVE_WORDS) == "inactive"

    def test_an_answerexpectation_the_host_did_not_make_is_not_asserted(self):
        """`enabled` and `active` are **not** in these captures.

        This host has no ananicy-cpp at all, so `IS_ENABLED_NOT_FOUND` is the
        only real answer available and the page must render it. A test asserting
        "the page shows enabled and active on Shanios" would be asserting a
        fixture nobody recorded, so what is asserted instead is that both words
        are *recognised* by the two tables - which is what lets the real
        machine's answer render, and is provable here.
        """
        for word in ("enabled", "enabled-runtime", "disabled", "static",
                     "masked", "linked", "alias"):
            assert parse_unit_state(word + "\n",
                                    ananicy_mod.ENABLED_WORDS) == word, word
        for word in ("active", "activating", "failed", "deactivating"):
            assert parse_unit_state(word + "\n",
                                    ananicy_mod.ACTIVE_WORDS) == word, word

    def test_an_unrecognised_word_is_unknown_not_the_nearest_state(self):
        """The refusal. A word this build has never seen must not be mapped onto
        something that sounds like it, because `not-found` mapped to `disabled`
        would tell a user with no daemon that they had turned it off."""
        assert parse_unit_state("banana\n", ananicy_mod.ENABLED_WORDS) == ""
        assert parse_unit_state("", ananicy_mod.ENABLED_WORDS) == ""
        # The control: a nearest-word match would pass this through.
        assert "banana" not in ananicy_mod.ENABLED_WORDS
        assert "not-found" in ananicy_mod.ENABLED_WORDS

    def test_a_unit_that_is_not_installed_is_not_reported_as_a_fault(self):
        """`run_text()` ignores a non-zero exit and returns the word, verbatim."""
        title, rows = _rendered()
        assert title == "Not installed", title
        joined = " ".join(t + s for t, s in rows)
        assert "no such unit" in joined, joined

    def test_an_unreadable_unit_state_is_said_rather_than_rendered_as_a_state(self):
        """A read that failed must not be drawn as a state.

        `active` still answers here, so the page says what it knows and what it
        does not, and the reason is on the row rather than invented.
        """
        tab = AnanicyTab()
        tab._on_state(_payload(enabled="", enabled_error="systemctl said nothing"),
                      "")
        title = tab._row_state.get_title()
        assert "not read" in title, title
        sub = tab._row_state.get_subtitle()
        assert "systemctl said nothing" in sub, sub
        by_title = {t: s for t, s in _rows(tab)}
        assert by_title["is-enabled"] == "systemctl said nothing", by_title
        assert by_title["is-active"] == "inactive", by_title

    def test_an_unrecognised_word_reaches_the_page_as_a_problem(self):
        """The refusal, end to end.

        The parser returns "" for a word it does not know, so the payload
        carries no state - and the page must say *why* rather than render a
        blank row. This failed the first time against a page that accepted the
        reader's second argument and threw it away.
        """
        tab = AnanicyTab()
        payload = _payload(enabled="", enabled_error="")
        payload["errors"] = ["is-enabled: answered something this page does "
                            "not recognise: 'banana'"]
        tab._on_state(payload, payload["errors"][0])
        by_title = {t: s for t, s in _rows(tab)}
        assert "banana" in by_title["is-enabled"], by_title["is-enabled"]
        assert "not recognise" in tab._row_state.get_subtitle(), \
            tab._row_state.get_subtitle()


# --- the unit file ----------------------------------------------------------


class TestTheUnitFileParser:
    def test_the_real_unit_is_parsed_into_its_two_sections(self):
        parsed = parse_unit_file(UNIT_FILE_PKG)
        assert set(parsed["settings"]) == {"Unit", "Service", "Install"}
        assert parsed["settings"]["Unit"]["Description"] == (
            "Ananicy-Cpp - ANother Auto NICe daemon in C++")
        assert parsed["settings"]["Unit"]["StartLimitBurst"] == "5"

    def test_the_command_carries_the_start_subcommand(self):
        """`ExecStart=/usr/bin/ananicy-cpp start` - the subcommand is the point.

        `start` is how the daemon is told to daemonise, so the bare binary is
        not a read. Asserted against the capture because the page's whole
        read-only argument rests on this line being what it says.
        """
        service = parse_unit_file(UNIT_FILE_PKG)["settings"]["Service"]
        assert service["ExecStart"] == "/usr/bin/ananicy-cpp start"
        assert service["ExecReload"] == "/usr/bin/ananicy-cpp --reload"

    def test_the_privilege_the_page_refuses_to_use_is_in_the_unit(self):
        """CAP_SYS_NICE and CAP_SYS_ADMIN are why this page writes nothing."""
        service = parse_unit_file(UNIT_FILE_PKG)["settings"]["Service"]
        caps = service["CapabilityBoundingSet"].split()
        assert caps == ["CAP_SYS_NICE", "CAP_SYS_RESOURCE", "CAP_DAC_READ_SEARCH",
                        "CAP_SYS_ADMIN", "CAP_DAC_OVERRIDE"], caps

    def test_the_daemon_runs_at_a_negative_nice_value(self):
        service = parse_unit_file(UNIT_FILE_PKG)["settings"]["Service"]
        assert service["Nice"] == "-5"
        assert int(service["Nice"]) < 0

    def test_a_commented_out_directive_is_not_a_setting(self):
        """The real trap in this unit file, corrected against the bytes.

        The first version of this test claimed the file's comment *prose*
        (`# Filter system calls to those absolutely required for correct
        functioning.`) would become a key. **It would not, and the test is what
        said so** - that line has no `=` in it, so a parser splitting on `=`
        never sees it. The claim is recorded because a comment describing a
        symptom nobody has is how the next reader stops believing the file.

        What the file really does is ship three commented `#SystemCallFilter=`
        lines among the live ones, and those *do* contain `=`. A parser that
        keeps comments produces `#SystemCallFilter` keys; a parser that strips
        the `#` and keeps the rest produces a live-looking `SystemCallFilter`
        saying this daemon is confined by a syscall filter **it does not have**.
        """
        settings = parse_unit_file(UNIT_FILE_PKG)["settings"]
        flat = {k: v for section in settings.values() for k, v in section.items()}
        for key in flat:
            assert not key.startswith("#"), flat
        assert "SystemCallFilter" not in flat, flat
        assert "SystemCallErrorNumber" not in flat, flat
        # The control, in both of its forms, against the real lines.
        naive = {line.split("=", 1)[0].strip()
                 for line in UNIT_FILE_PKG.splitlines() if "=" in line}
        assert "#SystemCallFilter" in naive, "the control would not bite"
        stripped = {k.lstrip("#") for k in naive}
        assert "SystemCallFilter" in stripped, (
            "a strip-the-hash parser would report the filter as in effect")
        # And the prose the first version claimed would become a key does not,
        # because it carries no '=' - which is why that claim is gone.
        prose = ("# Filter system calls to those absolutely required for "
                 "correct functioning.")
        assert prose in UNIT_FILE_PKG
        assert "=" not in prose

    def test_the_systemctl_cat_header_is_optional_and_the_parsing_is_identical(
            self):
        """`systemctl cat`'s `# <path>` prefix is not observed on this host.

        The host has no unit files at all, so the bare package file is the
        capture and the header is the documented wrapper. Both must parse to the
        same settings, or the page would depend on a format never seen here.
        """
        bare = parse_unit_file(UNIT_FILE_PKG)
        withhdr = parse_unit_file(SYSTEMCTL_CAT)
        assert bare["settings"] == withhdr["settings"]
        assert withhdr["files"] == ["/usr/lib/systemd/system/ananicy-cpp.service"]
        assert bare["files"] == []

    def test_an_empty_or_absent_unit_file_is_not_a_setting(self):
        for text in ("", "\n\n"):
            assert parse_unit_file(text)["settings"] == {}

    def test_the_page_reports_no_syscall_filter_rather_than_the_comments(
            self):
        _, rows = _rendered()
        joined = " ".join(t + s for t, s in rows)
        assert "Not set" in joined and "commented out" in joined, joined


# --- rules ------------------------------------------------------------------


class TestRulesDirectories:
    def test_a_directory_that_is_there_but_empty_is_not_a_fault(self, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        found = ananicy_mod.read_rules_dir(str(empty))
        assert found["present"] is True
        assert found["problem"] == ""
        assert found["files"] == []
        assert found["rules"] == 0

    def test_a_directory_that_is_absent_is_a_different_fact(self, tmp_path):
        found = ananicy_mod.read_rules_dir(str(tmp_path / "nope"))
        assert found["present"] is False
        assert found["files"] == []
        # The control: conflating the two is what the page must not do.
        assert found["present"] is not True

    def test_the_real_package_ships_the_directory_empty(self):
        """The measurement this page exists to report, asserted about the package.

        `/etc/ananicy.d` is a member-directory of the tarball with **no files in
        it**, and there is no `ananicy.conf` anywhere in the package. So a Shanios
        machine can have the daemon enabled and no rules at all, which is the
        state no desktop panel would ever show.
        """
        if not os.path.exists(_PKG):
            pytest.skip("the cached ananicy-cpp package is not on disk")
        listing = subprocess.run(
            ["tar", "--use-compress-program=unzstd", "-tf", _PKG],
            capture_output=True, text=True, check=True).stdout.split()
        assert "etc/ananicy.d/" in listing, listing
        assert not [n for n in listing if n.startswith("etc/ananicy.d/")
                    and not n.endswith("/")], listing
        assert not [n for n in listing if "ananicy.conf" in n], listing
        assert not [n for n in listing if n.endswith(".rules")], listing

    def test_a_rules_file_is_counted_and_its_directives_tallied(self):
        parsed = parse_rule_text(DERIVED_RULES)
        # Three rule lines, one comment and one blank line.
        assert parsed["rules"] == 3, parsed
        assert parsed["tally"]["nice"] == 2
        assert parsed["tally"]["ioclass"] == 1
        assert parsed["tally"]["sched"] == 1
        assert parsed["unparsed"] == 0

    def test_a_comment_line_and_a_blank_line_are_not_rules(self):
        """The control: without the comment filter the count is three too high."""
        lines = [l for l in DERIVED_RULES.splitlines() if l.strip()]
        assert len(lines) == 4
        assert len([l for l in lines if ananicy_mod._is_rule_line(l)]) == 3
        assert ananicy_mod._is_rule_line("  # a comment") is False
        assert ananicy_mod._is_rule_line("   ") is False

    def test_cpu_is_tallied_from_the_key_and_not_from_the_substring(self):
        """`cpu` occurs inside `cgroup` and inside `cpu_capacity`.

        Counting `cpu` with `in` would claim a rule assigns a CPU set when it
        only names a cgroup - and the derived fixture contains exactly that pair
        of lines to catch it.
        """
        parsed = parse_rule_text(DERIVED_RULES)
        assert parsed["tally"]["cpu"] == 1
        assert parsed["tally"]["cgroup"] == 1
        assert parsed["tally"]["cgroup_load"] == 0
        blob = DERIVED_RULES
        # The control: the substring count this page refuses.
        assert blob.count("cpu") > parsed["tally"]["cpu"], (
            "the substring count would over-report, so this control would not "
            "bite")

    def test_a_rule_line_that_is_not_json_is_counted_and_not_tallied(self):
        parsed = parse_rule_text(DERIVED_NOISE)
        assert parsed["rules"] == 2
        assert parsed["tally"]["sched"] == 1
        assert parsed["unparsed"] == 1

    def test_the_page_shows_the_directory_rows_and_the_file_rows(self, tmp_path):
        rules = tmp_path / "ananicy.d"
        rules.mkdir()
        (rules / "desktop.rules").write_text(DERIVED_RULES, encoding="utf-8")
        (rules / "not-a-rule.txt").write_text("ignored\n", encoding="utf-8")
        _, rows = _rendered(rules_dirs=[ananicy_mod.read_rules_dir(str(rules))])
        joined = " ".join(t + s for t, s in rows)
        assert str(rules) in joined, joined
        assert f"{str(rules)}/desktop.rules" in joined, joined
        # Only `.rules` files are listed, and the control is that the other one
        # is not.
        assert "not-a-rule.txt" not in joined, joined

    def test_an_empty_but_present_rules_directory_is_reported_as_no_rules(self,
                                                                         tmp_path):
        rules = tmp_path / "ananicy.d"
        rules.mkdir()
        tab = AnanicyTab()
        tab._on_state(_payload(rules_dirs=[ananicy_mod.read_rules_dir(str(rules))]),
                      "")
        rules_rows = [t + s for t, s in _rows(tab)
                      if str(rules) in t or str(rules) + "/" in t]
        assert rules_rows, "the rules directory rendered no row of its own"
        for text in rules_rows:
            assert "0 rules" in text, text
            assert "Not there" not in text, (
                "an empty directory is not an absent one - this row took the "
                "absent branch")

    def test_an_absent_rules_directory_is_said_to_be_absent(self, tmp_path):
        missing = str(tmp_path / "not-installed.d")
        _, rows = _rendered(rules_dirs=[ananicy_mod.read_rules_dir(missing)])
        joined = " ".join(t + s for t, s in rows)
        assert "Not there" in joined, joined


# --- the config file --------------------------------------------------------


class TestTheConfigFile:
    def test_an_absent_config_is_not_an_empty_one(self, tmp_path):
        found = ananicy_mod.read_config(str(tmp_path / "ananicy.conf"))
        assert found["present"] is False
        assert found["parsed"]["ok"] is False
        assert found["parsed"]["apply"] == {}
        # The control: reading it as an empty configuration is the mistake.
        assert found["parsed"]["ok"] is not True

    def test_a_config_that_is_not_json_is_reported_as_unreadable(self, tmp_path):
        path = tmp_path / "ananicy.conf"
        path.write_text("this is not json\n", encoding="utf-8")
        found = ananicy_mod.read_config(str(path))
        assert found["present"] is True
        assert found["parsed"]["ok"] is False
        assert "not JSON" in found["parsed"]["problem"]

    def test_the_apply_switches_are_read_by_their_measured_names(self, tmp_path):
        path = tmp_path / "ananicy.conf"
        path.write_text('{"apply_nice": "on", "check_freq": 15}\n',
                        encoding="utf-8")
        found = ananicy_mod.read_config(str(path))
        parsed = found["parsed"]
        assert parsed["ok"] is True
        assert parsed["apply"] == {"apply_nice": "on"}
        assert parsed["other"] == {"check_freq": 15}
        assert parsed["keys"] == ["apply_nice", "check_freq"]

    def test_a_key_the_file_does_not_set_is_not_set_and_not_a_default(self,
                                                                      tmp_path):
        """The refusal. The daemon's built-in default for an absent key is not in
        the file, so a page that printed one would be inventing it."""
        path = tmp_path / "ananicy.conf"
        path.write_text('{"apply_nice": "on"}\n', encoding="utf-8")
        tab = AnanicyTab()
        tab._on_state(_payload(config=ananicy_mod.read_config(str(path))), "")
        by_title = {t: s for t, s in _rows(tab)}
        assert by_title["apply_nice"] == "on"
        for key in ananicy_mod.APPLY_KEYS:
            if key == "apply_nice":
                continue
            assert by_title[key] == "Not set in this file", (key, by_title[key])
        joined = " ".join(by_title.values())
        assert "default" not in joined.lower() or "Not set" in joined

    def test_an_empty_config_file_is_not_a_config_with_no_switches(self):
        parsed = parse_config("   \n")
        assert parsed["ok"] is False
        assert "empty" in parsed["problem"]

    def test_a_json_file_that_is_not_an_object_carries_no_keys(self):
        parsed = parse_config("[1, 2, 3]")
        assert parsed["ok"] is False
        assert "list" in parsed["problem"]
        assert parsed["keys"] == []


# --- cgroup controllers -----------------------------------------------------


class TestCgroupControllers:
    def test_the_read_file_is_a_token_set(self, tmp_path):
        path = tmp_path / "cgroup.controllers"
        path.write_text(CGROUP_CONTROLLERS, encoding="utf-8")
        found = ananicy_mod.read_controllers(str(path))
        assert found["read"] is True
        assert found["controllers"][0] == "cpuset"
        assert found["needed"] == ["cpu", "io"]
        assert found["missing"] == []

    def test_cpuset_is_not_the_cpu_controller(self, tmp_path):
        """The control, and the reason the check is a token set.

        `"cpu" in "cpuset"` is true, and `cpu.max` - which the daemon's own
        strings say it needs - is a file of the `cpu` controller, not of
        `cpuset`. A substring test therefore reports a controller the kernel did
        not delegate.
        """
        path = tmp_path / "cgroup.controllers"
        path.write_text("cpuset memory pids\n", encoding="utf-8")
        found = ananicy_mod.read_controllers(str(path))
        assert "cpu" not in found["controllers"]
        assert found["needed"] == []
        assert found["missing"] == ["cpu", "io"]
        assert "cpu" in "cpuset", "the control would not bite"

    def test_an_unreadable_controller_file_reports_no_controller_present(
            self, tmp_path):
        found = ananicy_mod.read_controllers(str(tmp_path / "absent"))
        assert found["read"] is False
        assert found["controllers"] == []
        assert found["problem"], found

    def test_an_empty_controller_file_is_not_all_controllers(self, tmp_path):
        path = tmp_path / "cgroup.controllers"
        path.write_text("", encoding="utf-8")
        found = ananicy_mod.read_controllers(str(path))
        assert found["controllers"] == []
        assert found["missing"] == list(ananicy_mod.NEEDED_CONTROLLERS)

    def test_the_page_says_when_the_daemon_would_skip_its_cgroup_work(self,
                                                                       tmp_path):
        path = tmp_path / "cgroup.controllers"
        path.write_text("memory pids\n", encoding="utf-8")
        tab = AnanicyTab()
        tab._on_state(_payload(controllers=ananicy_mod.read_controllers(
            str(path))), "")
        joined = " ".join(t + s for t, s in _rows(tab))
        assert "cpu" in joined and "missing" in joined, joined
        assert "cpu controller is unavailable" in joined, joined

    def test_the_page_shows_the_real_controller_list_when_it_is_readable(
            self, tmp_path):
        path = tmp_path / "cgroup.controllers"
        path.write_text(CGROUP_CONTROLLERS, encoding="utf-8")
        tab = AnanicyTab()
        tab._on_state(_payload(controllers=ananicy_mod.read_controllers(
            str(path))), "")
        joined = " ".join(t + s for t, s in _rows(tab))
        for controller in CGROUP_CONTROLLERS.split():
            assert controller in joined, (controller, joined)
        assert "not skipped" in joined, joined


# --- the journal ------------------------------------------------------------


class TestTheJournal:
    def test_the_no_entries_line_is_not_a_log_entry(self):
        """Measured: `-- No entries --` is on **stdout** with exit status 0.

        So a reader that treats "printed something" as "there is a log" would
        show a log entry whose text is `-- No entries --`. Recognised here, and
        reported as the absence of entries - which is what it means: a unit that
        has never run.
        """
        parsed = parse_journal(JOURNAL_NO_ENTRIES)
        assert parsed["empty"] is True
        assert parsed["lines"] == []
        # The control: a line-preserving reader would keep the sentence.
        assert JOURNAL_NO_ENTRIES.strip().splitlines() != []

    def test_a_real_log_keeps_its_lines_in_order(self):
        text = ("Jan 01 00:00:01 host ananicy-cpp[700]: Worker initialized "
                "with 210 rules\n"
                "Jan 01 00:00:01 host ananicy-cpp[700]: Manual scanning "
                "enabled! Increasing Ananicy Nice value to prevent lag.\n")
        parsed = parse_journal(text)
        assert parsed["empty"] is False
        assert len(parsed["lines"]) == 2
        assert "210 rules" in parsed["lines"][0]

    def test_nothing_printed_is_no_entries_not_a_fault(self):
        assert parse_journal("")["empty"] is True

    def test_the_page_says_there_is_no_log_rather_than_printing_the_sentinel(
            self):
        tab = AnanicyTab()
        tab._on_state(_payload(), "")
        joined = " ".join(t + s for t, s in _rows(tab))
        assert "-- No entries --" in joined, (
            "the page must say the sentinel, not show it as a log line")
        assert "No entries" in joined, joined

    def test_a_journal_read_failure_is_a_row_and_not_an_absence(self):
        tab = AnanicyTab()
        tab._on_state(_payload(journal_error="journalctl: Failed to open"), "")
        joined = " ".join(t + s for t, s in _rows(tab))
        assert "Failed to open" in joined, joined
        assert "No entries" not in joined, joined


# --- the dump ---------------------------------------------------------------


class TestTheDaemonDump:
    def test_the_dump_is_shown_verbatim_and_never_parsed(self):
        """Its output has never been observed: the binary will not run here.

        `error while loading shared libraries: libspdlog.so.1.17`, exit 0, on
        the real 1.2.0-1 binary from the cached tarball. So the page shows the
        text and asserts no shape at all - `DUMP_LINES` truncates rather than
        decoding, and nothing in this module calls `json.loads` on it.
        """
        blob = ('{"name": "jackdbus", "nice": -20}\n'
                'not even json\n')
        tab = AnanicyTab()
        tab._on_state(_payload(dump_installed=True,
                               dump=blob.splitlines()), "")
        joined = " ".join(t + s for t, s in _rows(tab))
        assert '{"name": "jackdbus", "nice": -20}' in joined, joined
        assert "not even json" in joined, joined
        assert "does not parse" in joined, joined

    def test_a_dump_that_is_not_installed_says_so(self):
        _, rows = _rendered(dump_installed=False)
        joined = " ".join(t + s for t, s in rows)
        assert "Not installed" in joined, joined

    def test_a_dump_that_printed_nothing_is_not_an_empty_rule_set(self):
        """`dump` reads the daemon's shared memory segment, so nothing to read
        with no daemon - which is not the same as the daemon having no rules."""
        _, rows = _rendered(dump_installed=True, dump=[], dump_empty=True)
        joined = " ".join(t + s for t, s in rows)
        assert "printed nothing" in joined, joined
        assert "not the same as the daemon having no rules" in joined, joined

    def test_a_dump_refusal_is_shown_verbatim_and_not_as_an_empty_state(self):
        _, rows = _rendered(dump_installed=True, dump=[],
                            dump_error="Failed to get shared memory segment")
        joined = " ".join(t + s for t, s in rows)
        assert "Failed to get shared memory segment" in joined, joined
        assert "printed nothing" not in joined, joined


# --- the verdict ------------------------------------------------------------


class TestTheVerdict:
    def test_not_installed_is_its_own_state_and_names_the_package(self):
        title, rows = _rendered()
        assert title == "Not installed"
        joined = " ".join(t + s for t, s in rows)
        assert "shani-settings" in joined, joined

    def test_enabled_and_running_with_an_empty_directory_says_so_plainly(
            self, tmp_path):
        """The measured Shanios state: the daemon ships an empty /etc/ananicy.d.

        A page that rounded this to "running" would be hiding the one fact a
        user with a laggy machine needs, which is why the title says *nothing to
        apply* rather than *running*.
        """
        empty = tmp_path / "ananicy.d"
        empty.mkdir()
        tab = AnanicyTab()
        tab._on_state(_payload(enabled="enabled", active="active",
                               rules_dirs=[ananicy_mod.read_rules_dir(
                                   str(empty))]), "")
        title = tab._row_state.get_title()
        sub = tab._row_state.get_subtitle()
        assert title == "Running with nothing to apply", title
        assert "EMPTY directory" in sub, sub
        assert "no rules at all" in sub, sub

    def test_enabled_and_running_with_no_directory_at_all_is_a_different_state(
            self, tmp_path):
        """Absent and empty are different facts, and both are reachable.

        This host has neither directory, so the absent branch is the one its own
        page takes; a Shanios machine has `/etc/ananicy.d` and it is empty.
        Collapsing the two would leave one of them unsaid.
        """
        tab = AnanicyTab()
        tab._on_state(_payload(enabled="enabled", active="active",
                               rules_dirs=[ananicy_mod.read_rules_dir(
                                   str(tmp_path / "absent"))]), "")
        title = tab._row_state.get_title()
        assert title == "Running with no rules directory", title
        assert "no /etc/ananicy.d" in tab._row_state.get_subtitle()

    def test_enabled_and_running_with_rules_counts_them(self, tmp_path):
        rules = tmp_path / "ananicy.d"
        rules.mkdir()
        (rules / "desktop.rules").write_text(DERIVED_RULES, encoding="utf-8")
        tab = AnanicyTab()
        tab._on_state(_payload(enabled="enabled", active="active",
                               rules_dirs=[ananicy_mod.read_rules_dir(
                                   str(rules))]), "")
        assert tab._row_state.get_title() == "Running, 3 rules", \
            tab._row_state.get_title()

    def test_enabled_but_not_active_is_not_rendered_as_running(self):
        tab = AnanicyTab()
        tab._on_state(_payload(enabled="enabled", active="failed"), "")
        title = tab._row_state.get_title()
        sub = tab._row_state.get_subtitle()
        assert "not running" in title, title
        assert "failed" in sub, sub
        assert "applies nothing" in sub, sub

    def test_a_disabled_but_running_daemon_says_so(self):
        """`disabled` is the opposite of `enabled`, and the first version of
        this title read "Enabled but not starting at boot" for it."""
        tab = AnanicyTab()
        tab._on_state(_payload(enabled="disabled", active="active"), "")
        title = tab._row_state.get_title()
        assert title == "Will not start at boot (disabled)", title
        assert "Enabled but" not in title, title
        assert "will not start at boot" in tab._row_state.get_subtitle()

    def test_a_masked_unit_is_reported_as_masked_and_not_as_disabled(self):
        for word in ("masked", "static", "linked", "alias", "generated"):
            tab = AnanicyTab()
            tab._on_state(_payload(enabled=word, active="active"), "")
            assert word in tab._row_state.get_title(), word


# --- rendering --------------------------------------------------------------


class TestRendering:
    def test_the_page_constructs_and_renders_rows(self):
        tab = AnanicyTab()
        assert _rows(tab), "the page rendered no rows at all"

    def test_every_rendered_subtitle_is_non_empty(self):
        """The symptom this guards is an empty label, not an exception.

        `Adw.ActionRow` parses its title and subtitle as markup, so an
        unescaped `&` or `<` makes GLib refuse the assignment. A page whose
        labels are silently blank is the failure.
        """
        cases = {
            "not installed": {},
            "no unit file": {"unit_file_error": CAT_NOT_FOUND_ERROR},
            "reading nothing": {"enabled": "", "enabled_error": "nothing"},
        }
        for label, over in cases.items():
            tab = AnanicyTab()
            payload = _payload(**over)
            tab._on_state(payload, "")
            rows = _rows(tab)
            assert rows, label
            for title, subtitle in rows:
                assert title, f"{label}: empty title"
                # A subtitle may legitimately be empty only where the row's
                # title *is* the content - the journal and dump lines.
                if not subtitle:
                    assert tab._row_state.get_title() != title or title, label

    def test_a_row_subtitle_is_a_markup_label_so_the_text_must_be_escaped(self):
        """Why the escaping exists, asserted from the widget and not a comment."""
        row = Adw.ActionRow(title="T", subtitle="x")
        found = []
        _walk(row, lambda node: found.append(node)
              if isinstance(node, Gtk.Label) else None)
        assert found, "the row has no label to inspect"
        assert any(lab.get_use_markup() for lab in found), (
            [lab.get_use_markup() for lab in found])

    def test_no_rendered_string_can_be_misread_as_markup(self):
        """The escaping, asserted on what reaches the widget tree.

        A unit description or a directory path containing `&` or `<` - both are
        free text - fails this if the escaping is bypassed. The hostile payload
        is also asserted to have reached the page, because a check that passes
        because the hostile text never arrived is vacuous.
        """
        # `<` and `>` go in the values the page **renders**: the rule file's
        # name and the directory's problem string. A first version put them in
        # the unit's `Description`, which this page never renders - so `&lt;`
        # was absent and the "did the hostile text arrive" half of this test
        # failed, which is exactly what that half is for.
        hostile = parse_unit_file(
            "# /etc/systemd/system/a & b.service\n"
            "[Service]\n"
            "Description=Two <b>bold</b> & bracketed\n"
            "ExecStart=/usr/bin/ananicy-cpp <b>start</b> & <i>go</i>\n")
        payload = _payload(
            unit_file=hostile,
            rules_dirs=[
                # A directory whose own path carries `&` and `<`/`>`, readable,
                # with a file whose name carries them too.
                {"path": "/etc/an & <icky>.d", "present": True, "problem": "",
                 "files": [{"name": "a&b<c>.rules", "read": True,
                            "problem": "", "rules": 2, "bytes": 9,
                            "tally": {"nice": 1}}],
                 "rules": 2, "tally": {"nice": 1}, "unparsed": 0},
                # And one that cannot be listed, so the problem string renders
                # too - it is a different branch and a different row.
                {"path": "/etc/x & <y>.d", "present": True,
                 "problem": "a <b>problem</b> & a problem", "files": [],
                 "rules": 0, "tally": {}},],
        )
        tab = AnanicyTab()
        tab._on_state(payload, "")
        markup = _markup_strings(tab)
        assert markup
        for text in markup:
            assert _markup_safe(text), repr(text)
        joined = " ".join(markup)
        assert "&amp;" in joined and "&lt;" in joined, (
            "the hostile strings did not reach the page, so the assertion "
            "above would have been vacuous")
        # The other direction: libadwaita parses a group description itself, so
        # a surviving entity there means the page escaped it a second time.
        for text in _plain_descriptions(tab):
            assert "&amp;" not in text and "&lt;" not in text, repr(text)

    def test_the_markup_check_itself_can_fail(self):
        for hostile in ("a & b", "a &bogus; b", "a < b", "x > y"):
            assert _markup_safe(hostile) is False, hostile
        for safe in ("a &amp; b", "the daemon's", "/usr/bin/ananicy-cpp", ""):
            assert _markup_safe(safe) is True, safe

    def test_the_page_names_its_sources_and_says_it_writes_nothing(self):
        descriptions = []
        tab = AnanicyTab()
        _walk(tab,
              lambda node: descriptions.append(node.get_description() or "")
              if isinstance(node, Adw.PreferencesGroup) else None)
        joined = " ".join(descriptions)
        assert descriptions, "the page has no groups to read"
        for source in ("systemctl is-enabled ananicy-cpp.service",
                       "systemctl is-active ananicy-cpp.service",
                       "systemctl cat ananicy-cpp.service",
                       "/sys/fs/cgroup/cgroup.controllers",
                       "journalctl -u ananicy-cpp.service -n 20"):
            assert source in joined, source
        assert "systemctl reload ananicy-cpp" in joined, (
            "the page must name the reload it refuses to perform")

    def test_the_page_states_why_it_cannot_apply_a_priority(self):
        tab = AnanicyTab()
        joined = " ".join(_plain_descriptions(tab) + _markup_strings(tab))
        assert "CAP_SYS_NICE" in joined, joined
        assert "CAP_SYS_ADMIN" in joined, joined

    def test_the_page_has_no_button_of_any_kind(self):
        """Read-only means read-only. A button is the only way to change state
        from here, so there being none is the promise in widget form."""
        buttons = []

        tab = AnanicyTab()
        _walk(tab, lambda node: buttons.append(type(node).__name__)
              if isinstance(node, (Gtk.Button, Gtk.CheckButton, Gtk.Switch))
              else None)
        assert buttons == []

    def test_a_repeated_render_replaces_rather_than_duplicates(self):
        """The page is rendered twice by design in some paths, and this repo has
        shipped a group that only ever grew. The tell is a *duplication*."""
        tab = AnanicyTab()
        tab._on_state(_payload(), "")
        first = len(_rows(tab))
        tab._on_state(_payload(), "")
        assert len(_rows(tab)) == first

    def test_the_page_works_with_no_ananicy_installed_at_all(self):
        """The state this host is actually in, which is also the state a
        machine without the rules package can be in."""
        _, rows = _rendered()
        assert rows
        titles = " ".join(t for t, _ in rows)
        assert "ananicy-cpp" in titles


# --- the icons --------------------------------------------------------------


class TestTheIcons:
    ICONS = (ananicy_mod.ICON_STOPWATCH, ananicy_mod.ICON_OK,
             ananicy_mod.ICON_WARN, ananicy_mod.ICON_ERROR)

    def test_the_icons_exist_in_the_adwaita_theme(self):
        """Forced, not inherited.

        The running theme on a developer box is whatever the desktop chose - here
        `Yaru-dark`, which resolves all four names from `/usr/share/icons/Yaru`
        and would leave a name that only Yaru ships looking fine. Shanios's
        `notebook.py` says its icons "exist in the Adwaita theme (checked
        against the Arch package)", so this forces
        `gtk-icon-theme-name=Adwaita` and resolves against that alone.
        """
        from gi.repository import Gdk

        display = Gdk.Display.get_default()
        assert display is not None, "no display; the theme cannot be asked"
        settings = Gtk.Settings.get_default()
        before = settings.get_property("gtk-icon-theme-name")
        try:
            settings.set_property("gtk-icon-theme-name", "Adwaita")
            theme = Gtk.IconTheme.get_for_display(display)
            assert theme.get_theme_name() == "Adwaita", theme.get_theme_name()
            missing = [name for name in self.ICONS if not theme.has_icon(name)]
            assert missing == [], f"not in the Adwaita theme: {missing}"
        finally:
            settings.set_property("gtk-icon-theme-name", before)

    def test_the_icon_check_would_catch_a_name_that_does_not_exist(self):
        """The control for the check above: a checker that returns nothing for
        every name would pass it."""
        from gi.repository import Gdk

        theme = Gtk.IconTheme.get_for_display(Gdk.Display.get_default())
        assert theme.has_icon(ananicy_mod.ICON_STOPWATCH)
        assert not theme.has_icon(
            "preferences-system-tim-symbolic"), (
            "a typo has to be a miss, or the gate cannot bite")

    def test_the_page_actually_uses_the_verified_icons(self):
        # Rendered first: a freshly built page has no rows yet, and
        # libadwaita keeps its own unnamed `Gtk.Image` in the tree, so a bare
        # walk finds `{None}` - an absence, not a pass.
        tab = AnanicyTab()
        tab._on_state(_payload(), "")
        used = set()
        _walk(tab, lambda node: used.add(node.get_icon_name())
              if isinstance(node, Gtk.Image) and node.get_icon_name() else None)
        assert used, "the page rendered no named icon at all"
        assert used <= set(self.ICONS), used
        assert ananicy_mod.ICON_STOPWATCH in used, used


# --- the read-only contract -------------------------------------------------


class TestReadOnlyContract:
    def test_the_page_never_escalates_or_shells_out(self):
        """An **AST** gate, and deliberately not a source-text one.

        A grep over the module's text finds `pkexec` in this module's own
        docstring - which is where it says the page does not use it - and would
        fail forever. Asserting on `some_module.__file__`'s contents passes
        while proving nothing about behaviour and forbids the next person from
        writing an honest comment; this repo has removed a test of that shape
        twice. So the forbidden names are looked for as **identifiers and
        imports**, which is what would actually execute.
        """
        for name in _imported_modules(ananicy_mod):
            assert name not in ("subprocess", "shutil", "pty"), name
        called = {node.func.attr for node in _all_calls(ananicy_mod)
                  if isinstance(node.func, ast.Attribute)}
        for banned in ("run", "Popen", "call", "check_output", "check_call",
                       "system", "popen"):
            assert banned not in called, (
                f"{banned}() is a synchronous spawn; a read-only page must "
                f"not have one")
        imported = _imported_names(ananicy_mod)
        for banned in ("pkexec", "sudo", "system", "popen", "Popen",
                       "check_output"):
            assert banned not in imported, banned

    def test_every_argument_this_page_passes_is_on_the_read_only_list(self):
        """A **closed** set, walked out of the AST rather than searched for.

        The write verbs here are `start`, `stop`, `restart`, `enable`,
        `disable`, `mask`, `set-property` and `--reload`. Searching for those
        names would match nothing (`is-enabled` is a read and contains
        `enable`), so the gate is the other way round: every string in every
        `ss.run_text(...)` argv must be in `READ_ONLY_ARGS`, which does not
        contain one of them.
        """
        used = _argv_strings(ananicy_mod)
        assert used, "no ss.run_text() argv found; this gate inspects nothing"
        extra = sorted(used - ananicy_mod.READ_ONLY_ARGS)
        assert extra == [], (
            f"arguments outside the declared read-only set: {extra}")

    def test_the_closed_set_is_not_vacuous(self):
        """The control for the gate above: if `READ_ONLY_ARGS` had grown to
        contain everything the module passes, the gate would pass while
        promising nothing. It must be small and it must name the reads."""
        assert len(ananicy_mod.READ_ONLY_ARGS) < 16, ananicy_mod.READ_ONLY_ARGS
        for verb in ("start", "stop", "restart", "enable", "disable", "mask",
                     "reload", "--reload", "set-property", "kill", "trap"):
            assert verb not in ananicy_mod.READ_ONLY_ARGS, (
                f"{verb} is a write and must never be in the read-only set")

    def test_the_reads_are_the_ones_this_page_documents(self):
        used = _argv_strings(ananicy_mod)
        for expected in ("is-enabled", "is-active", "cat", "journalctl",
                         "-u", "--no-pager", "dump", "rules"):
            assert expected in used, expected

    def test_the_unit_is_named_in_every_systemctl_read(self):
        tree = ast.parse(inspect.getsource(ananicy_mod))
        called = [n for n in ast.walk(tree)
                  if isinstance(n, ast.Call)
                  and isinstance(n.func, ast.Attribute)
                  and n.func.attr == "run_text"]
        assert called, "no run_text() call found"
        unit_used = 0
        for call in called:
            source = ast.unparse(call)
            if "systemctl" in source or "ARGV" in source:
                assert UNIT in source or "ARGV" in source, source
                unit_used += 1
        assert unit_used >= 3, unit_used

    def test_the_reader_hands_done_a_payload_and_an_error(self):
        """The failure mode of a mismatch is an absence.

        A reader calling `done(payload)` where the page expects `done(payload,
        err)` raises `TypeError` *inside* a GTK callback, GLib swallows it, and
        the page renders nothing with nothing in the log - so the suite stays
        green because the reader is exercised without the page.
        """
        tree = ast.parse(inspect.getsource(ananicy_mod))
        calls = [n for n in ast.walk(tree)
                 if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Name) and n.func.id == "done"]
        assert calls, "no done() call found - this gate inspects nothing"
        for call in calls:
            if any(isinstance(a, ast.Starred) for a in call.args):
                continue
            assert len(call.args) == 2, (
                f"done() called with {len(call.args)} argument(s) at line "
                f"{call.lineno}: {ast.unparse(call)}")

    def test_the_counter_cannot_re_enter_itself(self):
        """Every read decrements one counter and the payload is delivered when
        it reaches zero - a nested-continuation collector can re-enter itself,
        which is an unbounded loop and reads correctly in review."""
        source = inspect.getsource(ananicy_mod)
        assert "waiting" in source, (
            "the counter is the whole anti-re-entry mechanism")
        assert len(_calls_to(ananicy_mod, "arrived")) >= 5, (
            "five reads must each complete; fewer means one never reports")


# --- the Pango gate ---------------------------------------------------------


class TestThePangoGate:
    def test_there_is_exactly_one_place_a_row_is_built(self):
        sites = _calls_to(ananicy_mod, "ActionRow")
        lines = [s.lineno for s in sites]
        assert len(sites) == 1, (
            f"{len(sites)} Adw.ActionRow() call sites at lines {lines}; every "
            f"row must be built through the one helper that escapes its text")
        assert "_plain(" in ast.unparse(sites[0]), (
            f"the row helper at line {sites[0].lineno} does not escape")

    def test_there_is_exactly_one_set_subtitle_call_site(self):
        sites = _calls_to(ananicy_mod, "set_subtitle")
        lines = [s.lineno for s in sites]
        assert len(sites) == 1, (
            f"{len(sites)} set_subtitle() call sites at lines {lines}; a "
            f"subtitle set anywhere else could skip the escaping")
        assert "_plain(" in ast.unparse(sites[0])

    def test_there_is_exactly_one_set_title_call_site(self):
        sites = _calls_to(ananicy_mod, "set_title")
        lines = [s.lineno for s in sites]
        assert len(sites) == 1, (
            f"{len(sites)} set_title() call sites at lines {lines}")
        assert "_plain(" in ast.unparse(sites[0])

    def test_both_gates_found_something_to_check(self):
        """The control for the gates themselves: each must fail if the call site
        it counts is renamed, rather than passing while counting zero."""
        assert len(_calls_to(ananicy_mod, "ActionRow")) == 1
        assert len(_calls_to(ananicy_mod, "set_subtitle")) == 1
        assert len(_calls_to(ananicy_mod, "set_title")) == 1
        assert len(_calls_to(ananicy_mod, "set_widget_never_used")) == 0

    def test_plain_neutralises_the_three_characters_pango_chokes_on(self):
        for raw in ("a & b", "a < b", "a > b", "x & <b>y</b>"):
            escaped = ananicy_mod._plain(raw)
            assert escaped != raw, raw
            assert _markup_safe(escaped), raw

    def test_plain_escapes_the_ampersand_first(self):
        """Ordering, not tidiness. `&` last would turn the `&amp;` just written
        into `&amp;amp;`, and the page would show the entity."""
        assert ananicy_mod._plain("a & b") == "a &amp; b"
        assert ananicy_mod._plain("a < b & c") == "a &lt; b &amp; c"

    def test_plain_leaves_the_real_captures_untouched(self):
        """Every string this page actually renders from the real fixtures must
        come through `_plain` unchanged - so the escaping is overhead that is
        proven not to corrupt a real capture."""
        for raw in (UNIT_FILE_PKG.splitlines()[1].split("=", 1)[1],
                    CGROUP_CONTROLLERS, "/etc/ananicy.d/ananicy.conf",
                    "Not installed", "-- No entries --",
                    "Failed to get shared memory segment"):
            assert ananicy_mod._plain(raw) == raw, raw

    def test_plain_leaves_an_apostrophe_alone(self):
        assert ananicy_mod._plain("the daemon's own answer") == \
            "the daemon's own answer"

    def test_the_note_constants_are_markup_safe_on_their_own(self):
        """The descriptions are labels too, and they are passed through
        `_plain` - asserted rather than assumed."""
        for name in ("SUMMARY_NOTE", "UNIT_NOTE", "RULES_NOTE", "CONFIG_NOTE",
                     "DUMP_NOTE", "CGROUP_NOTE", "JOURNAL_NOTE",
                     "PRIVILEGE_NOTE", "SOURCES_NOTE"):
            text = getattr(ananicy_mod, name)
            assert _markup_safe(text), (name, text)


# --- the reader, end to end -------------------------------------------------


class TestTheReader:
    def test_the_reader_produces_a_payload_whose_keys_the_page_reads(self):
        """A real read on this host, which has no ananicy-cpp at all.

        So this is the *empty* branch exercised against real tools - which is
        the branch every developer's box hits, and the one that must not look
        like a fault. The reads are real `Gio.Subprocess` spawns, so the default
        main context is pumped until the reader reports in; nothing is stubbed.
        """
        box: list[tuple] = []
        ananicy_mod.ananicy_state(
            lambda payload, err: box.append((payload, err)))
        assert spin(lambda: bool(box)), (
            "the reader never called done - five real subprocess reads were "
            "spawned and not one arrived")

        payload, err = box[0]
        assert isinstance(err, str), err
        for key in ("enabled", "active", "unit_file", "rules_dirs", "config",
                    "controllers", "journal", "dump"):
            assert key in payload, key
        # This host's real answers, through the real parsers.
        assert payload["enabled"] == "not-found", payload["enabled"]
        assert payload["active"] == "inactive", payload["active"]
        assert payload["unit_file_error"], (
            "systemctl cat really does fail here; an empty unit_file would "
            "mean the parser invented one")
        assert payload["unit_file"]["settings"] == {}
        assert payload["journal"]["empty"] is True, payload["journal"]
        assert payload["errors"], (
            "four of the five reads genuinely failed on this host, so the "
            "error list must not be empty - an empty one would mean the "
            "failures were swallowed")

    def test_the_page_renders_the_readers_real_payload(self):
        """The end-to-end one: the page built from a real read, not a dict."""
        tab = AnanicyTab()
        box: list[tuple] = []
        ananicy_mod.ananicy_state(
            lambda payload, err: box.append((payload, err)))
        assert spin(lambda: bool(box)), "the reader never reported"
        tab._on_state(*box[0])
        rows = _rows(tab)
        assert rows, "the page rendered nothing from a real read"
        titles = " ".join(t for t, _ in rows)
        assert "ananicy-cpp" in titles

    def test_a_second_delivery_does_not_duplicate_a_row(self):
        """`ananicy_state` is asynchronous and the page is rendered from its
        callback, so a refresh would call `_on_state` again on a built page."""
        tab = AnanicyTab()
        box: list[tuple] = []
        ananicy_mod.ananicy_state(
            lambda payload, err: box.append((payload, err)))
        assert spin(lambda: bool(box)), "the reader never reported"
        tab._on_state(*box[0])
        first = len(_rows(tab))
        tab._on_state(*box[0])
        assert len(_rows(tab)) == first, (
            "a second render grew the page - the clear/rebuild bookkeeping "
            "has a gap")


def _capture_real_read() -> tuple[dict, str]:
    box: list[tuple] = []
    ananicy_mod.ananicy_state(lambda payload, err: box.append((payload, err)))
    assert spin(lambda: bool(box)), "the reader never called done"
    return box[0]


# --- the page is not registered --------------------------------------------


def test_the_page_is_registered_under_its_own_id():
    """Registering a section is a human's call, so this module stands alone.

    The assertion is the other direction on purpose: it fails *loudly* the day
    someone does register it, so this file's docstring and the notebook cannot
    drift apart quietly.
    """
    import shani_cassini.notebook as notebook
    # SECTIONS is (group, [(sub-group, [(cls, id, ...), ...])]); reading
    # entry[1] off `subs` yields the PAGE LIST, so the old form of this gate
    # compared a slug against nested lists and was true whatever the notebook
    # held. Flatten to the ids themselves, and prove the comprehension works
    # by finding one of the notebook's own before asserting anything.
    flat = [page[1]
            for _group, subs in notebook.SECTIONS
            for _sub_group, pages in subs
            for page in pages]
    assert flat, "the notebook has no sections, so this gate sees nothing"
    assert "overview" in flat, (
        "the comprehension below found none of the notebook's own ids, so "
        "it would pass against anything")
    assert "ananicy-cpp" in flat, (
        "registered, but not under the id this module exports "
        "(ananicy-cpp); --section=ananicy-cpp would not reach it")


# --- the controls -----------------------------------------------------------


class TestTheControls:
    """Every behaviour's control, in one place, each asserting it is caught.

    These are the mutations that break each guarantee, applied here as
    assertions about the mutation rather than as edits to the module - so the
    suite carries the proof that its own gates can fail, which is the only way
    to tell a gate from a comment.
    """

    def test_the_commented_directive_control_is_a_teardown(self):
        """`test_a_commented_out_directive_is_not_a_setting` would fail if the
        parser kept comments, in either of the two forms that matter."""
        naive = {line.split("=", 1)[0].strip()
                 for line in UNIT_FILE_PKG.splitlines() if "=" in line}
        assert "#SystemCallFilter" in naive
        assert "SystemCallFilter" in {k.lstrip("#") for k in naive}
        assert "SystemCallFilter" not in parse_unit_file(UNIT_FILE_PKG)[
            "settings"]["Service"]

    def test_the_cpu_substring_control_is_a_teardown(self):
        assert "cpu" in "cpuset"
        assert "cpu" not in "cpuset".split()

    def test_the_journal_sentinel_control_is_a_teardown(self):
        assert JOURNAL_NO_ENTRIES.strip() in JOURNAL_NO_ENTRIES

    def test_the_rules_comment_control_is_a_teardown(self):
        assert "# a comment line, which is not a rule" in DERIVED_RULES
        assert len(DERIVED_RULES.splitlines()) == 5
        assert len([l for l in DERIVED_RULES.splitlines()
                    if ananicy_mod._is_rule_line(l)]) == 3

    def test_the_unrecognised_word_control_is_a_teardown(self):
        assert "banana" not in ananicy_mod.ENABLED_WORDS
        assert parse_unit_state("banana\n",
                                ananicy_mod.ENABLED_WORDS) == ""

    def test_the_apply_default_control_is_a_teardown(self):
        """If the page printed a default for an absent key, `apply_sched` would
        carry a value; the control is that the table has seven keys and the
        fixture sets one."""
        assert len(ananicy_mod.APPLY_KEYS) == 7, ananicy_mod.APPLY_KEYS
        parsed = parse_config('{"apply_nice": "on"}')
        assert set(parsed["apply"]) == {"apply_nice"}
        for key in ananicy_mod.APPLY_KEYS:
            if key != "apply_nice":
                assert key not in parsed["apply"], key

    def test_the_write_verb_control_is_a_teardown(self):
        """The closed set must reject a write verb the moment one is added."""
        assert "restart" not in ananicy_mod.READ_ONLY_ARGS
        for candidate in ("restart", "--reload", "stop"):
            assert candidate not in ananicy_mod.READ_ONLY_ARGS, candidate

    def test_the_absent_config_control_is_a_teardown(self):
        parsed = parse_config("")
        assert parsed["ok"] is False
        assert parsed["keys"] == []


# --- helpers ----------------------------------------------------------------


def spin(cond, timeout=8.0) -> bool:
    """Iterate the default main context until cond() holds, or give up.

    `iteration(False)`, never `iteration(True)`: the blocking form would wait
    for an event and return the moment **one** is dispatched, which is fine for
    a test waiting for something that will arrive and wrong for a bound - and
    `ananicy_state` spawns five real `Gio.Subprocess` reads, so its completions
    arrive over the default context and nothing else pumps it.
    """
    ctx = GLib.MainContext.default()
    end = time.monotonic() + timeout
    while not cond() and time.monotonic() < end:
        ctx.iteration(False)
        time.sleep(0.01)
    return cond()


def _all_calls(module) -> list:
    return [n for n in ast.walk(ast.parse(inspect.getsource(module)))
            if isinstance(n, ast.Call)]


def _imported_modules(module) -> set[str]:
    """Every module this one imports, as dotted names."""
    out: set[str] = set()
    for node in ast.walk(ast.parse(inspect.getsource(module))):
        if isinstance(node, ast.Import):
            out.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            out.add(node.module)
    return out


def _imported_names(module) -> set[str]:
    """Every name this module binds with `import X` or `from X import Y`."""
    out: set[str] = set()
    for node in ast.walk(ast.parse(inspect.getsource(module))):
        if isinstance(node, ast.Import):
            out.update(alias.asname or alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            out.update(alias.asname or alias.name for alias in node.names)
    return out


def _calls_to(module, attr: str) -> list:
    tree = ast.parse(inspect.getsource(module))
    return [n for n in ast.walk(tree)
            if isinstance(n, ast.Call) and _called_name(n.func) == attr]


def _called_name(func) -> str:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _argv_strings(module) -> set[str]:
    """Every string literal that reaches an `ss.run_text(...)` argv."""
    tree = ast.parse(inspect.getsource(module))
    out: set[str] = set()
    names = {n.id for n in ast.walk(tree)
             if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
    for call in _calls_to(module, "run_text"):
        for arg in call.args:
            _collect_strings(arg, out, names)
    return out


def _collect_strings(node, out: set[str], names: set[str]) -> None:
    """Every string reachable from one argv expression.

    Descends through `*ARGV_X[1:]`, through a bare module-level list constant,
    and into the arguments of `ss.tool_path_or_self("systemctl")` - which is
    where three of this page's five reads get their tool name. An earlier
    version stopped at the `Subscript`, collected an empty set, and reported
    "no argv found" while the gate it was guarding silently inspected nothing.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        out.add(node.value)
    elif isinstance(node, ast.Starred):
        _collect_strings(node.value, out, names)
    elif isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        for element in node.elts:
            _collect_strings(element, out, names)
    elif isinstance(node, ast.Subscript):
        # `ARGV_IS_ENABLED[1:]` - the constant is on the value side.
        _collect_strings(node.value, out, names)
    elif isinstance(node, ast.Slice):
        _collect_strings(node.value, out, names)
    elif isinstance(node, ast.Call):
        for arg in list(node.args) + [kw.value for kw in node.keywords]:
            _collect_strings(arg, out, names)
    elif isinstance(node, ast.BinOp):
        _collect_strings(node.left, out, names)
        _collect_strings(node.right, out, names)
    elif isinstance(node, ast.Name) and node.id in names:
        # A module-level argv constant: read its value out of the module.
        value = getattr(ananicy_mod, node.id, None)
        if isinstance(value, (list, tuple)):
            for item in value:
                if isinstance(item, str):
                    out.add(item)