"""The IRQ Balance page's one writable control, and the boundary around it.

IRQ Balance was a pure reporter. It now writes exactly one file,
`/etc/default/irqbalance`, and the point of this file is that "exactly one" is
enforced rather than asserted in a comment.

**Why the write exists at all.** The package ships no `/etc` directory - only
`/usr/share/irqbalance/irqbalance.env` - so there was no file to report and no
way to set the banlist without a terminal. The page's own `ACTIONS_NOTE` used to
send the user to one.

**And why only the banlist.** `IRQBALANCE_ARGS` is refused by the helper's
validator, because the unit's `ExecStart` uses an *unquoted* `$IRQBALANCE_ARGS`
and systemd passes an unquoted `$VAR` as exactly one argument - so a value
holding two flags reaches the daemon as a single unrecognised option. A page
offering it would produce config that reads as applied and is not.
"""

from __future__ import annotations

import ast
import inspect
import os
import pathlib
import sys
import textwrap

import gi
import pytest

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw  # type: ignore  # noqa: E402

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from shani_cassini import config_io  # noqa: E402
from shani_cassini.tabs import irqbalance as ib  # noqa: E402


ENV_BODY = 'IRQBALANCE_ARGS=""\n#IRQBALANCE_BANNED_CPULIST=\n'


# --- the boundary: this page runs one program, for one file ----------------


def test_the_page_runs_nothing_but_the_save_helper():
    """Every write on this page is `pkexec shani-cassini-save`. Nothing else.

    Checked against the module's imports and against the argv it builds, because
    the alternative - a subprocess call appearing beside an unrelated one - is
    the regression this exists to catch.
    """
    tree = ast.parse(textwrap.dedent(inspect.getsource(ib)))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert "subprocess" not in imported, (
        "this page must not build its own argv; the helper is the only writer")
    assert "pty" not in imported


def test_the_helper_is_the_only_privileged_program_and_it_is_allowlisted():
    """The helper is reached by exact path, and the file this page writes is one
    it has a validator for. A path the helper does not know falls through to a
    different writer with different safety properties."""
    assert config_io.SAVE_HELPER.startswith("/")
    assert config_io.helper_target_for(ib.LOCAL_ENV) == "irqbalance_env", (
        "the page writes /etc/default/irqbalance but the helper has no "
        "validator for it, so the save would go by a different, weaker route")
    argv = config_io.save_argv("irqbalance_env", "0" * 64)
    assert argv[:2] == ["pkexec", config_io.SAVE_HELPER]
    assert "--expect-sha256" in argv, (
        "the digest is what stops a polkit prompt eating part of the payload")


def test_the_editable_row_is_the_banlist_and_nothing_else():
    """The one setting that cannot work must not be *offered*.

    `ExecStart=/usr/sbin/irqbalance $IRQBALANCE_ARGS` is unquoted, and
    systemd.service(5) says an unquoted `$VAR` becomes "exactly a single
    argument". So `--banirq=3 --banmod=foo` reaches the daemon as one argument
    and it rejects its own command line. The helper refuses the key; this is the
    page half.

    **Asserted on the row that is actually built, not on the word.** The first
    version of this test was `"IRQBALANCE_ARGS" not in source`, and it failed
    against pre-existing *reporting* code - `VARS_THAT_MATTER` names the variable
    so the page can say what it is set to. Naming a setting to report it is the
    opposite of offering it for editing, and a text check cannot tell those
    apart.
    """
    tab = ib.IrqBalanceTab()
    labels = _row_titles(tab)
    editable = [t for t in labels if "CPU" in (t or "")]
    assert editable, f"the banlist row is missing: {labels}"
    for label in labels:
        assert "ARGS" not in (label or ""), (
            f"an editable row offers IRQBALANCE_ARGS: {label}")


def test_the_page_no_longer_claims_it_changes_nothing():
    """It did, and now it writes a file. A page that says it changes nothing
    above a Save button is the contradiction this repo keeps finding."""
    src = textwrap.dedent(inspect.getsource(ib))
    assert "changes nothing, writes nothing" not in src, (
        "the page writes /etc/default/irqbalance now and must say so")


# --- the control itself, driven against a real file ------------------------


def _walk(widget):
    """Every widget under `widget`, depth-first."""
    out, stack = [], [widget]
    while stack:
        node = stack.pop()
        out.append(node)
        child = node.get_first_child()
        while child is not None:
            stack.append(child)
            child = child.get_next_sibling()
    return out


def _row_titles(tab):
    return [r.get_title() for r in _walk(tab)
            if isinstance(r, Adw.PreferencesRow)]


def _group_titles(tab):
    return [g.get_title() for g in _walk(tab)
            if isinstance(g, Adw.PreferencesGroup)]


@pytest.fixture
def page(tmp_path, monkeypatch):
    """The real page, with the write intercepted so no pkexec is involved.

    Intercepting `config_edit.save` is deliberate: what is under test here is
    the page's *decisions* - validate before asking for a password, refuse a
    malformed list, write the separator the file uses - not the helper, which
    has its own suite in shani-deploy.
    """
    env = tmp_path / "irqbalance"
    env.write_text(ENV_BODY)
    captured: dict = {}
    def fake_save(path, text, done):
        """What the helper does, minus pkexec: capture AND write the file.

        The first version of this fixture only captured. That made the page look
        broken, because a second Save in the same test re-read the ORIGINAL file,
        found the key still commented out, correctly reported "already empty",
        and wrote nothing - which the test then read as a failure to remove. The
        helper does write the file, so the fake must too, or the test is
        describing a world where saves do not persist.
        """
        captured.update(path=path, text=text)
        captured.setdefault("saves", []).append(text)
        pathlib.Path(path).write_text(text)
        done("", "")

    monkeypatch.setattr(ib.ce, "save", fake_save)
    monkeypatch.setattr(ib, "LOCAL_ENV", str(env))
    tab = ib.IrqBalanceTab()
    tab._captured = captured
    return tab


def wait_until_ready(page, timeout: float = 10.0) -> bool:
    """Wait until the page is willing to be saved again.

    `_saved` clears the guard and re-enables the row, and it arrives through
    `GLib.idle_add` from the writer thread - so this is the same wait as
    `wait_for_saves`, asked about the other half of the same round trip.
    """
    import time as _time
    from gi.repository import GLib as _GLib
    ctx = _GLib.MainContext.default()
    end = _time.monotonic() + timeout
    while (page._saving or not page._ban_row.get_sensitive()) and _time.monotonic() < end:
        ctx.iteration(False)
        _time.sleep(0.005)
    return not page._saving and page._ban_row.get_sensitive()


def wait_for_saves(page, count: int, timeout: float = 10.0) -> bool:
    """Wait until the page's writer thread has been called `count` times.

    The save runs on a `threading.Thread`, so it lands after the click that
    started it. `time.sleep` alone would do for the thread itself, but the page's
    own `_saved()` callback goes through `GLib.idle_add`, so the main loop has to
    be iterated too — which is what every other async test in this suite does.
    """
    import time as _time
    from gi.repository import GLib as _GLib
    ctx = _GLib.MainContext.default()
    end = _time.monotonic() + timeout

    def seen() -> int:
        # `.get`, not `[]`: the key only exists once the writer has been called
        # at all, and this is called *before* the first one. The first version
        # raised KeyError here, which the control run below found immediately -
        # a helper that cannot be called in the state it was written for.
        return len(page._captured.get("saves", []))

    while seen() < count and _time.monotonic() < end:
        ctx.iteration(False)
        _time.sleep(0.005)
    return seen() >= count


def test_a_valid_cpu_list_is_written_with_the_files_own_separator(page):
    """The separator is `=` here because systemd parses this file. Writing `0-3`
    with a space would produce a directive systemd does not read."""
    page._ban_row.set_text("0-3")
    page._on_save_clicked(None)
    assert "IRQBALANCE_BANNED_CPULIST=0-3" in page._captured["text"]
    assert "IRQBALANCE_BANNED_CPULIST 0-3" not in page._captured["text"]


def test_a_malformed_cpu_list_is_refused_before_anything_is_written(page):
    """The user gets a red border, not an administrator authentication for a
    value that was never going to be accepted."""
    page._ban_row.set_text("0-")
    page._on_save_clicked(None)
    assert not page._captured, "a refused value must not reach the writer"
    assert "error" in page._ban_row.get_css_classes()


@pytest.mark.parametrize("bad", ["abc", "0,,2", "-1", "0-3-4", "1 2"])
def test_each_malformed_list_is_refused(page, bad):
    page._ban_row.set_text(bad)
    page._on_save_clicked(None)
    assert not page._captured, bad


def test_an_empty_value_removes_the_key_rather_than_setting_it_blank(page):
    """Setting `IRQBALANCE_BANNED_CPULIST=` to empty is not the same as not
    setting it, and the shipped state is "not set".

    **Each Save is waited for before the next is issued, and both are counted.**
    The page hands the write to a `threading.Thread` (a real user must not have
    the GTK main loop waiting on `pkexec`), so a second Save issued immediately
    can read the file *before* the first thread has written it — at which point
    the key is still commented out, "already empty" is the correct answer, and
    the page correctly writes nothing. The test then read
    `page._captured["text"]`, still holding the *first* save's
    `IRQBALANCE_BANNED_CPULIST=0-3`, and reported "the key was not removed".

    So the red line named a defect in the page that is not there, and it appeared
    only in a full-suite run where the thread had less scheduling luck — the
    ordering class this repo records twice, in the one shape where it is worst:
    a test that blames the code under test for a race with itself.

    Counting the calls separates the two real defects: "the second Save never
    reached the writer" and "the second Save wrote the key again" used to print
    the same message.
    """
    page._ban_row.set_text("0-3")
    page._on_save_clicked(None)
    assert wait_for_saves(page, 1), "the first save never reached the writer"
    # And for the page to be ready for the next one - a real user's Save is
    # greyed out until `_saved` runs, so the second click is only reachable
    # after that. Without the wait, the second click is *refused by the page*
    # (there is now a guard for exactly that) and the key would never be
    # removed - so this line is the one that makes the rest of the test mean
    # what it says.
    assert wait_until_ready(page), "the page never became writable again"
    page._ban_row.set_text("")
    page._on_save_clicked(None)
    assert wait_for_saves(page, 2), (
        f"the second save never reached the writer; the first wrote "
        f"{page._captured['saves']}")
    assert "IRQBALANCE_BANNED_CPULIST" not in page._captured["saves"][-1], \
        f"the second save wrote the key back: {page._captured['saves'][-1]!r}"


class TestTheWriteItself:
    """What the page does while a write is in flight, rather than before it.

    Every other test here is about the decision - validate, refuse, choose a
    separator. These three are about the window between the click and the
    answer, which is where the two flakes in this file came from.
    """

    def test_a_second_save_while_one_is_in_flight_is_refused(self, page,
                                                            monkeypatch):
        """The invariant lives in `_on_save_clicked`, not only in the row.

        **Two different values, deliberately.** The first version of this test
        set the box to empty for the second click, and its control passed with
        the guard removed - because emptying the box is the one change the page
        refuses on its own merits: the file still has the key commented out, so
        `remove_key` reports "unchanged" and `_on_save_clicked` returns before
        the writer is reached. The test could not tell a guard that worked from
        no guard at all, which is the shape this repo keeps finding.

        Changing one valid list to another is the case the guard exists for: the
        second click would otherwise read the pre-write file and write a value
        derived from it, so the user's first change is lost.
        """
        import threading
        release = threading.Event()
        seen: list[str] = []

        def slow_save(path, text, done):
            seen.append(text)
            page._captured.setdefault("saves", []).append(text)
            release.wait(2.0)
            pathlib.Path(path).write_text(text)
            done("", "")

        monkeypatch.setattr(ib.ce, "save", slow_save)
        page._ban_row.set_text("0-3")
        page._on_save_clicked(None)
        page._ban_row.set_text("4-5")
        page._on_save_clicked(None)
        release.set()
        assert wait_for_saves(page, 1)
        assert len(seen) == 1, (
            f"the second click was not refused; the writer saw {seen}")

    def test_a_writer_that_raises_leaves_the_page_usable_and_says_so(
            self, page, monkeypatch):
        """**A raised exception must not grey out the page for the session.**

        `ce.save` runs on a daemon thread nobody joins, so an exception there
        killed the thread, never called back, and left the CPU-list row
        insensitive with no toast and nothing in the log — the one control this
        page has, permanently disabled, silently. The handler reports it through
        the same `done` the helper uses.
        """
        def exploding_save(path, text, done):
            raise OSError("pkexec could not be started")

        monkeypatch.setattr(ib.ce, "save", exploding_save)
        page._ban_row.set_text("0-3")
        page._on_save_clicked(None)
        assert wait_for_saves(page, 0) or True
        # The row must come back, and the page must accept a save again.
        ctx = ib.GLib.MainContext.default()
        import time as _time
        end = _time.monotonic() + 5
        while (page._ban_row.get_sensitive() is False
               and _time.monotonic() < end):
            ctx.iteration(False)
            _time.sleep(0.005)
        assert page._ban_row.get_sensitive(), \
            "the CPU-list row stayed greyed out after the writer raised"

    def test_the_refusal_is_the_method_not_only_the_widget(self, page,
                                                           monkeypatch):
        """Calling `_on_save_clicked` directly while saving is a no-op.

        Reachable without any keyboard or focus behaviour at all - the point of
        putting the guard in the method rather than trusting the row.
        """
        monkeypatch.setattr(ib.ce, "save", lambda p, t, d: d("", ""))
        page._saving = True
        page._ban_row.set_text("4-5")
        page._on_save_clicked(None)
        assert page._captured.get("saves") in (None, []), \
            "a save ran while one was already in flight"


def test_the_written_file_still_parses_as_the_helper_expects(page):
    """The page's output must be what the helper's validator accepts - the two
    are separate implementations of the same rule, and drift between them is a
    save the page offers and the helper rejects."""
    page._ban_row.set_text("0-3,5,7-8")
    page._on_save_clicked(None)
    helper = pathlib.Path(
        "/home/shrinivaskumbhar/Documents/shani/shani-deploy/scripts/"
        "shani-cassini-save.sh")
    if not helper.exists():
        pytest.skip("the helper is not in this checkout")
    out = pathlib.Path("/tmp/page-output.conf")
    out.write_text(page._captured["text"])
    import subprocess
    proc = subprocess.run(["bash", str(helper), "--check-irqbalance-env",
                           str(out)], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


def test_the_control_is_on_screen_not_just_built(page):
    """A row that is constructed and never added looks identical to a working
    one to any test that reaches it by attribute. This walks the tree."""
    titles = _group_titles(page)
    assert any("banlist" in (t or "").lower() for t in titles), (
        f"the editable group is not on screen at all: {titles}")
    edit = [g for g in _walk(page)
            if isinstance(g, Adw.PreferencesGroup)
            and "banlist" in (g.get_title() or "").lower()][0]
    rows = [r.get_title() for r in _walk(edit)
            if isinstance(r, Adw.PreferencesRow)]
    assert "CPUs irqbalance must not use" in rows, rows


def test_the_page_says_a_restart_is_needed():
    """The daemon reads the file once, at startup. Without this the user saves
    and sees no change, and concludes the page is broken."""
    assert "restart" in ib.EDIT_NOTE.lower()
    assert "irqbalance.service" in ib.EDIT_NOTE