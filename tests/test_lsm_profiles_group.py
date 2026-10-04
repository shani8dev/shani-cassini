"""The AppArmor profile list, on the LSM page since the two pages were folded.

These exist because the fold was not a copy. Moving the list in meant trusting
two parsers that had never been run against each other in one read, and meant
deleting a page whose tests were the only thing holding a parser honest - so
the coverage the AppArmor page carried comes here, plus the case that parser had
wrong and no fixture had reached.
"""

from __future__ import annotations

import pytest

from shani_cassini import system_status as ss
from shani_cassini.tabs import lsm as lsm_mod
from tests.test_new_gap_pages import spin, walk

gi = pytest.importorskip("gi")
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

Adw.init()


def _spin(predicate, tries: int = 400) -> bool:
    from gi.repository import GLib
    import time
    ctx = GLib.MainContext.default()
    for _ in range(tries):
        if predicate():
            return True
        ctx.iteration(False)
        time.sleep(0.005)
    return False


def _row_named(tab, needle: str):
    """Exact-title lookup through the repo's own widget walker, not a hand-rolled
    one. An earlier version of this file walked `_children` by hand and matched
    on a substring; it found nothing for five of the eight tests and the failure
    looked like a page defect rather than a broken helper."""
    for r in walk(tab):
        if r.get_title() == needle:
            return r
    return None


# The counts half and the profiles half come out of ONE read. Verbatim aa-status
# shape, with the process table in the wording that used to defeat the parser.
COUNTS = ("apparmor module is loaded.\n"
          "42 profiles are loaded.\n"
          "40 profiles are in enforce mode.\n"
          " 2 profiles are in complain mode.\n"
          " 0 unconfined processes.\n")


def _report(section_word: str) -> dict:
    return {
        "counts": {"ok": True, "problem": "", "module_loaded": True,
                   "loaded": 42, "enforce": 40, "complain": 2, "unconfined": 0},
        "profiles": ss._parse_aa_profiles(
            COUNTS + "\nProfiles:\n  Enforcement mode\n    /usr/bin/foo// null\n"
            "  complain mode\n    /usr/bin/bar// null\n\n"
            f"Processes are in {section_word} mode:\n"
            "   /usr/bin/firefox (1234) firefox\n"
            "   /usr/bin/sshd (99) sshd\n", ""),
    }


class TestTheFoldedInProfileList:
    def test_the_page_has_the_group_and_the_sixth_row_appears_in_the_tree(
            self, monkeypatch) -> None:
        monkeypatch.setattr(ss, "apparmor_report",
                            lambda done: done(_report("complain"), ""))
        tab = lsm_mod.LsmTab()
        tab._btn_profiles.emit("clicked")
        assert _spin(lambda: _row_named(tab, "/usr/bin/foo") is not None)
        assert _row_named(tab, "Profile list") is not None

    def test_enforcing_and_complaining_rows_say_which_is_which(
            self, monkeypatch) -> None:
        """A complain-mode profile blocks nothing, and saying only its name
        would read as protection it is not."""
        monkeypatch.setattr(ss, "apparmor_report",
                            lambda done: done(_report("complain"), ""))
        tab = lsm_mod.LsmTab()
        tab._btn_profiles.emit("clicked")
        assert _spin(lambda: _row_named(tab, "/usr/bin/bar") is not None)
        assert "Enforcing" in _row_named(tab, "/usr/bin/foo").get_subtitle()
        assert "blocks nothing" in _row_named(tab, "/usr/bin/bar").get_subtitle()

    @pytest.mark.parametrize("word", ["enforce", "complain"])
    def test_a_running_process_is_never_drawn_as_a_profile(self, word) -> None:
        """**This is the defect the fold exposed.**

        `_parse_aa_profiles` ended its block at a line starting "Processes are
        in" - but that check sat *below* the two mode checks, and "Processes are
        in complain mode:" *contains* the substring "complain mode". So the
        mode check re-opened the section and every confined process was collected
        as a complaining profile, naming the user's browser and sshd as security
        profiles that do not exist.

        The enforce wording does not collide, which is why the guard looked
        sound: it had only ever been exercised against the one of the two
        wordings that is safe. Both are pinned here.
        """
        out = _report(word)["profiles"]
        names = out["enforce"] + out["complain"]
        assert "/usr/bin/firefox (1234) firefox" not in names
        assert "/usr/bin/sshd (99) sshd" not in names
        assert out["enforce"] == ["/usr/bin/foo"]
        assert out["complain"] == ["/usr/bin/bar"]

    def test_one_read_serves_both_halves(self) -> None:
        """The promise `apparmor_profiles`' own docstring made and its code did
        not keep: two `pkexec aa-status` spawns is two password prompts for one
        answer. `apparmor_report` must spawn once."""
        import inspect
        body = inspect.getsource(ss.apparmor_report)
        assert body.count('tool_path_or_self("aa-status")') == 1, (
            "apparmor_report spawns aa-status more than once")
        # and the retired readers are genuinely gone, not merely unused
        for retired in ("apparmor_status", "apparmor_profiles"):
            assert not hasattr(ss, retired), f"{retired} is dead code again"


class TestTheStatesAreKeptApart:
    def test_a_refusal_is_never_drawn_as_zero_profiles(self, monkeypatch) -> None:
        """The failure apparmor.py's docstring records having shipped once: a
        dismissed prompt and a machine with no profiles must not look alike."""
        monkeypatch.setattr(ss, "apparmor_report", lambda done: done(
            {"counts": {"ok": False, "problem": "aa-status needs an administrator password"},
             "profiles": {"ok": False, "problem": "aa-status needs an administrator password"}},
            ""))
        tab = lsm_mod.LsmTab()
        tab._btn_profiles.emit("clicked")
        assert _spin(lambda: "no profile is claimed"
                     in (_row_named(tab, "Profile list").get_subtitle() or ""))
        subtitle = _row_named(tab, "Profile list").get_subtitle()
        assert "No profiles are loaded" not in subtitle

    def test_a_genuinely_empty_answer_says_so(self, monkeypatch) -> None:
        """The opposite case, and the one that must NOT read as a refusal."""
        monkeypatch.setattr(ss, "apparmor_report", lambda done: done(
            {"counts": {"ok": True, "loaded": 0, "enforce": 0, "complain": 0},
             "profiles": {"ok": True, "problem": "aa-status printed no profile names - "
                          "either none are loaded, or this build cannot read them",
                          "enforce": [], "complain": []}}, ""))
        tab = lsm_mod.LsmTab()
        tab._btn_profiles.emit("clicked")
        assert _spin(lambda: _row_named(tab, "AppArmor profiles") is not None
                     and "No profiles are loaded"
                     in (_row_named(tab, "AppArmor profiles").get_subtitle() or ""))

    def test_not_asked_yet_is_not_the_same_as_asked_and_empty(self, monkeypatch) -> None:
        monkeypatch.setattr(ss, "apparmor_report", lambda done: None)
        tab = lsm_mod.LsmTab()
        subtitle = _row_named(tab, "Profile list").get_subtitle()
        assert "not read yet" in subtitle
        assert "No profiles are loaded" not in subtitle
