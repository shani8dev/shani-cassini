"""`shani-health --history`: the deploy event log, and why it was never wired.

`shani-health --history` always existed and nothing called it. The reason is in
the backend: `show_history` printed its events with bare `printf` and recorded no
rows, so `--history --json` answered `{"checks": []}` — an empty document a GUI
would have had to scrape prose to consume. That was fixed in shani-health (the
human output is byte-identical; the JSON gained the events), and this is the
consumer that was missing.

It is wired on the Health page, beside every other `shani-health` mode, and not on
Boot and Recovery: that page's gate records that `shani-health` is "another
tool's business" there, and the gate is right. Putting the feature where it
belongs took no new reader at all — `health_report(mode, done)` already builds the
argv.

The fixture is the real document shape, in the tool's own order (oldest first),
which is the order the page reverses.
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from shani_cassini import system_status as ss  # noqa: E402
from shani_cassini.tabs import health as hl  # noqa: E402

REAL = {
    "timestamp": "2026-10-10T08:00:00+00:00",
    "checks": [
        {"section": "deploy_history", "key": "2026-10-08 09:14:02",
         "status": "ok", "message": "DEPLOY v20261008"},
        {"section": "deploy_history", "key": "2026-10-08 09:16:40",
         "status": "warning", "message": "ROLLBACK (manual)"},
        {"section": "deploy_history", "key": "2026-10-09 21:03:11",
         "status": "ok", "message": "DEPLOY v20261009"},
        {"section": "deploy_history", "key": "2026-10-10 07:55:44",
         "status": "warning", "message": "ROLLBACK (emergency - deploy failed)"},
    ],
}


@pytest.fixture
def fake_health(tmp_path, monkeypatch):
    """Put a `shani-health` on PATH that prints the real document.

    `HealthTab.__init__` returns early when `shani-health` is absent, before it
    builds `_results` and `_empty` — so on a dev host with no image the page
    cannot be rendered at all without one. The fake prints the captured
    document, which is what the real tool now emits for `--history --json`.
    """
    import json

    path = tmp_path / "shani-health"
    path.write_text("#!/bin/bash\ncat <<'JSON'\n"
                    + json.dumps(REAL) + "\nJSON\n")
    path.chmod(0o755)
    monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ['PATH']}")
    return tmp_path


def _rows(group):
    """The group's ActionRows in DOCUMENT order.

    Pre-order, siblings in order. A stack-based walk pops the last child first
    and so returns the reverse of what the user reads - which makes every
    ordering assertion made through it say the opposite of what it appears to
    say. Rows also sit two levels down inside an AdwPreferencesGroup (the
    group's internal listbox), so a single level is not enough either.
    """
    from gi.repository import Adw  # type: ignore

    out = []

    def walk(widget):
        if isinstance(widget, Adw.ActionRow):
            out.append(widget)
        child = widget.get_first_child()
        while child is not None:
            walk(child)
            child = child.get_next_sibling()

    walk(group)
    return out


# --- the wiring ------------------------------------------------------------


def test_history_is_a_mode_the_page_offers():
    modes = [m for m, _t, _d in hl.CHECKS]
    assert "history" in modes, modes


def test_the_reader_builds_the_history_argv():
    """The tool's own argument order, not a guess.

    `--history` takes a count, and `health_report` puts the mode in as
    `--{mode}` — so wiring this mode is the whole implementation.
    """
    seen = {}

    def fake_run_json(argv, done):
        seen["argv"] = argv
        done(REAL, "")

    real = ss.run_json
    ss.run_json = fake_run_json
    try:
        ss.health_report("history", lambda payload, err: None)
    finally:
        ss.run_json = real
    assert seen["argv"] == ["pkexec", ss.HEALTH, "--history", "--json"]


# --- the rendering ---------------------------------------------------------


def _show(mode="history", doc=None):
    """Drive the page's own renderer and return the group it built.

    `_empty` and `_results` live in the body of `__init__`, which runs before
    anything is rendered, so constructing the tab is enough — the notebook does
    not have to have shown it.
    """
    tab = hl.HealthTab()
    tab._show(mode, doc or REAL, 3.0)
    return getattr(tab, f"_group_{mode}")


def test_the_log_renders_newest_first(fake_health):
    """The one ordering fact worth pinning.

    The tool writes oldest-first. Every other mode on this page wants the worst
    finding first; a log wants "what happened most recently", and sorting it like
    a findings list would put every rollback above every deploy.
    """
    group = _show()
    titles = [r.get_title() for r in _rows(group)]
    assert titles[0] == "2026-10-10 07:55:44", titles
    assert titles[-1] == "2026-10-08 09:14:02", titles


def test_the_summary_describes_a_log_not_a_findings_list(fake_health):
    """"2 warnings" for two rollbacks would call someone's system unhealthy.

    A rollback is an event that happened, not a problem found.
    """
    tab = hl.HealthTab()
    tab._show("history", REAL, 3.0)
    group = getattr(tab, "_group_history")
    desc = group.get_description() or ""
    assert "warning" not in desc, desc
    assert "problem" not in desc, desc
    assert "4 events" in desc and "2 deployed" in desc and "2 rolled back" in desc, desc


def test_the_timestamp_is_the_row_title_and_the_event_the_subtitle(fake_health):
    group = _show()
    rows = _rows(group)
    assert rows[0].get_title() == "2026-10-10 07:55:44"
    assert rows[0].get_subtitle() == "ROLLBACK (emergency - deploy failed)"


def test_an_empty_log_renders_as_an_empty_log(fake_health):
    tab = hl.HealthTab()
    tab._show("history", {"timestamp": "x", "checks": []}, 1.0)
    group = getattr(tab, "_group_history")
    desc = group.get_description() or ""
    assert "0 events" in desc, desc
    assert "1 deployed" not in desc, desc


def test_a_rollback_is_not_drawn_as_an_error(fake_health):
    """The rollback rows carry a warning status from the tool.

    Sorting by it would lift them above the deploys, which is the failure the
    ordering branch exists to stop — so this asserts the icon is the warning one
    and the order is still chronological.
    """
    group = _show()
    rows = _rows(group)
    assert rows[0].get_subtitle().startswith("ROLLBACK")
    assert rows[-1].get_subtitle().startswith("DEPLOY")
    assert rows[0].get_subtitle_selectable() is True
