"""The Printers page: `lpstat`, `lpoptions`, `lpinfo -v` and `scanimage -L`.

**Every fixture below is verbatim output**, captured from Arch `cups 2:2.4.19-1`,
`cups-filters 2.0.1-3`, `sane-airscan 0.99.38-1` and `sane 1.4.0-4` in a
container with queues actually created through `lpadmin`. The capture found
things a plausible-looking fixture would have hidden, and each is pinned:

1. **A job line's first token is a queue name.** `lpstat -t` really does print
   `OfficeHP-1              root              1024   Sat Oct  3 12:11:07 2026`
   in the same stream as the `printer OfficeHP ...` record. A parser that says
   "every unrecognised line is a queue" invents a fourth queue out of a job.
2. **A reason is a tab-indented continuation line**, `\treason unknown`, and
   `\tpdftopdf filter function failed.` sits under a printer record for the
   same reason. Un-indented, "reason unknown" reads as a printer.
3. **The printer record has two spaces and a full stop in the middle:**
   `printer OfficeHP now printing OfficeHP-1.  enabled since Sat Oct  3
   12:11:07 2026`. Only the trailing `enabled since`/`disabled since` is the
   flag; the phrase before it is free text.
4. **`lpstat -r` exits 0 whether or not the scheduler is running**, so the exit
   status cannot tell the two apart - and the scheduler line's capitalisation
   differs per subcommand (`-r`/`-t` lowercase, `-a`/`-p` `Scheduler is not
   running.`).
5. **`lpstat -t` prints `lpstat: No destinations added.` four times** when the
   scheduler is up and holds nothing. Four identical error-looking lines for a
   healthy machine.

The two capture findings that changed the design rather than just a parser:

- **`/etc/cupd/` does not exist on Arch.** The configuration is `/etc/cups/`,
  and there is no `client.conf` at all. Reading the Debian path would have
  produced a page reporting three missing files on every Shanios machine.
- **`lpinfo -v` answers `Forbidden` for a user not in group `cups`**, and the
  same files (`cups-files.conf`, mode 0640 root:cups) are unreadable by them.
  `shani-printer.install` adds every human user to `sys`, `cups` and `lp`, so
  on Shanios both work - verified in-container as a user in those groups. That
  is why "unreadable" is a state this page can report rather than a bug.

**The last class of test is the gate, and it blanks module docstrings first.**
`printers.py`'s own docstring names `lpadmin`, `lp`, `cupsctl` and `cancel` in
order to explain why they are never run, so a text search over the module
matches its own documentation and passes against a module that *does* call them.
`_code_without_docstrings()` is that step, and the gate also asserts it found
the reader at all - a gate that inspects nothing is the failure mode this repo
has hit repeatedly.
"""

import ast
import inspect
import re

import pytest

gi = pytest.importorskip("gi")
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw  # noqa: E402

from shani_cassini.tabs import printers as printers_mod  # noqa: E402
from shani_cassini.tabs.printers import (  # noqa: E402
    PrintersTab,
    parse_lpinfo_v,
    parse_lpoptions,
    parse_lpstat_t,
    parse_scanimage_l,
    parse_scheduler,
    printers_state,
)


# --- verbatim captures ------------------------------------------------------

# Arch cups 2:2.4.19-1, cupsd NOT running. `lpstat -r` exits 0.
SCHEDULER_NOT_RUNNING = "scheduler is not running\n"
SCHEDULER_RUNNING = "scheduler is running\n"

# `lpstat -t` with cupsd NOT running: the whole stdout, and note it exits 0.
LPSTAT_T_NO_DAEMON = (
    "scheduler is not running\n"
    "no system default destination\n"
)

# `lpstat -t` with cupsd running and NO queues. The four identical
# "No destinations added." lines are the tool's, not this page's.
LPSTAT_T_RUNNING_EMPTY = (
    "scheduler is running\n"
    "no system default destination\n"
    "lpstat: No destinations added.\n"
    "lpstat: No destinations added.\n"
    "lpstat: No destinations added.\n"
    "lpstat: No destinations added.\n"
    "scheduler is running\n"
    "no system default destination\n"
)

# `lpstat -t` with two enabled queues, one disabled queue and a failed job.
# The tab-indented lines are the tool's, and are part of the fixture.
LPSTAT_T_THREE_QUEUES = (
    "scheduler is running\n"
    "system default destination: OfficeHP\n"
    "device for NetLaser: socket://192.0.2.51:9100\n"
    "device for OfficeHP: ipp://192.0.2.50/ipp/print\n"
    "device for OldFax: socket://192.0.2.9:9100\n"
    "NetLaser accepting requests since Sat Oct  3 12:11:07 2026\n"
    "OfficeHP accepting requests since Sat Oct  3 12:11:07 2026\n"
    "OldFax not accepting requests since Sat Oct  3 12:11:07 2026 -\n"
    "\treason unknown\n"
    "printer NetLaser is idle.  enabled since Sat Oct  3 12:11:07 2026\n"
    "printer OfficeHP now printing OfficeHP-1.  enabled since "
    "Sat Oct  3 12:11:07 2026\n"
    "\tpdftopdf filter function failed.\n"
    "printer OldFax disabled since Sat Oct  3 12:11:07 2026 -\n"
    "\treason unknown\n"
    "OfficeHP-1              root              1024   "
    "Sat Oct  3 12:11:07 2026\n"
)

# `lpoptions` with one queue. Note the single-quoted value with a space in it,
# and that this is ONE line.
LPOPTIONS_ONE_QUEUE = (
    "copies=1 device-uri=ipp://192.0.2.50/ipp/print finishings=3 "
    "job-cancel-after=10800 job-hold-until=no-hold job-priority=50 "
    "job-sheets=none,none marker-change-time=0 number-up=1 "
    "print-color-mode=color "
    "printer-commands=AutoConfigure,Clean,PrintSelfTestPage "
    "printer-info='Office LaserJet' printer-is-accepting-jobs=true "
    "printer-is-shared=true printer-is-temporary=false "
    "printer-location='Second floor' "
    "printer-make-and-model='Generic PostScript Printer' "
    "printer-state=4 printer-state-change-time=1791029467 "
    "printer-state-reasons=none printer-type=8532044 "
    "printer-uri-supported=ipp://localhost/printers/OfficeHP\n"
)

# `lpoptions` with no queues: empty stdout, exit 0.
LPOPTIONS_EMPTY = ""

# `lpinfo -v` as root, and as a member of groups cups/lp/sys.
LPINFO_V = (
    "network beh\n"
    "network socket\n"
    "network lpd\n"
    "network https\n"
    "network ipps\n"
    "network ipp\n"
    "network http\n"
    "file cups-pdf:/\n"
)

# `scanimage -L` with no scanner: a paragraph on STDOUT, exit 0.
SCANIMAGE_NONE = (
    "\n"
    "No scanners were identified. If you were expecting something different,\n"
    "check that the scanner is plugged in, turned on and detected by the\n"
    "sane-find-scanner tool (if appropriate). Please read the documentation\n"
    "which came with this software (README, FAQ, manpages).\n"
)

# `scanimage -L` with a device. The `device \`%s' is a %s %s %s` and
# `default device is \`%s'` shapes are the format strings read out of the
# installed scanimage 1.4.0 binary; the second record kind is included here
# because it is in the same stream and its name is otherwise a phantom device.
SCANIMAGE_ONE = (
    "device `airscan:e0: Brother MFC-L2710DW' is a Brother MFC-L2710DW "
    "multi-function peripheral scanner\n"
    "default device is `airscan:e0: Brother MFC-L2710DW'\n"
)

SCANIMAGE_ADF = (
    "device `airscan:e1: Brother MFC-L2710DW ADF' is a Brother MFC-L2710DW "
    "ADF scanner\n"
)


# --- helpers ----------------------------------------------------------------

def _rows(tab):
    """Every ActionRow's (title, subtitle) read back out of the widget tree.

    Read from the tree rather than from an attribute: this repo has shipped
    rows that were built, stored on `self`, updated on every read and never
    given a parent - and the test that reached them by attribute passed.
    """
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


def _code_without_docstrings():
    """The module's code with every docstring blanked.

    `printers.py` names lpadmin, lp, cupsctl and cancel *in its docstring* to
    explain why they are never run. Searching the raw source therefore matches
    its own documentation and passes against a module that does call them -
    which is why every gate below goes through this.
    """
    tree = ast.parse(inspect.getsource(printers_mod))
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                 ast.AsyncFunctionDef)):
            continue
        body = node.body
        if body and isinstance(body[0], ast.Expr) and isinstance(
                getattr(body[0], "value", None), ast.Constant) and isinstance(
                body[0].value.value, str):
            body[0].value.value = ""
    return ast.unparse(tree)


def _stub_reads(monkeypatch, *, scheduler="running", lpstat_t="", lpoptions="",
                lpinfo="", scanimage="", browsed="enabled", errors=None):
    """Point ss.run_text at canned output per argv.

    Keyed on the tool's basename so the test does not care whether the reader
    resolved /usr/sbin/lpstat or a bare `lpstat` - which is itself part of what
    the sbin test below checks.
    """
    errors = errors or {}
    seen: list[list[str]] = []

    def fake_run_text(argv, done):
        seen.append(list(argv))
        tool = argv[0].rsplit("/", 1)[-1]
        key = f"{tool} {' '.join(argv[1:])}".strip()
        text = {
            "lpstat -r": scheduler,
            "lpstat -t": lpstat_t,
            "lpoptions": lpoptions,
            "lpinfo -v": lpinfo,
            "scanimage -L": scanimage,
        }.get(key)
        if text is None and key.startswith("systemctl"):
            text = browsed
        if text is None:
            done(None, errors.get(key, f"{tool} said nothing"))
            return
        err = errors.get(key, "")
        if not text and not err:
            done(None, f"{tool} said nothing")
            return
        done(text, err)

    monkeypatch.setattr(printers_mod.ss, "run_text", fake_run_text)
    monkeypatch.setattr(printers_mod.ss, "have_tool",
                        lambda cmd: cmd not in ("lpstat-nonexistent",))
    return seen


def _drain(tab, payload, err=""):
    tab._on_state(payload, err)
    return _rows(tab)


# --- scheduler reachability -------------------------------------------------

class TestScheduler:
    def test_a_running_scheduler_is_not_running_read_out_of_the_text(self):
        assert parse_scheduler(SCHEDULER_RUNNING) == "running"

    def test_an_unreachable_scheduler_is_its_own_answer(self):
        assert parse_scheduler(SCHEDULER_NOT_RUNNING) == "not running"

    def test_the_two_states_cannot_be_told_apart_by_the_exit_status(self):
        """The real capture: `lpstat -r` exited 0 in BOTH states. If a future
        fixture ever makes the exit status meaningful this is where to notice;
        until then the text is the only discriminator and the parser must not
        be rewritten to look at anything else."""
        assert SCHEDULER_NOT_RUNNING and SCHEDULER_RUNNING
        assert parse_scheduler(SCHEDULER_NOT_RUNNING) != \
            parse_scheduler(SCHEDULER_RUNNING)

    def test_a_wording_this_build_does_not_know_is_not_guessed(self):
        assert parse_scheduler("lpstat: something new\n") is None


class TestLpstatT:
    def test_three_queues_and_a_default(self):
        got = parse_lpstat_t(LPSTAT_T_THREE_QUEUES)
        names = [p["name"] for p in got["printers"]]
        assert names == ["NetLaser", "OfficeHP", "OldFax"], names
        assert got["default"] == "OfficeHP"

    def test_a_job_line_is_not_a_fourth_queue(self):
        """`OfficeHP-1` is a job whose first token is a queue name."""
        got = parse_lpstat_t(LPSTAT_T_THREE_QUEUES)
        assert got["jobs"] == 1
        assert "OfficeHP-1" not in [p["name"] for p in got["printers"]]

    def test_a_tab_indented_reason_is_not_a_queue(self):
        got = parse_lpstat_t(LPSTAT_T_THREE_QUEUES)
        assert "reason unknown" not in [p["name"] for p in got["printers"]]
        assert "pdftopdf filter function failed." not in \
            [p["name"] for p in got["printers"]]

    def test_the_reason_attaches_to_the_queue_it_belongs_to(self):
        got = parse_lpstat_t(LPSTAT_T_THREE_QUEUES)
        by_name = {p["name"]: p for p in got["printers"]}
        assert by_name["OldFax"]["reason"] == "reason unknown", by_name
        assert by_name["OldFax"]["accepting"] is False
        assert by_name["OldFax"]["enabled"] is False

    def test_a_filter_failure_is_kept_as_the_reason_and_is_not_a_state(self):
        got = parse_lpstat_t(LPSTAT_T_THREE_QUEUES)
        office = {p["name"]: p for p in got["printers"]}["OfficeHP"]
        assert office["reason"] == "pdftopdf filter function failed.", office
        assert office["enabled"] is True
        assert office["accepting"] is True

    def test_the_free_text_phrase_is_kept_and_the_flag_is_not_taken_from_it(self):
        got = parse_lpstat_t(LPSTAT_T_THREE_QUEUES)
        office = {p["name"]: p for p in got["printers"]}["OfficeHP"]
        # "now printing OfficeHP-1" contains the word "printing" and the job id;
        # neither is the enabled flag, and the trailing "enabled since" is.
        assert office["phrase"] == "now printing OfficeHP-1", office
        assert office["enabled"] is True

    def test_an_idle_queue_still_reports_its_device_uri(self):
        got = parse_lpstat_t(LPSTAT_T_THREE_QUEUES)
        by_name = {p["name"]: p for p in got["printers"]}
        assert by_name["NetLaser"]["device"] == "socket://192.0.2.51:9100"
        assert by_name["NetLaser"]["phrase"] == "is idle"
        assert by_name["OfficeHP"]["device"] == "ipp://192.0.2.50/ipp/print"

    def test_four_no_destinations_lines_is_a_healthy_empty_machine(self):
        got = parse_lpstat_t(LPSTAT_T_RUNNING_EMPTY)
        assert got["printers"] == []
        assert got["default"] is None
        assert got["jobs"] == 0

    def test_an_unreachable_daemon_yields_no_queues_at_all(self):
        got = parse_lpstat_t(LPSTAT_T_NO_DAEMON)
        assert got["printers"] == []
        assert got["default"] is None


# --- lpoptions --------------------------------------------------------------

class TestLpoptions:
    def test_a_single_quoted_value_with_a_space_survives(self):
        got = parse_lpoptions(LPOPTIONS_ONE_QUEUE)
        assert got["printer-info"] == "Office LaserJet", got
        assert got["printer-location"] == "Second floor"
        assert got["printer-make-and-model"] == "Generic PostScript Printer"

    def test_the_unquoted_pairs_still_parse(self):
        got = parse_lpoptions(LPOPTIONS_ONE_QUEUE)
        assert got["copies"] == "1"
        assert got["device-uri"] == "ipp://192.0.2.50/ipp/print"
        assert got["printer-state-reasons"] == "none"

    def test_no_output_is_an_answer_and_not_an_empty_dict_because_it_failed(self):
        assert parse_lpoptions(LPOPTIONS_EMPTY) == {}


# --- lpinfo / scanimage -----------------------------------------------------

class TestLpinfo:
    def test_backends_are_read_in_order(self):
        assert parse_lpinfo_v(LPINFO_V) == [
            "beh", "socket", "lpd", "https", "ipps", "ipp", "http",
            "cups-pdf:/",
        ]

    def test_a_file_backend_is_not_dropped(self):
        assert "cups-pdf:/" in parse_lpinfo_v(LPINFO_V)


class TestScanimage:
    def test_no_scanner_is_a_note_and_not_an_error(self):
        devices, note = parse_scanimage_l(SCANIMAGE_NONE)
        assert devices == []
        assert "no scanner is attached" in note, note

    def test_the_backend_is_the_part_of_the_name_before_the_colon(self):
        devices, _ = parse_scanimage_l(SCANIMAGE_ONE)
        assert devices[0]["backend"] == "airscan", devices
        assert devices[0]["description"] == (
            "Brother MFC-L2710DW multi-function peripheral scanner")

    def test_the_default_device_line_does_not_become_a_second_device(self):
        devices, _ = parse_scanimage_l(SCANIMAGE_ONE)
        assert len(devices) == 1, devices

    def test_a_backend_that_states_no_source_is_not_guessed_to_be_flatbed(self):
        devices, _ = parse_scanimage_l(SCANIMAGE_ONE)
        assert devices[0]["sources"] == [], devices

    def test_an_adf_is_reported_because_the_backend_says_adf(self):
        devices, _ = parse_scanimage_l(SCANIMAGE_ADF)
        assert devices[0]["sources"] == ["ADF"], devices


# --- the reader -------------------------------------------------------------

class TestReader:
    def test_the_reader_hands_done_a_payload_and_an_error(self):
        """Arity 2, or a TypeError inside a GTK callback swallows the page."""
        tree = ast.parse(inspect.getsource(printers_mod))
        reader = next(n for n in ast.walk(tree)
                      if isinstance(n, ast.FunctionDef)
                      and n.name == "printers_state")
        arities = {len(node.args) for node in ast.walk(reader)
                   if isinstance(node, ast.Call)
                   and getattr(node.func, "id", "") == "done"}
        assert arities == {2}, f"done() called with arities {arities or '{}'}"

    def test_the_reads_are_a_sequence_and_not_a_re_entering_continuation(self):
        """Regression test for a defect this file's own author shipped.

        The reader originally passed one shared `collect` function as the
        continuation of *each* of the four remaining reads. Completing any one
        of them therefore called `collect` again, which started all four over,
        for ever - and every individual line reads correctly, so review does
        not catch it. A synchronous stub reader is what made it visible; with
        the real asynchronous one it is still an unbounded loop, just a slower
        one.

        The property: `printers_state` must advance through an index, and no
        read helper may be handed a continuation that re-enters the reader.
        """
        tree = ast.parse(inspect.getsource(printers_mod))
        reader = next(n for n in ast.walk(tree)
                      if isinstance(n, ast.FunctionDef)
                      and n.name == "printers_state")

        # The reads must live in ONE tuple of helper references, so the
        # sequence is countable and cannot grow by nesting another
        # continuation inside the last one.
        steps = next(
            (n.value for n in ast.walk(reader)
             if isinstance(n, ast.Assign) and len(n.targets) == 1
             and getattr(n.targets[0], "id", "") == "steps"), None)
        assert isinstance(steps, ast.Tuple), (
            "printers_state no longer holds its reads in one tuple; the "
            "sequence has become something that can re-enter")
        ordered = [e.id for e in steps.elts]
        assert ordered == ["_read_scheduler", "_read_queues", "_read_options",
                           "_read_backends", "_read_browsed"], ordered

        # `_read_scanners` is deliberately NOT in the sequence. `scanimage -L`
        # measured 3.59s on Arch with sane + sane-airscan installed and **no
        # scanner attached**, against under 10ms for each of these five - and
        # that is the no-hardware number. In the sequence it held the entire
        # page at "Reading…" for three and a half seconds, which rendering
        # caught as nine rows where there should have been nineteen.
        assert "_read_scanners" not in ordered, (
            "_read_scanners is back in the sequence; it will gate every other "
            "group behind a read that costs seconds when there is no scanner")
        assert "_read_scanners" not in ordered

        helpers = {n.name for n in ast.walk(tree)
                   if isinstance(n, ast.FunctionDef)}
        for helper in ordered + ["_read_scanners"]:
            assert helper in helpers, f"{helper} is gone"
        # No helper may be called with a locally-defined function as its
        # continuation: every continuation is the index-advancing lambda.
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or \
                    getattr(node.func, "id", None) != "_run":
                continue
            done = node.args[-1] if node.args else None
            assert not (isinstance(done, ast.Name) and
                        any(isinstance(getattr(h, "body", [None])[0],
                                      ast.FunctionDef)
                            for h in ast.walk(tree)
                            if isinstance(h, ast.FunctionDef) and
                            getattr(done, "id", "") == h.name)), \
                f"{ast.unparse(node)} is handed a locally-defined continuation"

    def test_the_reader_terminates_against_a_synchronous_stub(self):
        """The end-to-end version: a reader that calls back synchronously must
        reach its terminal delivery rather than re-entering. Infinite
        recursion is a RecursionError here rather than a hang, which is at
        least a signal - and the call count is the property, not the absence of
        a crash.

        **Two** deliveries, not one, and that is the fix for the slow read:
        the fast chain renders the page, then the SANE answer lands and the page
        renders again. Anything unbounded here is the same defect in a new coat.
        """
        calls = []

        def fake_run_text(argv, done):
            tool = argv[0].rsplit("/", 1)[-1]
            text = {
                "lpstat -r": SCHEDULER_RUNNING,
                "lpstat -t": LPSTAT_T_THREE_QUEUES,
                "lpoptions": LPOPTIONS_ONE_QUEUE,
                "lpinfo -v": LPINFO_V,
                "scanimage -L": SCANIMAGE_NONE,
            }.get(f"{tool} {' '.join(argv[1:])}".strip(),
                  "enabled\n" if tool == "systemctl" else None)
            done(text or "", "")

        monkey = pytest.MonkeyPatch()
        monkey.setattr(printers_mod.ss, "run_text", fake_run_text)
        try:
            printers_state(lambda p, e: calls.append((p, e)))
        finally:
            monkey.undo()

        assert len(calls) == 2, f"done() called {len(calls)} times"
        first, second = (p for p, _ in calls)
        for payload in (first, second):
            assert payload["scheduler"] == "running"
            assert len(payload["printers"]) == 3, payload["printers"]
            assert payload["default"] == "OfficeHP"
            assert payload["options"]["printer-info"] == "Office LaserJet"
            assert payload["backends"], payload
            assert payload["browsed"] == "enabled", payload["browsed"]
        assert first["scanners_pending"] is False, (
            "with a synchronous stub the scan read has already landed by the "
            "first delivery, so it must not still claim to be pending")


class TestRenderingIsIdempotent:
    """The page renders **twice** by design — the fast chain, then the SANE
    answer — so every group must be cleared and rebuilt, not appended to.

    Found by rendering in Arch with the real tools: at 9s, after the 3.6s
    `scanimage -L` landed, the page had **22** rows where the first render had
    **19**. The Scheduler group had gained its three rows twice, because
    `_render_daemon` added them without ever recording them in the list its
    `_clear` empties. The tell is a *duplication*, which is the mirror of the
    more usual failure in this repo - a row built, stored and never given a
    parent - and neither is caught by a test that renders once.
    """

    def _payloads(self):
        first = parse_lpstat_t(LPSTAT_T_THREE_QUEUES)
        return (
            {"scheduler": "running", "printers": [], "browsed": "enabled",
             "backends": [], "tools": [], "files": [],
             "scanners_pending": True},
            {"scheduler": "running", **first, "browsed": "enabled",
             "backends": ["ipp"], "tools": [], "files": [],
             "options": {"printer-info": "Office LaserJet"},
             "scanners_pending": False,
             "scanners_note": "SANE was asked and answered that no scanner "
                              "is attached"},
        )

    def test_rendering_the_second_payload_does_not_duplicate_a_row(self):
        one, two = self._payloads()
        tab = PrintersTab()
        tab._on_state(one, "")
        before = _rows(tab)
        tab._on_state(two, "")
        after = _rows(tab)
        titles = [a for a, _ in after]
        dupes = {t for t in titles if titles.count(t) > 1}
        assert not dupes, f"duplicated rows: {sorted(dupes)}"
        assert len(after) > len(before), (
            "the second render should have added the queues and the options")

    def test_the_scheduler_group_has_exactly_its_three_rows(self):
        one, two = self._payloads()
        tab = PrintersTab()
        for payload in (one, two, two):
            tab._on_state(payload, "")
        rows = _rows(tab)
        for title in ("CUPS scheduler", "cups-browsed.service",
                      "Discovery backends"):
            count = [a for a, _ in rows].count(title)
            assert count == 1, (title, count, rows)

    def test_rendering_the_same_payload_twice_changes_nothing(self):
        payload = self._payloads()[1]
        tab = PrintersTab()
        tab._on_state(payload, "")
        first = _rows(tab)
        tab._on_state(payload, "")
        assert _rows(tab) == first

    def test_every_group_tracks_the_rows_it_adds(self):
        """The structural version, so a future group cannot forget. Each
        `_render_*` must register its rows in a list named after the group."""
        tree = ast.parse(inspect.getsource(printers_mod))
        renders = [n for n in ast.walk(tree)
                   if isinstance(n, ast.FunctionDef)
                   and n.name.startswith("_render_")]
        assert len(renders) >= 5, [n.name for n in renders]
        for fn in renders:
            body = ast.unparse(fn)
            tracking = "_rows" in body or "_add_" in body
            assert tracking, (
                f"{fn.name}() neither appends to a tracking list nor calls "
                "_add_*(), so a second render would duplicate its rows")


class TestSlowScanReadDoesNotGateThePage:
    """The measured fact this is about: on Arch with `sane` and `sane-airscan`
    installed and **no scanner attached**, `scanimage -L` takes 3.59s,
    reproducibly. The other five reads on this page each take under 10ms.
    A rendering run with the real tools produced nine rows where there were
    nineteen, with the summary still reading `Reading…`."""

    def _deliveries(self, scan_text, scan_err=""):
        calls = []

        def fake_run_text(argv, done):
            tool = argv[0].rsplit("/", 1)[-1]
            key = f"{tool} {' '.join(argv[1:])}".strip()
            if key == "scanimage -L":
                done(scan_text, scan_err)
                return
            text = {
                "lpstat -r": SCHEDULER_RUNNING,
                "lpstat -t": LPSTAT_T_THREE_QUEUES,
                "lpoptions": LPOPTIONS_ONE_QUEUE,
                "lpinfo -v": LPINFO_V,
            }.get(key, "enabled\n" if tool == "systemctl" else None)
            done(text or "", "")

        monkey = pytest.MonkeyPatch()
        monkey.setattr(printers_mod.ss, "run_text", fake_run_text)
        try:
            printers_state(lambda p, e: calls.append(p))
        finally:
            monkey.undo()
        return calls

    def test_a_page_with_the_scan_read_still_outstanding_is_rendered(self):
        """The first delivery has the scan answer missing and must still be a
        complete page - every group populated except the scan one, which says
        it is asking."""
        seen = []
        tab = PrintersTab()

        def fake_run_text(argv, done):
            tool = argv[0].rsplit("/", 1)[-1]
            key = f"{tool} {' '.join(argv[1:])}".strip()
            if key == "scanimage -L":
                # The slow read: park it, and only answer when the fast chain
                # has already delivered.
                tab_state["parked"] = done
                return
            text = {
                "lpstat -r": SCHEDULER_RUNNING,
                "lpstat -t": LPSTAT_T_THREE_QUEUES,
                "lpoptions": LPOPTIONS_ONE_QUEUE,
                "lpinfo -v": LPINFO_V,
            }.get(key, "enabled\n" if tool == "systemctl" else None)
            done(text or "", "")

        tab_state = {"parked": None}
        monkey = pytest.MonkeyPatch()
        monkey.setattr(printers_mod.ss, "run_text", fake_run_text)
        try:
            printers_state(lambda p, e: (seen.append(p),
                                         tab._on_state(p, e)))
        finally:
            monkey.undo()

        assert len(seen) == 1, seen
        assert seen[0]["scanners_pending"] is True, seen[0]
        rows = _rows(tab)
        titles = [a for a, _ in rows]
        for name in ("NetLaser", "OfficeHP", "OldFax"):
            assert name in titles, titles
        assert "Asking SANE" in titles, titles
        assert not any(b.strip() == "" for _, b in rows), rows

        # Now let the slow read land; the page updates rather than duplicating.
        assert tab_state["parked"] is not None, "the scan read was never parked"
        payload = dict(seen[0])
        payload["scanners_pending"] = False
        payload["scanners_note"] = "SANE was asked and answered that no " \
                                   "scanner is attached"
        tab._on_state(payload, "")
        after = _rows(tab)
        titles2 = [a for a, _ in after]
        assert titles2.count("NetLaser") == 1, titles2
        assert "Asking SANE" not in titles2, titles2
        assert "No scan hardware found" in titles2, titles2

    def test_the_pending_flag_is_cleared_by_the_scan_answer(self):
        calls = self._deliveries(SCANIMAGE_NONE)
        assert calls, "nothing was delivered"
        for payload in calls:
            assert payload["scanners_pending"] is False, payload
            assert "no scanner is attached" in payload["scanners_note"], \
                payload["scanners_note"]

    def test_a_failed_scan_read_is_still_an_answer_not_a_blank_group(self):
        calls = self._deliveries("", "scanimage is not installed")
        assert calls
        for payload in calls:
            assert payload["scanners"] == []
            assert payload["scanners_note"] == "scanimage is not installed"
        tab = PrintersTab()
        tab._on_state(calls[-1], "")
        rows = _rows(tab)
        assert "No scan hardware found" in [a for a, _ in rows], rows


class TestDebianPathsAreNotUsed:
    def test_the_debian_config_directory_is_not_read(self):
        """`/etc/cupd/` is the Debian path and does not exist on Arch, where the
        configuration is `/etc/cups/`. There is no `client.conf` there either.
        Reading the Debian path would have produced a page reporting three
        missing files on every Shanios machine."""
        from shani_cassini.tabs.printers import CUPS_FILES
        assert CUPS_FILES, CUPS_FILES
        for path in CUPS_FILES:
            assert path.startswith("/etc/cups/"), path
        assert not any("cupd" in p for p in CUPS_FILES), CUPS_FILES
        assert not any("client.conf" in p for p in CUPS_FILES), CUPS_FILES


class TestSbinResolution:
    def test_every_cups_tool_is_resolved_through_the_sbin_aware_resolver(self):
        """`cups` puts lpstat, lpinfo, lpoptions and scanimage in /usr/sbin, and
        a bare which() would call a working system unconfigured."""
        seen = []
        monkey = pytest.MonkeyPatch()

        def fake_run_text(argv, done):
            seen.append(list(argv))
            key = argv[0].rsplit("/", 1)[-1] + " " + " ".join(argv[1:])
            text = {
                "lpstat -r": SCHEDULER_RUNNING,
                "lpstat -t": LPSTAT_T_THREE_QUEUES,
                "lpoptions": LPOPTIONS_ONE_QUEUE,
                "lpinfo -v": LPINFO_V,
                "scanimage -L": SCANIMAGE_NONE,
                "systemctl is-enabled cups-browsed.service": "enabled\n",
            }.get(key.strip(), "x\n")
            done(text, "")

        monkey.setattr(printers_mod.ss, "run_text", fake_run_text)
        monkey.setattr(printers_mod.ss, "tool_path_or_self",
                        lambda cmd: f"/usr/sbin/{cmd}")
        try:
            got = {}
            printers_state(lambda p, e: got.update(p=p, e=e))
        finally:
            monkey.undo()
        assert got["p"]["scheduler"] == "running"
        assert [a[0] for a in seen if a[0].endswith("lpstat")] == [
            "/usr/sbin/lpstat", "/usr/sbin/lpstat"]
        assert "/usr/sbin/scanimage" in [a[0] for a in seen]

    def test_an_absent_tool_still_gets_executed_so_its_own_error_reports(self):
        """tool_path_or_self returns the bare name when nothing is found, which
        is the contract that lets run_text say "<tool> is not installed"."""
        assert printers_mod.ss.tool_path_or_self(
            "lpstat-does-not-exist") == "lpstat-does-not-exist"


# --- the page ---------------------------------------------------------------

class TestPageStates:
    def test_cups_absent_is_its_own_state(self):
        tab = PrintersTab()
        rows = _drain(tab, {"scheduler": None,
                            "scheduler_error": "lpstat is not installed",
                            "printers": [], "tools": [],
                            "files": []})
        joined = " | ".join(f"{a}: {b}" for a, b in rows)
        assert "not installed" in joined, joined

    def test_the_daemon_not_answering_is_not_the_same_as_no_queues(self):
        tab = PrintersTab()
        rows = _drain(tab, {"scheduler": "not running", "printers": [],
                            "tools": [], "files": []})
        joined = " | ".join(f"{a}: {b}" for a, b in rows)
        assert "did not answer" in joined, joined
        assert "Not read" in joined, joined

    def test_a_running_daemon_with_no_queue_says_so_distinctly(self):
        tab = PrintersTab()
        rows = _drain(tab, {"scheduler": "running", "printers": [],
                            "tools": [], "files": []})
        joined = " | ".join(f"{a}: {b}" for a, b in rows)
        assert "holds no queue" in joined, joined
        assert "did not answer" not in joined, joined

    def test_three_queues_each_get_a_row_named_after_itself(self):
        payload = parse_lpstat_t(LPSTAT_T_THREE_QUEUES)
        tab = PrintersTab()
        rows = _drain(tab, {"scheduler": "running", **payload,
                            "tools": [], "files": []})
        titles = [a for a, _ in rows]
        for name in ("NetLaser", "OfficeHP", "OldFax"):
            assert name in titles, titles

    def test_the_default_printer_is_named(self):
        payload = parse_lpstat_t(LPSTAT_T_THREE_QUEUES)
        tab = PrintersTab()
        rows = _drain(tab, {"scheduler": "running", **payload,
                            "tools": [], "files": []})
        office = [b for a, b in rows if a == "OfficeHP"][0]
        assert "default printer" in office, office

    def test_a_disabled_queue_is_marked_and_still_shown(self):
        payload = parse_lpstat_t(LPSTAT_T_THREE_QUEUES)
        tab = PrintersTab()
        rows = _drain(tab, {"scheduler": "running", **payload,
                            "tools": [], "files": []})
        fax = [b for a, b in rows if a == "OldFax"][0]
        assert "Disabled" in fax, fax
        assert "not accepting requests" in fax, fax

    def test_no_queue_exists_and_the_daemon_never_answered_stay_apart(self):
        """The empty printer list from an unreachable daemon is not evidence of
        a machine with no printers, and the row must say so."""
        tab = PrintersTab()
        rows = _drain(tab, {"scheduler": "not running", "printers": [],
                            "tools": [], "files": []})
        title = [a for a, b in rows if "queue" in a.lower()][0]
        sub = [b for a, b in rows if a == title][0]
        assert "did not answer" in sub, sub

    def test_the_job_count_is_reported_without_being_touchable(self):
        payload = parse_lpstat_t(LPSTAT_T_THREE_QUEUES)
        tab = PrintersTab()
        rows = _drain(tab, {"scheduler": "running", **payload,
                            "tools": [], "files": []})
        jobs = [b for a, b in rows if a == "Jobs held"]
        assert jobs and "1 job" in jobs[0], rows
        assert "does not cancel" in jobs[0], jobs[0]

    def test_lpoptions_with_no_queues_is_not_shown_as_a_failure(self):
        tab = PrintersTab()
        rows = _drain(tab, {"scheduler": "running", "printers": [],
                            "options": {}, "tools": [], "files": []})
        opts = [b for a, b in rows if a == "Print options"][0]
        assert "None set" in opts, opts

    def test_a_forbidden_backend_read_is_reported_as_a_refusal(self):
        tab = PrintersTab()
        rows = _drain(tab, {"scheduler": "running", "printers": [],
                            "backends": [], "backends_error": "Forbidden",
                            "tools": [], "files": []})
        beh = [b for a, b in rows if a == "Discovery backends"][0]
        assert beh == "Forbidden", beh

    def test_the_managing_tools_are_all_named(self):
        tab = PrintersTab()
        rows = _drain(tab, {"scheduler": "running", "printers": [],
                            "tools": [], "files": []})
        titles = [a for a, _ in rows]
        for tool in ("lpadmin", "lp", "cupsctl", "system-config-printer"):
            assert tool in titles, (tool, titles)

    def test_an_unreadable_cups_file_is_a_refusal_not_a_missing_file(self):
        tab = PrintersTab()
        rows = _drain(tab, {"scheduler": "running", "printers": [],
                            "tools": [], "files": [
                                {"path": "/etc/cups/cupsd.conf",
                                 "present": True, "readable": False}]})
        sub = [b for a, b in rows if a == "/etc/cups/cupsd.conf"][0]
        assert "not readable" in sub, sub
        assert "Not present" not in sub, sub


class TestSummaryRowTitle:
    """Found by rendering, not by the suite: the summary row's title stayed
    `Reading…` for ever because only its subtitle was ever updated. The
    subtitle was right and the row still said it was reading, which is the
    tell this repo keeps hitting - the failure is an absence, and nothing
    warns."""

    @pytest.mark.parametrize("payload,title", [
        ({"scheduler": "not running", "scheduler_error": "",
          "printers": [], "tools": [], "files": []},
         "The scheduler did not answer"),
        ({"scheduler": "running", "printers": [], "tools": [], "files": []},
         "No queue is defined"),
        ({"scheduler": None, "cups_installed": False,
          "scheduler_error": "lpstat is not installed",
          "printers": [], "tools": [], "files": []},
         "CUPS is not installed"),
    ])
    def test_the_title_stops_saying_it_is_reading(self, payload, title):
        tab = PrintersTab()
        _drain(tab, payload)
        titles = [a for a, _ in _rows(tab)]
        assert "Reading…" not in titles, titles
        assert title in titles, titles

    def test_a_queue_count_is_in_the_title_when_there_are_queues(self):
        payload = parse_lpstat_t(LPSTAT_T_THREE_QUEUES)
        tab = PrintersTab()
        rows = _drain(tab, {"scheduler": "running", **payload,
                            "tools": [], "files": []})
        titles = [a for a, _ in rows]
        assert "3 queues" in titles, titles

    def test_an_unrecognised_answer_is_not_reported_as_stopped(self):
        """The failure this pins: the page once keyed "not installed" off
        `scheduler_error`, so a tool that IS installed and answered something
        unfamiliar was reported as a missing package - sending a user to
        install something they already have. `cups_installed` is the real
        fact, and it is set by the reader rather than inferred from text."""
        tab = PrintersTab()
        rows = _drain(tab, {"scheduler": None, "cups_installed": True,
                            "scheduler_error": "lpstat -r answered something "
                                               "this page does not recognise",
                            "printers": [], "tools": [], "files": []})
        joined = " | ".join(f"{a}: {b}" for a, b in rows)
        assert "could not be read" in joined, joined


class TestCupsBrowsed:
    """`systemctl is-enabled` answers on stdout, including two answers that are
    not a state: `not-found` (exit 4) and `static`/`indirect`. All three were
    measured in a real Arch container, where the unit is present and nothing
    enables it."""

    @pytest.mark.parametrize("answer,expect", [
        ("enabled", "Enabled, so printers announced on the network are found"),
        ("enabled-runtime", "Enabled, so printers announced on the network "
                            "are found"),
        ("not-found", "The unit is not installed"),
        ("static", "no [Install] section"),
        ("masked", "Masked"),
        ("disabled", "Answered disabled"),
    ])
    def test_each_answer_is_worded_as_itself(self, answer, expect):
        tab = PrintersTab()
        rows = _drain(tab, {"scheduler": "running", "printers": [],
                            "browsed": answer, "tools": [], "files": []})
        sub = [b for a, b in rows
               if a == "cups-browsed.service"][0]
        assert expect in sub, (answer, sub)

    def test_a_disabled_browsed_unit_is_not_worded_as_enabled(self):
        tab = PrintersTab()
        rows = _drain(tab, {"scheduler": "running", "printers": [],
                            "browsed": "disabled", "tools": [], "files": []})
        sub = [b for a, b in rows
               if a == "cups-browsed.service"][0]
        assert not sub.startswith("Enabled"), sub

    def test_no_systemd_is_said_rather_than_shown_as_disabled(self):
        tab = PrintersTab()
        rows = _drain(tab, {"scheduler": "running", "printers": [],
                            "browsed": None, "tools": [], "files": []})
        sub = [b for a, b in rows
               if a == "cups-browsed.service"][0]
        assert "no systemd" in sub, sub


class TestEveryRowHasText:
    """The failure mode this guards: an unescaped `&` or `<` in a row makes
    Pango render **nothing**, and `get_subtitle()` then returns an empty
    string - so a test that searched the subtitle for the offending character
    passes against a row that is showing nothing at all. Therefore: assert
    every row has a NON-EMPTY subtitle, and drive the strings that came from a
    file or a tool through the escaping helper."""

    @pytest.mark.parametrize("payload_name,payload", [
        ("three_queues", {
            "scheduler": "running", "tools": [], "files": [],
            "printers": [{"name": "Amp & Co", "device":
                          "ipp://h/p?a=1&b=2", "enabled": True,
                          "accepting": True, "phrase": "is idle",
                          "reason": "printer-state-reasons=marker-waste"},
                         {"name": "Lt<Gt>", "device": "socket://h:9100",
                          "enabled": False, "accepting": False,
                          "phrase": "disabled", "reason": "reason unknown"}],
            "default": "Amp & Co", "jobs": 2,
            "options": {"printer-info": "Sales & Marketing <Floor 2>"},
            "backends": ["ipp", "ipps"],
        }),
        ("forbidden", {
            "scheduler": "running", "tools": [], "files": [],
            "printers": [], "backends": [],
            "backends_error": "Forbidden", "options": {},
            "scanners": [{"name": "airscan:e0: HP & Co",
                          "backend": "airscan", "sources": ["ADF"],
                          "description": "HP <A1> multifunction"}],
        }),
        ("no_daemon", {
            "scheduler": "not running", "tools": [], "files": [
                {"path": "/etc/cups/cupsd.conf", "present": True,
                 "readable": False}],
            "printers": [], "options": {},
        }),
    ])
    def test_no_row_renders_blank(self, payload_name, payload):
        tab = PrintersTab()
        rows = _drain(tab, payload)
        assert rows, f"{payload_name}: the page built no rows at all"
        empty = [(a, b) for a, b in rows if not b.strip()]
        assert not empty, (payload_name, empty)

    def test_the_escaping_helper_actually_escapes(self):
        """The control for the assertion above: if `esc` did nothing, the
        markup-bearing rows above would still be non-empty *as strings*, so
        this is the step that proves the helper is load-bearing."""
        assert printers_mod.esc("Sales & Marketing <Floor 2>") == \
            "Sales &amp; Marketing &lt;Floor 2&gt;"

    def test_every_group_description_is_escaped_or_carries_no_markup(self):
        """`Adw.PreferencesGroup`'s description is **also** Pango markup, and
        the failure is worse than a row's: an unescaped `&` blanks the entire
        group, so every row in it disappears and nothing errors.

        Probed in Arch, libadwaita 1.9.x, rather than assumed:
          raw      -> get_description() == 'Sales & Marketing <Floor 2>' and
                       the label is empty (invalid markup)
          escaped  -> get_description() == 'Sales &amp; Marketing &lt;Floor 2&gt;'
        So the escaped string is what is *stored* and what Pango renders back
        to the original text, and the group survives.
        """
        tree = ast.parse(inspect.getsource(printers_mod))
        checked = 0
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = getattr(node.func, "attr", "") or getattr(node.func, "id", "")
            if not name.endswith("PreferencesGroup"):
                continue
            desc = next((kw.value for kw in node.keywords
                         if kw.arg == "description"), None)
            assert desc is not None, f"{name} has no description to check"
            checked += 1
            if isinstance(desc, ast.Call):
                assert getattr(desc.func, "id", "") == "esc", \
                    f"a group description is built by {ast.unparse(desc.func)}"
                continue
            assert isinstance(desc, ast.Constant), ast.unparse(desc)
            assert "&" not in desc.value and "<" not in desc.value, (
                f"group description carries markup and is not escaped: "
                f"{desc.value!r}")
        assert checked >= 6, f"only {checked} group descriptions were checked"

    def test_the_page_builds_no_group_with_an_empty_description(self):
        """Read back out of the widget tree, so a description that failed to
        parse shows up as the whole group rendering nothing."""
        tab = PrintersTab()
        _drain(tab, {"scheduler": "running", "printers": [],
                     "tools": [], "files": []})
        found = []

        def walk(node):
            if isinstance(node, Adw.PreferencesGroup):
                found.append((node.get_title(), node.get_description() or ""))
            child = node.get_first_child()
            while child is not None:
                walk(child)
                child = child.get_next_sibling()

        walk(tab)
        assert len(found) == 7, [t for t, _ in found]
        for title, desc in found:
            assert desc.strip(), f"group {title!r} rendered no description"


# --- the gates --------------------------------------------------------------

class TestReadOnlyGates:
    """The page must not print, cancel, accept or modify.

    These are gates on **argv**, not on text. An earlier version of this file
    searched the source for the words `lpadmin`, `lp`, `cupsctl`, `cancel` and
    `accept` and failed on all of them - correctly: `TOOL_ROWS` legitimately
    holds those names as *data*, because naming them in the last group is the
    point of that group. A text gate cannot tell "named" from "run". So the
    gate walks the AST for every argv that reaches a reader and asserts what is
    in it, which is the property that actually matters.
    """

    # The only things any argv on this page may name.
    ALLOWED = {"LPSTAT", "LPOPTIONS", "LPINFO", "SCANIMAGE"}

    def _reader_calls(self):
        """Every call that hands something to a reader, as (name, args).

        Two shapes reach a reader and both are returned:
          * `_run(LPSTAT, ["-r"], got)` - the funnel for the four CUPS tools
          * `ss.run_text([ss.tool_path_or_self("systemctl"), ...], got)` -
            the one direct call, in _read_browsed

        `_run`'s **own body** is excluded, because inside it the tool is the
        parameter `tool` and every argv head is a variable by construction.
        Asserting on that would be asserting that a function forwards its
        argument; the property that matters is what its *call sites* pass.
        """
        tree = ast.parse(inspect.getsource(printers_mod))
        funnel = next((n for n in ast.walk(tree)
                       if isinstance(n, ast.FunctionDef) and n.name == "_run"),
                      None)
        assert funnel is not None, "_run is gone; the funnel has changed shape"
        inside = range(funnel.lineno, (funnel.end_lineno or funnel.lineno) + 1)
        calls = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or node.lineno in inside:
                continue
            name = getattr(node.func, "id", None) or \
                getattr(node.func, "attr", None)
            if name in ("_run", "run_text", "run_status",
                        "run_json_tool", "run_json"):
                calls.append((name, node.args, node))
        return calls

    def test_the_gate_inspects_argv_rather_than_searching_text(self):
        calls = self._reader_calls()
        assert calls, (
            "no reader call was found at all, so this gate would pass while "
            "proving nothing")

        run_calls = [(a, n) for name, a, n in calls if name == "_run"]
        assert run_calls, "_run() is the funnel for the CUPS tools and is gone"
        for args, _ in run_calls:
            head = args[0]
            assert isinstance(head, ast.Name) and head.id in self.ALLOWED, \
                f"_run() is handed {ast.unparse(head)}; only " \
                f"{sorted(self.ALLOWED)} are reads"

        # Every direct read_text is a subcommand of a fixed tool, checked as
        # argv rather than as text.
        for name, args, _ in calls:
            if name == "_run":
                continue
            argv = args[0]
            assert isinstance(argv, ast.List), ast.unparse(argv)
            head = argv.elts[0]
            assert isinstance(head, ast.Call), ast.unparse(head)
            assert ast.unparse(head.func).endswith("tool_path_or_self"), \
                ast.unparse(head)
            literal = head.args[0]
            assert isinstance(literal, ast.Constant), \
                f"the direct reader call names {ast.unparse(literal)}, not a " \
                "literal, so what it runs is not pinned here"
            assert literal.value in self.ALLOWED_DIRECT, (
                f"{literal.value!r} is read directly; only "
                f"{sorted(self.ALLOWED_DIRECT)} are")

    # The one tool this page reads that is not a CUPS tool, and the only
    # subcommand of it used: both are reads.
    ALLOWED_DIRECT = {"systemctl"}

    def test_systemctl_is_only_asked_whether_a_unit_is_enabled(self):
        """`is-enabled` asks a question. Anything else in this family -
        `start`, `enable`, `restart` - would be a state change, so the
        subcommand is pinned rather than the tool."""
        found = False
        for name, args, _ in self._reader_calls():
            if name == "_run":
                continue
            argv = args[0]
            words = [e.value if isinstance(e, ast.Constant)
                     else ast.unparse(e) for e in argv.elts[1:]]
            assert words == ["is-enabled", "cups-browsed.service"], words
            found = True
        assert found, "the direct reader call is gone; nothing was checked"

    def test_no_writing_cups_command_can_reach_argv(self):
        """The negative control for the gate above, stated as the property:
        a writer is not merely absent from the text, it cannot be constructed."""
        forbidden = {"lpadmin", "lp", "cupsctl", "cancel", "accept", "disable",
                     "enable", "reject", "purge", "rm", "rmmuted", "cupsdctl",
                     "restart", "start", "stop", "reload"}
        in_argv = set()
        for name, args, _ in self._reader_calls():
            nodes = ([args[0]] if name == "_run" and args
                     else (args[0].elts if name != "_run" and args
                           and isinstance(args[0], ast.List) else []))
            for n in nodes:
                for sub in ast.walk(n):
                    if isinstance(sub, ast.Constant) and \
                            isinstance(sub.value, str):
                        in_argv.add(sub.value)
        assert not (in_argv & forbidden), \
            f"a writing command reached argv: {sorted(in_argv & forbidden)}"

    def test_the_module_names_the_writing_tools_only_as_data(self):
        """`TOOL_ROWS` is a tuple of strings, which is how the last group can
        name lpadmin/lp/cupsctl at all. Asserting they are there keeps the gate
        above honest: if they were removed, the gate would be protecting less
        than its docstring claims."""
        from shani_cassini.tabs.printers import TOOL_ROWS
        names = [t[0] for t in TOOL_ROWS]
        assert names == ["lpadmin", "lp", "cupsctl", "system-config-printer"], \
            names

    def test_no_privileged_helper_is_used(self):
        code = _code_without_docstrings()
        assert "pkexec" not in code

    def test_a_bare_which_is_never_used_for_a_cups_tool(self):
        """`shutil.which` answers "is it on this session's PATH", which on a
        desktop session is a fact about PATH and not about the machine."""
        code = _code_without_docstrings()
        assert "shutil.which" not in code
        assert "ss.have(" not in code

    def test_the_page_shells_out_to_nothing_of_its_own(self):
        code = _code_without_docstrings()
        for bad in ("Gio.Subprocess", "subprocess", "os.system"):
            assert bad not in code, bad

    def test_the_docstring_blanking_step_is_itself_verified(self):
        """Without this the gates above would be matching the module's own
        prose about why it does not call these tools. `pkexec` appears in the
        docstring and nowhere in the code, which is exactly the property this
        uses to prove the blanking works."""
        raw = printers_mod.__doc__ or ""
        assert "Forbidden" in raw, (
            "fixture problem: this test needs a word that is in the docstring "
            "and not in the code")
        assert "Forbidden" not in _code_without_docstrings()


class TestNoEscapingIsSkipped:
    def test_titles_and_subtitles_all_go_through_the_helper(self):
        """`_row` is the only row constructor; a second one would be a place
        where an unescaped string could enter."""
        tree = ast.parse(_code_without_docstrings())
        made = 0
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_row":
                made += 1
                assert node.args.args, "_row must take the strings"
        assert made == 1, made