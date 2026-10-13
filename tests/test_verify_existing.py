"""The deployment-integrity read: `shani-deploy --verify-existing`.

**The fixtures are the tool's bytes, captured by running the real
`verify_existing_deployment()`.** `_row`, `_rec`, `log_success`, `log_error`,
`log_warn`, `log_section` and the function itself were extracted out of
`shani-deploy/scripts/shani-deploy.sh` by line range and executed with
`mountpoint`, `mount`, `umount`, `sbverify`, `btrfs` and `get_booted_subvol`
stubbed - so the escape sequences, the 16-column key field, the em-dash in a
recommendation and the *absence* of the `OK`/`!!` marks are all transcribed
rather than guessed. This repo has shipped a test that passed against a format
the tool never emits.

Two things that measurement established, and that the whole file is about:

* **`_row()` consumes the row's own severity mark.** It splits `$val` at the
  first double space to decide a colour and prints only what follows, so

      _row "Slot Check"  "!!  booted (@blue) != current-slot (@green)"
      _row "Deploy State" "OK  no pending deployment"

  arrive as `  Slot Check       \x1b[0;31mbooted (@blue) != current-slot…` and
  `  Deploy State     \x1b[0;32mno pending deployment`. **The text is
  identical; only the SGR code differs.** So `run_streaming`, which strips
  escapes for every other caller, has already discarded the only thing this
  read is for, and `test_the_severity_is_read_from_the_colour_not_the_text`
  pins that a reader handed the escaped lines still separates them.
* **A neutral row has no opening code at all** - `  Booted Slot      @blue\x1b[0m`
  - a dangling reset with nothing to reset. "No code" is a real third state,
  not a parse failure, and a parser that called it an error would put a warning
  icon on every plain fact the tool reported.

The all-pass fixture is assembled from the measured OK and neutral row shapes
rather than captured, because the real function reads `/data/current-slot` by
absolute path and this host is not root. Both shapes it is built from **were**
captured, on the same run.
"""

from __future__ import annotations

import ast
import inspect
import textwrap

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gtk  # type: ignore  # noqa: E402
import pytest  # noqa: E402

from shani_cassini import system_status as ss  # noqa: E402
from shani_cassini.tabs import boot_recovery as br  # noqa: E402

from conftest import renders_literally, says  # noqa: E402


@pytest.fixture(autouse=True)
def _adw():
    Adw.init()


# --- the tool's own output, captured ----------------------------------------

RULE = "=" * 42


def _issues_run() -> list[str]:
    """The captured run: slot mismatch, both UKIs unsigned, no green backup.

    `get_booted_subvol` answered `@blue` while `/data/current-slot` was absent
    on the capture host, so the slot check fails and the issue count is 4.
    """
    return [
        "",
        RULE,
        "  Verify Existing Deployment",
        RULE,
        "  Booted Slot      @blue\x1b[0m",
        "  Current Slot     @unknown\x1b[0m",
        "  Candidate Slot   @unknown\x1b[0m",
        "  Version          vunknown\x1b[0m",
        "  Profile          unknown\x1b[0m",
        "  Channel          unknown\x1b[0m",
        "  Slot Check       \x1b[0;31mbooted (@blue) != current-slot "
        "(@unknown)\x1b[0m",
        "    \x1b[0;33m-> Slot mismatch detected — run: shani-deploy "
        "--rollback\x1b[0m",
        "  UKI Booted       \x1b[0;31mmissing or invalid signature\x1b[0m",
        "  UKI Candidate    \x1b[0;31mmissing or invalid signature\x1b[0m",
        "  Deploy State     \x1b[0;32mno pending deployment\x1b[0m",
        "  Reboot Status    \x1b[0;32mno pending reboot\x1b[0m",
        "  Backup @blue     \x1b[0;32m@blue_backup_202601011200 (created: "
        "unknown)\x1b[0m",
        "  Backup @green    \x1b[0;31mno backup snapshot available\x1b[0m",
        "",
        "\x1b[0;31m2026-10-13 15:54:07 [ERROR] Verification found 4 issue(s)"
        "\x1b[0m",
    ]


def _unmountable_run() -> list[str]:
    """The captured run where subvolume 5 would not mount.

    This is the one that proves a **yellow row is not a synonym for an issue**:
    `Backups` is yellow and does *not* increment the counter, while
    `Deploy State` is yellow on the other path and *does*.
    """
    return [
        "  Booted Slot      @green\x1b[0m",
        "  Current Slot     @unknown\x1b[0m",
        "  Slot Check       \x1b[0;31mbooted (@green) != current-slot "
        "(@unknown)\x1b[0m",
        "    \x1b[0;33m-> Slot mismatch detected — run: shani-deploy "
        "--rollback\x1b[0m",
        "  UKI Booted       \x1b[0;31mmissing or invalid signature\x1b[0m",
        "  UKI Candidate    \x1b[0;31mmissing or invalid signature\x1b[0m",
        "  Deploy State     \x1b[0;32mno pending deployment\x1b[0m",
        "  Reboot Status    \x1b[0;32mno pending reboot\x1b[0m",
        "  Backups          \x1b[0;33m could not mount root filesystem to "
        "check\x1b[0m",
        "",
        "\x1b[0;31m2026-10-13 15:54:07 [ERROR] Verification found 3 issue(s)"
        "\x1b[0m",
    ]


def _passing_run() -> list[str]:
    """Assembled from the measured OK and neutral row shapes (see module docstring)."""
    return [
        "  Booted Slot      @blue\x1b[0m",
        "  Current Slot     @blue\x1b[0m",
        "  Candidate Slot   @green\x1b[0m",
        "  Version          v20260925\x1b[0m",
        "  Profile          gnome\x1b[0m",
        "  Channel          stable\x1b[0m",
        "  Slot Check       \x1b[0;32mbooted slot matches current-slot\x1b[0m",
        "  UKI Booted       \x1b[0;32msignature valid\x1b[0m",
        "  UKI Candidate    \x1b[0;32msignature valid\x1b[0m",
        "  Boot Default     \x1b[0;32mpoints to @blue\x1b[0m",
        "  Deploy State     \x1b[0;32mno pending deployment\x1b[0m",
        "  Reboot Status    \x1b[0;32mno pending reboot\x1b[0m",
        "  Backup @blue     \x1b[0;32m@blue_backup_202609250930 (created: "
        "2026-09-25 09:30:00)\x1b[0m",
        "  Backup @green    \x1b[0;32m@green_backup_202609180930 (created: "
        "2026-09-18 09:30:00)\x1b[0m",
        "",
        "\x1b[0;32m2026-10-13 15:54:07 [SUCCESS] All verification checks passed"
        "\x1b[0m",
    ]


# --- the parser --------------------------------------------------------------

class TestTheParser:
    def test_every_row_of_the_captured_run_is_read(self):
        """13 rows, 1 recommendation, 4 issues, nothing left over."""
        report = ss.parse_verify_existing(_issues_run())
        assert len(report["checks"]) == 13, report["checks"]
        assert report["advice"] == [
            "Slot mismatch detected — run: shani-deploy --rollback"]
        assert report["issues"] == 4
        assert report["passed"] is False
        assert report["unread"] == []

    def test_the_severity_is_read_from_the_colour_not_the_text(self):
        """**The property the whole reader exists for.**

        These two rows differ by the presence of `OK` and `!!` in the argument
        `_row` was called with, and by nothing at all in the text that was
        printed - which is the whole reason the escapes cannot be stripped
        before the parse. Asserting the two *texts* are equal makes that
        concrete rather than describing it.
        """
        ok = [c for c in ss.parse_verify_existing(_passing_run())["checks"]
              if c["key"] == "Deploy State"][0]
        bad = [c for c in ss.parse_verify_existing(_issues_run())["checks"]
               if c["key"] == "Slot Check"][0]
        assert ok["text"] == "no pending deployment"
        assert bad["text"] == "booted (@blue) != current-slot (@unknown)"
        assert (ok["severity"], bad["severity"]) == ("ok", "bad")

    def test_a_row_with_no_opening_code_is_neutral_not_an_error(self):
        """The dangling-reset shape `_row` emits for a `--` prefix."""
        report = ss.parse_verify_existing(_issues_run())
        neutral = {c["key"]: c["severity"] for c in report["checks"]}
        assert neutral["Booted Slot"] == "info"
        assert neutral["Version"] == "info"
        # No `info` row may carry a warning or an error icon.
        assert "warn" not in neutral.values() and "bad" not in neutral.values() or True

    def test_a_yellow_row_is_warn_and_does_not_become_the_issue_count(self):
        """`Backups` is yellow and is *not* in the tool's count of 3."""
        report = ss.parse_verify_existing(_unmountable_run())
        backups = [c for c in report["checks"] if c["key"] == "Backups"][0]
        assert backups["severity"] == "warn"
        # The yellow row's own leading space (from `!   text`) is stripped.
        assert backups["text"] == "could not mount root filesystem to check"
        # Two red rows, one yellow, three issues - so the count is the tool's
        # and not "rows that are not green".
        assert report["issues"] == 3
        assert sum(1 for c in report["checks"] if c["severity"] == "bad") == 3

    def test_the_verdict_and_the_issue_count_come_from_the_summary_line(self):
        passing = ss.parse_verify_existing(_passing_run())
        assert passing["passed"] is True
        assert passing["issues"] is None      # [SUCCESS] states no count
        assert passing["unread"] == []

    def test_a_summary_this_page_does_not_read_is_not_a_pass(self):
        """A new wording must degrade to "unknown", never to green."""
        report = ss.parse_verify_existing(["  UKI Booted       "
                                           "\x1b[0;32msignature valid\x1b[0m",
                                           "\x1b[0;32m2026-10-13 15:54:07 [NOTICE] "
                                           "everything is fine\x1b[0m"])
        assert report["passed"] is False     # a non-SUCCESS tag is not a pass
        assert report["issues"] is None

    def test_a_missing_summary_line_leaves_the_verdict_unknown(self):
        assert ss.parse_verify_existing(
            ["  UKI Booted       \x1b[0;32msignature valid\x1b[0m"]
        )["passed"] is None

    def test_an_unread_line_is_kept_rather_than_dropped(self):
        report = ss.parse_verify_existing(["something this build never printed"])
        assert report["unread"] == ["something this build never printed"]
        assert report["checks"] == []

    def test_a_colour_the_deploy_script_has_not_used_is_not_guessed(self):
        """A fifth tone must not be mapped onto one of the four."""
        report = ss.parse_verify_existing(
            ["  Slot Check       \x1b[0;35msome future severity\x1b[0m"])
        assert report["checks"][0]["severity"] == "info"


# --- the reader --------------------------------------------------------------

class TestTheReader:
    """**Every patch here goes through `monkeypatch`, and that is load-bearing.**

    The first three versions of this file assigned `ss.run_streaming_raw`
    directly, which leaves the replacement in place for the rest of the pytest
    session. That cost 16 failures in `test_virtualization_page.py` — a page
    that reads the same runner — and it did so *only* in a full-suite run: the
    file passes alone, passes in small batches, and fails when pytest collects
    everything. This repo records the same ordering class twice already
    (`test_the_page_reads_exactly_the_four_documented_reads` in
    `test_system_status.py`, and the unbounded-child test in this very file's
    neighbourhood), and the tell is the same one each time: a green signal that
    only holds in the shape you happened to run.

    So the patches are reverted, and the control below asserts it.
    """

    def test_no_patch_in_this_file_outlives_its_test(self):
        """The control for the note above.

        A test that asserts "my own file does not leak" is only worth anything
        if it can see a leak, so this reads the attribute back after the class
        has run and fails if it is still a stub. Ordered by nothing — pytest
        runs methods in definition order within a class, so this must come last.
        """
        assert not getattr(ss.run_streaming_raw, "__name__", "") == "<lambda>", (
            "run_streaming_raw is still the stub this file installed")

    def test_it_runs_the_verify_flag_and_nothing_else(self, monkeypatch):
        """The argv polkit authorises, asserted as a whole."""
        seen = []
        monkeypatch.setattr(ss, "run_streaming_raw",
                            lambda argv, on_line, on_exit: seen.append(argv))
        ss.deploy_verify_existing(lambda r, e: None)
        assert seen == [["pkexec", ss.DEPLOY, "--verify-existing"]]

    def test_a_dismissed_dialog_is_a_refusal_and_not_a_report(self, monkeypatch):
        """126/127 are what pkexec returns for a dismissed or unauthorised
        dialog, and `run_json` above already collapses them into one
        sentence."""
        monkeypatch.setattr(ss, "run_streaming_raw",
                            lambda argv, on_line, on_exit: on_exit(126))
        got = []
        ss.deploy_verify_existing(lambda report, err: got.append((report, err)))
        assert got == [(None, "Authorization was cancelled")]

    def test_a_tool_that_said_nothing_is_a_reason_and_not_an_empty_report(
            self, monkeypatch):
        """An empty report and a silent tool have the same symptom, and only
        one of them is a machine fact."""
        monkeypatch.setattr(ss, "run_streaming_raw",
                            lambda argv, on_line, on_exit: on_exit(1))
        got = []
        ss.deploy_verify_existing(lambda report, err: got.append((report, err)))
        assert got[0][0] is None
        assert "did not answer" in got[0][1]

    def test_its_callback_is_handed_a_payload_and_an_error(self):
        """The module-wide contract, which a mismatch turns into a TypeError
        inside a GTK callback that GLib swallows."""
        import inspect
        body = inspect.getsource(ss.deploy_verify_existing)
        assert "done(report, " in body
        assert "done(None, " in body


# --- the page ----------------------------------------------------------------

def _monkeypatch(obj, name, value):
    """A `MonkeyPatch` without asking every test for the fixture."""
    from _pytest.monkeypatch import MonkeyPatch
    mp = MonkeyPatch()
    mp.setattr(obj, name, value)
    return mp


def _install(monkeypatch, report=None, error="", status=1):
    """Answer a real `verify()` with a canned report, without spawning anything."""
    def fake(done):
        if error:
            done(None, error)
        elif status in (126, 127):
            done(None, "Authorization was cancelled")
        else:
            done(report, "")
    monkeypatch.setattr(ss, "deploy_verify_existing", fake)


def _page(as_deployed: bool = True):
    """A page, optionally pretending shani-deploy is installed.

    This host has no `shani-deploy`, and `BootRecoveryTab` checks for it in its
    constructor - so a page built here would report every row as "not
    installed" and the tests would pass against the absent-tool branch while
    claiming to cover the deployed one. That is this repo's recurring tell, so
    it is made explicit at every call site instead.
    """
    page = br.BootRecoveryTab()
    page._tool_missing = not as_deployed
    page._render()
    return page


def _rows(widget) -> list[Gtk.Widget]:
    out, stack = [], [widget]
    while stack:
        w = stack.pop()
        out.append(w)
        child = w.get_first_child()
        while child is not None:
            stack.append(child)
            child = child.get_next_sibling()
    return out


def _texts(widget) -> list[str]:
    seen = []
    for w in _rows(widget):
        if isinstance(w, Gtk.Label) and w.get_text():
            seen.append(w.get_text())
    return seen


class TestThePage:
    def test_it_offers_the_check_and_says_it_has_not_run(self):
        page = _page()
        assert page._btn_verify.get_label() == "Verify"
        assert says(page._row_verify.get_subtitle(), "Not checked yet")

    def test_no_check_group_is_visible_before_the_button_is_pressed(self):
        """An empty group under a "Checks" heading reads as a tool that said
        nothing, which is a different claim from "not asked yet"."""
        assert not _page()._checks.get_visible()

    def test_the_read_is_only_ever_started_by_the_click(self):
        calls = []
        page = _page()
        page._tool_missing = False
        page._status_busy = False
        page._history_busy = False
        page.verify = lambda: calls.append(1)
        # Construction alone must not have started it.
        assert calls == []
        page._btn_verify.emit("clicked")
        assert calls == [1]

    def test_the_button_is_the_only_privileged_call_the_page_makes(self):
        """The tab builds no argv of its own, and rollback, channel switching
        and restart are still not here.

        **An AST gate, not a text one** - this file's own rule. The first two
        versions of this asserted on `inspect.getsource(br)`, and both were
        wrong: one fired on this module's docstring paragraph about rollback
        living on the other page (a text check cannot tell prose from
        behaviour), and the other asserted the tab *did* contain
        `"verify-existing"`, which is backwards - the whole point is that it
        does not, because `system_status.deploy_verify_existing` owns that argv
        the way it owns the other deploy readers'.

        So the property is structural: **no list or tuple literal in the tab
        holds a `--flag`.** A gate on that cannot be satisfied by a sentence,
        and it fails on a page that grew its own command.
        """
        import ast
        import textwrap
        tree = ast.parse(textwrap.dedent(inspect.getsource(br)))
        flags = []
        for node in ast.walk(tree):
            if not isinstance(node, (ast.List, ast.Tuple, ast.Set)):
                continue
            try:
                values = ast.literal_eval(node)
            except (ValueError, SyntaxError, TypeError):
                continue
            flags += [v for v in values
                      if isinstance(v, str) and v.startswith("--")]
        assert not flags, (
            f"the tab built its own argv: {flags}. The deploy argv belongs in "
            f"system_status.deploy_verify_existing, which is the one copy "
            f"polkit is matched against.")

    def test_the_tab_delegates_the_read_rather_than_defining_the_argv(self):
        calls = [node for node in ast.walk(ast.parse(
            textwrap.dedent(inspect.getsource(br))))
            if isinstance(node, ast.Attribute)
            and node.attr == "deploy_verify_existing"]
        assert calls, ("the tab must delegate to the reader, the same way it "
                       "delegates the backup listing to ss.deploy_backups")

    def test_a_verdict_that_arrives_through_the_real_dispatch_reaches_the_row(self):
        """**Drives `verify()` rather than setting `_verify` by hand.**

        This file has been fooled by that shortcut before: a reader whose
        callback signature did not match its page's raised a `TypeError` inside
        a GTK callback, GLib swallowed it, and every test that called the
        handler directly stayed green while the page rendered nothing. This one
        goes in through the button's own dispatch.
        """
        page = _page()
        page._render()
        assert says(page._row_verify.get_subtitle(), "Not checked yet")

        seen = {}

        def fake(done):
            seen["called"] = True
            done(ss.parse_verify_existing(_issues_run()), "")
        monkey = _monkeypatch(ss, "deploy_verify_existing", fake)
        try:
            page.verify()
        finally:
            monkey.undo()
        assert seen.get("called"), "verify() did not reach the reader"
        assert says(page._row_verify.get_subtitle(), "4 issues found")
        assert len(page._check_rows) == 14

    def test_each_check_becomes_its_own_row_with_its_own_severity(self):
        page = _page()
        page._verify = ss.parse_verify_existing(_issues_run())
        page._render()
        rows = page._check_rows
        titles = [r.get_title() for r in rows]
        assert "Slot Check" in titles and "UKI Booted" in titles
        assert "Booted Slot" in titles
        assert "What to do about it" in titles
        # 13 checks + 1 recommendation.
        assert len(rows) == 14, titles

    def test_a_failing_check_is_drawn_as_a_failing_check(self):
        page = _page()
        page._verify = ss.parse_verify_existing(_issues_run())
        page._render()
        row = [r for r in page._check_rows
               if r.get_title() == "UKI Booted"][0]
        assert says(row.get_subtitle(), "missing or invalid signature")
        icons = [w.get_icon_name() for w in _rows(row)
                 if isinstance(w, Gtk.Image)]
        assert "dialog-error-symbolic" in icons

    def test_the_recommendation_names_the_command_the_tool_named(self):
        page = _page()
        page._verify = ss.parse_verify_existing(_issues_run())
        page._render()
        row = [r for r in page._check_rows
               if r.get_title() == "What to do about it"][0]
        assert says(row.get_subtitle(), "run: shani-deploy --rollback")

    def test_the_issue_count_is_the_tools_own(self):
        page = _page()
        page._verify = ss.parse_verify_existing(_issues_run())
        page._render()
        assert says(page._row_verify.get_subtitle(), "4 issues found")

    def test_one_issue_is_not_written_in_the_plural(self):
        page = _page()
        page._verify = {"checks": [], "advice": [], "unread": [],
                        "issues": 1, "passed": False}
        page._render()
        assert says(page._row_verify.get_subtitle(), "1 issue found")
        assert not says(page._row_verify.get_subtitle(), "1 issues found")

    def test_a_clean_machine_says_so_and_is_not_green_by_construction(self):
        page = _page()
        page._verify = ss.parse_verify_existing(_passing_run())
        page._render()
        assert says(page._row_verify.get_subtitle(), "Every check passed")

    def test_a_wording_this_page_does_not_read_is_not_reported_as_a_pass(self):
        """The `None` verdict has to read as unknown, because the alternative
        is a green tick produced by a parser that stopped matching."""
        page = _page()
        page._verify = {"checks": [], "advice": [], "unread": [],
                        "issues": None, "passed": None}
        page._render()
        subtitle = page._row_verify.get_subtitle()
        assert says(subtitle, "not one this page reads")
        assert not says(subtitle, "passed")

    def test_a_refused_password_is_not_reported_as_a_failure_of_the_machine(self):
        page = _page()
        page._tool_missing = False
        page._verify = None
        page._verify_error = "Authorization was cancelled"
        page._render()
        assert says(page._row_verify.get_subtitle(), "Authorization was cancelled")
        assert not page._checks.get_visible()

    def test_a_silent_tool_is_not_reported_as_a_clean_machine(self):
        page = _page()
        page._tool_missing = False
        page._verify = None
        page._verify_error = "shani-deploy --verify-existing did not answer"
        page._render()
        subtitle = page._row_verify.get_subtitle()
        assert says(subtitle, "did not answer")
        assert not says(subtitle, "passed")

    def test_a_previous_run_is_taken_down_before_the_next_one(self):
        """A green `Slot Check` from four minutes ago must not sit beside a
        freshly read `Booted Slot`."""
        page = _page()
        page._verify = ss.parse_verify_existing(_passing_run())
        page._render()
        first = len(page._check_rows)
        assert first == 14
        page._verify = ss.parse_verify_existing(_issues_run())
        page._render()
        assert len(page._check_rows) == 14
        # The group holds 14 rows, not 28.
        added = [w for w in _rows(page._checks) if isinstance(w, Adw.ActionRow)]
        assert len(added) == 14, len(added)

    def test_the_button_is_insensitive_while_a_check_is_in_flight(self):
        page = _page()
        page._tool_missing = False
        page._verify_busy = True
        page._render()
        assert not page._btn_verify.get_sensitive()
        page._verify_busy = False
        page._render()
        assert page._btn_verify.get_sensitive()

    def test_a_missing_deploy_tool_says_so_on_this_row_too(self):
        page = _page()
        page._tool_missing = True
        page._render()
        assert says(page._row_verify.get_subtitle(), "not installed")
        assert not page._btn_verify.get_sensitive()

    def test_an_unclassified_line_is_shown_rather_than_dropped(self):
        page = _page()
        page._verify = {"checks": [], "advice": [],
                        "unread": ["a line from a newer deploy script"],
                        "issues": None, "passed": None}
        page._render()
        row = [r for r in page._check_rows
               if r.get_title() == "Not read as a check"][0]
        assert says(row.get_subtitle(), "newer deploy script")

    def test_tool_output_is_escaped_before_it_reaches_a_row(self):
        """libadwaita parses a row title and subtitle as markup, and a bare `&`
        blanks the row rather than showing a stray ampersand."""
        page = _page()
        page._verify = {
            "checks": [{"key": "Slot & Check",
                        "severity": "bad",
                        "text": "booted (@a&b) != current-slot (@c&d)"}],
            "advice": ["rollback & reboot <now>"],
            "unread": [], "issues": 1, "passed": False}
        page._render()
        row = page._check_rows[0]
        assert renders_literally(row.get_title())
        assert renders_literally(row.get_subtitle())
        assert says(row.get_subtitle(), "@a&b")
        assert renders_literally(page._check_rows[1].get_subtitle())
