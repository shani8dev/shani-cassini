"""The Fleet page's two health checks: `healthcheck` and `drift-check`.

The agent has supported both since it existed and nothing in Cassini drove
either. They are the operator's answer to "is this device actually reporting
in, and is its local state what it should be" - which is a different question
from the one the rest of the page asks, since `status` reports *membership* and
neither check reports whether the membership works.

**Both have a `--json` mode, so both are read and neither is parsed.** That is
the whole reason this is a small file: there is no prose to recover a verdict
from. It is also why the page must not decide anything - the agent sends its own
`status` and `drift_detected`, computed by the same precedence as its exit code,
and re-deriving either in Python would be a second implementation of a rule that
lives in shani-fleet. Two of the five drift categories carry a count after a
colon (`failed_units:3`, `stale_heartbeat:9000s`) and the fixtures below are the
agent's own strings, unsplit.

**The fixtures are the agent's `jq` invocations, read out of the script.** Each
document below is the exact shape `cmd_healthcheck` and `cmd_drift_check` emit,
including the four `status` values and their precedence, which is:

    fail_reason != ""   -> degraded
    not enrolled        -> not_enrolled
    no key in keyring   -> degraded
    console unreachable -> unreachable
    otherwise           -> healthy

The tests below do not re-state that precedence; they assert the page shows
whatever string arrived, because restating it here would be the drift the file
exists to prevent.

**The privilege is load-bearing, not incidental.** `shani-fleet-agent.service`
has no `User=`, so the agent is root and its `gpg --list-keys` reads root's
keyring. Called unprivileged the same check would read the desktop user's
keyring and report a missing signing key on a healthy enrolled machine - a wrong
answer rather than a missing one. `test_the_keyring_is_looked_for_where_the_agent_looks`
holds the argv that says so.
"""

from __future__ import annotations

import ast
import inspect
import textwrap

import pytest

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw  # type: ignore  # noqa: E402
from conftest import says  # noqa: E402

from shani_cassini import system_status as ss  # noqa: E402
from shani_cassini.tabs import fleet as fleet_mod  # noqa: E402


@pytest.fixture(autouse=True)
def _adw():
    Adw.init()


# --- the agent's own documents ------------------------------------------------

HEALTHY = {
    "enrolled": True, "gpg_in_keyring": True, "server_reachable": True,
    "gpg_key_id": "0xDEADBEEF01234567", "fail_reason": "",
    "version": "1.4.0", "status": "healthy",
}
NOT_ENROLLED = {**HEALTHY, "enrolled": False, "server_reachable": False,
                "status": "not_enrolled"}
KEY_MISSING = {**HEALTHY, "gpg_in_keyring": False, "status": "degraded",
               "fail_reason": "gpg key not in keyring"}
UNREACHABLE = {**HEALTHY, "server_reachable": False, "status": "unreachable"}
NO_KEY_CONFIGURED = {**HEALTHY, "gpg_key_id": "", "gpg_in_keyring": False,
                     "status": "degraded"}

DRIFT_CLEAN = {"drift_detected": False, "drift": [], "version": "1.4.0"}
DRIFT_ALL = {
    "drift_detected": True,
    "drift": ["slot_unknown", "gpg_key_missing", "reboot_pending",
              "failed_units:3", "stale_heartbeat:9000s"],
    "version": "1.4.0",
}


# --- the readers --------------------------------------------------------------

class TestTheReaders:
    def test_both_run_the_json_mode_through_pkexec(self, monkeypatch):
        """The argv polkit is asked about, asserted whole and for both."""
        seen = []
        monkeypatch.setattr(ss, "run_json",
                            lambda argv, done: (seen.append(list(argv)),
                                                done(None, "stopped")))
        ss.fleet_health(lambda r, e: None)
        ss.fleet_drift(lambda r, e: None)
        assert seen == [
            ["pkexec", "shani-fleet-agent", "healthcheck", "--json"],
            ["pkexec", "shani-fleet-agent", "drift-check", "--json"],
        ]

    def test_a_healthy_answer_carries_the_agent_own_status(self, monkeypatch):
        got = []
        monkeypatch.setattr(ss, "run_json",
                            lambda argv, done: done(HEALTHY, ""))
        ss.fleet_health(lambda r, e: got.append((r, e)))
        result, error = got[0]
        assert error == ""
        assert result["ok"] is True
        assert result["status"] == "healthy"
        assert [c["key"] for c in result["checks"]] == [
            "Enrollment", "Signing key", "Console"]

    def test_a_missing_keyring_names_the_key_and_the_consequence(self, monkeypatch):
        """The one fact a user can act on, in the agent's own terms.

        `gpg_key_missing` means the agent would refuse every signed command, so
        the row says that rather than only colouring an icon.
        """
        got = []
        monkeypatch.setattr(ss, "run_json",
                            lambda argv, done: done(KEY_MISSING, ""))
        ss.fleet_health(lambda r, e: got.append(r))
        signing = [c for c in got[0]["checks"] if c["key"] == "Signing key"][0]
        assert signing["yes"] is False
        assert says(signing["text"], "0xDEADBEEF01234567")
        assert says(signing["text"], "refused")

    def test_no_configured_key_is_not_named_as_a_missing_one(self, monkeypatch):
        """`gpg_key_id: ""` is *not configured*, which is a different fault from
        *configured and absent* - and the agent's two exit codes say so (3 vs 1).
        """
        got = []
        monkeypatch.setattr(ss, "run_json",
                            lambda argv, done: done(NO_KEY_CONFIGURED, ""))
        ss.fleet_health(lambda r, e: got.append(r))
        signing = [c for c in got[0]["checks"] if c["key"] == "Signing key"][0]
        assert says(signing["text"], "none configured")

    def test_a_document_without_a_status_is_a_reason_not_an_empty_report(
            self, monkeypatch):
        got = []
        monkeypatch.setattr(ss, "run_json",
                            lambda argv, done: done({"enrolled": True}, ""))
        ss.fleet_health(lambda r, e: got.append((r, e)))
        assert got[0][0]["ok"] is False
        assert "no status field" in got[0][0]["problem"]

    def test_drift_categories_are_passed_through_unsplit(self, monkeypatch):
        """`failed_units:3` keeps its colon and its count.

        Splitting it here would be a second parser for a format the agent owns,
        and the page would then be the thing that decides what a category means.
        """
        got = []
        monkeypatch.setattr(ss, "run_json", lambda argv, done: done(DRIFT_ALL, ""))
        ss.fleet_drift(lambda r, e: got.append(r))
        assert got[0]["drift"] == DRIFT_ALL["drift"]
        assert got[0]["detected"] is True

    def test_an_empty_drift_list_is_clean_not_absent(self, monkeypatch):
        got = []
        monkeypatch.setattr(ss, "run_json",
                            lambda argv, done: done(DRIFT_CLEAN, ""))
        ss.fleet_drift(lambda r, e: got.append(r))
        assert got[0]["drift"] == []
        assert got[0]["detected"] is False

    def test_a_document_with_no_drift_list_is_refused(self, monkeypatch):
        got = []
        monkeypatch.setattr(ss, "run_json",
                            lambda argv, done: done({"drift_detected": True}, ""))
        ss.fleet_drift(lambda r, e: got.append((r, e)))
        assert got[0][0]["ok"] is False
        assert "no drift list" in got[0][0]["problem"]


# --- the page ----------------------------------------------------------------

def _page() -> "fleet_mod.FleetTab":
    return fleet_mod.FleetTab()


def _row_titles(tab, key) -> list[str]:
    return [r.get_title() for r in getattr(tab, key)]


class TestThePage:
    def test_both_checks_are_offered_and_neither_has_run(self):
        tab = _page()
        assert tab._btn_health.get_label() == "Check"
        assert tab._btn_drift.get_label() == "Check"
        assert says(tab._row_health.get_subtitle(), "Not checked yet")
        assert says(tab._row_drift.get_subtitle(), "Not checked yet")
        assert not tab._findings.get_visible()

    def test_no_check_runs_because_the_page_was_built(self, monkeypatch):
        """Both need a password, so neither may run on construction."""
        calls = []
        monkeypatch.setattr(ss, "fleet_health",
                            lambda done: calls.append("health"))
        monkeypatch.setattr(ss, "fleet_drift",
                            lambda done: calls.append("drift"))
        _page()
        assert calls == []

    def test_a_healthy_machine_says_healthy_and_lists_the_three_checks(
            self, monkeypatch):
        tab = _page()
        # Driven through the real reader, so the shaping is exercised and not
        # bypassed - a test that hand-builds the value would pass against a
        # reader that stopped producing it.
        monkeypatch.setattr(ss, "run_json", lambda argv, done: done(HEALTHY, ""))
        tab.check_health()
        assert says(tab._row_health.get_subtitle(), "Healthy")
        assert _row_titles(tab, "_finding_rows") == [
            "Enrollment", "Signing key", "Console"]

    def test_the_status_shown_is_the_agent_own_not_a_recomputed_one(
            self, monkeypatch):
        """A document the page would score differently must show what it said.

        `enrolled` is false here while `status` says `degraded` - the agent's
        precedence puts `fail_reason` first, so a page combining the three
        booleans itself would draw a different verdict. This asserts the page
        shows the agent's.
        """
        tab = _page()
        monkeypatch.setattr(
            ss, "run_json", lambda argv, done: done(
                {"enrolled": False, "gpg_in_keyring": True,
                 "server_reachable": True, "gpg_key_id": "0xKEY",
                 "fail_reason": "something else entirely",
                 "version": "1.4.0", "status": "degraded"}, ""))
        tab.check_health()
        assert says(tab._row_health.get_subtitle(), "Degraded")
        assert not says(tab._row_health.get_subtitle(), "Not enrolled")


    def test_a_status_this_page_does_not_know_is_not_called_healthy(
            self, monkeypatch):
        """A fifth status must read as unrecognised, never fall through to the
        healthy wording - which is the failure mode of a `.get(..., healthy)`.
        """
        tab = _page()
        monkeypatch.setattr(ss, "run_json",
                            lambda argv, done: done({**HEALTHY,
                                                     "status": "quiescent"}, ""))
        tab.check_health()
        assert says(tab._row_health.get_subtitle(), "does not recognise")
        assert not says(tab._row_health.get_subtitle(), "Healthy")

    def test_clean_drift_says_no_drift_and_lists_nothing(self, monkeypatch):
        tab = _page()
        monkeypatch.setattr(ss, "run_json",
                            lambda argv, done: done(DRIFT_CLEAN, ""))
        tab.check_drift()
        assert says(tab._row_drift.get_subtitle(), "No drift detected")
        assert tab._finding_rows == []

    def test_drift_found_lists_each_category_verbatim(self, monkeypatch):
        tab = _page()
        monkeypatch.setattr(ss, "run_json",
                            lambda argv, done: done(DRIFT_ALL, ""))
        tab.check_drift()
        assert "5 item(s)" in tab._row_drift.get_subtitle()
        listed = [r.get_subtitle() for r in tab._finding_rows]
        assert listed == DRIFT_ALL["drift"], listed
        assert "failed_units:3" in listed

    def test_a_drift_document_that_omits_the_verdict_is_not_called_clean(
            self, monkeypatch):
        """`drift_detected` absent is not "no drift", and an empty list with the
        verdict missing is exactly the shape that reads as clean by accident.
        """
        tab = _page()
        monkeypatch.setattr(ss, "run_json",
                            lambda argv, done: done({"drift": []}, ""))
        tab.check_drift()
        assert says(tab._row_drift.get_subtitle(), "did not say whether")
        assert not says(tab._row_drift.get_subtitle(), "No drift")

    def test_a_refused_password_is_not_reported_as_a_broken_agent(
            self, monkeypatch):
        tab = _page()
        monkeypatch.setattr(ss, "fleet_health", lambda done: done(
            {"ok": False, "problem": "", "checks": [], "status": ""}, ""))
        tab.check_health()
        assert says(tab._row_health.get_subtitle(), "did not answer")
        assert not says(tab._row_health.get_subtitle(), "Healthy")

    def test_one_checks_rows_are_taken_down_before_the_other(self, monkeypatch):
        """A drift answer from three minutes ago must not sit beside a health
        answer read just now - they are two different questions."""
        tab = _page()
        monkeypatch.setattr(ss, "run_json",
                            lambda argv, done: done(DRIFT_ALL, ""))
        tab.check_drift()
        assert len(tab._finding_rows) == 5
        monkeypatch.setattr(ss, "run_json", lambda argv, done: done(HEALTHY, ""))
        tab.check_health()
        assert _row_titles(tab, "_finding_rows") == [
            "Enrollment", "Signing key", "Console"]

    def test_the_buttons_are_insensitive_while_a_check_is_in_flight(self):
        tab = _page()
        tab._busy = True
        tab._render_diagnostics()
        assert not tab._btn_health.get_sensitive()
        assert not tab._btn_drift.get_sensitive()

    def test_tool_output_is_escaped_before_it_reaches_a_row(self, monkeypatch):
        """`fail_reason` and the drift categories come off another project's
        strings, and libadwaita parses a subtitle as markup."""
        tab = _page()
        monkeypatch.setattr(ss, "run_json", lambda argv, done: done(
            {"drift_detected": True, "version": "1",
             "drift": ["<b>slot_unknown</b> & co"]}, ""))
        tab.check_drift()
        row = tab._finding_rows[0]
        assert "&amp;" in row.get_subtitle() or "&" not in row.get_subtitle()
        assert "<b>" not in row.get_subtitle()

    def test_the_keyring_is_looked_for_where_the_agent_looks(self):
        """The privilege is load-bearing: the agent runs as root, so its
        `gpg --list-keys` reads root's keyring. Unprivileged, this page would
        read the desktop user's and report a healthy machine as degraded.
        """
        tree = ast.parse(textwrap.dedent(inspect.getsource(ss.fleet_health)))
        argv = next(n for n in ast.walk(tree)
                    if isinstance(n, ast.Call)
                    and isinstance(n.func, ast.Name)
                    and n.func.id == "run_json")
        assert argv.args[0].elts[0].value == "pkexec"
        # And the page must not define the argv itself. Collected with a
        # try, because a list literal holding a non-constant (a module
        # constant such as `ss.FLEET_AGENT`) is a perfectly ordinary argv and
        # `literal_eval` refuses it - the first version of this raised inside
        # the comprehension and failed for a reason that had nothing to do with
        # what it was checking.
        page = ast.parse(textwrap.dedent(inspect.getsource(fleet_mod)))
        built = set()
        for node in ast.walk(page):
            if not isinstance(node, (ast.List, ast.Tuple, ast.Set)):
                continue
            try:
                values = ast.literal_eval(node)
            except (ValueError, SyntaxError, TypeError):
                continue
            if isinstance(values, (list, tuple, set)):
                built |= {v for v in values if isinstance(v, str)}
        assert not built & {"healthcheck", "drift-check", "--json"}, (
            "the tab must delegate the argv to system_status, which is where "
            f"the other fleet readers' argv lives; it built {sorted(built)}")


# **The agent's four, written out rather than read back from the table.**
#
# A parametrised test whose cases come from the table it checks is a test that
# loses a case the moment the table loses one: dropping `"unreachable"` left the
# suite green, with one test fewer and nothing failed. The expected set has to be
# an independent statement of what the agent can send, which means a literal here
# and a check that the two agree.
AGENT_STATUSES = ("degraded", "healthy", "not_enrolled", "unreachable")


def test_the_table_covers_every_status_the_agent_can_send() -> None:
    """Read out of `cmd_healthcheck` in shani-fleet-agent, not from the page."""
    assert sorted(fleet_mod.HEALTH_STATUS) == sorted(AGENT_STATUSES)


@pytest.mark.parametrize("status", AGENT_STATUSES)
def test_every_status_the_agent_can_send_has_its_own_wording(monkeypatch, status):
    """**One test per status, because the control that dropped one did not
    fail.**

    Removing `"unreachable"` from the table left the suite green: the page falls
    back to "a status this page does not recognise", which is honest, so a
    *missing* wording and an *unknown* wording are indistinguishable from
    outside. This asserts the exact sentence, not that it merely mentions the
    status.
    """
    tab = _page()
    monkeypatch.setattr(ss, "run_json",
                        lambda argv, done: done({**HEALTHY, "status": status}, ""))
    tab.check_health()
    said = tab._row_health.get_subtitle()
    assert said == fleet_mod.HEALTH_STATUS[status], (
        f"status {status!r} rendered as {said!r}")
