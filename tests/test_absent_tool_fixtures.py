"""The controls for `absent_tools` / `one_tool_absent`.

These are here, in a collected module, rather than at the bottom of
`tests/conftest.py` — where they were written first, and where pytest **does not
collect tests from**, so they would never have run. That is the same
"a check that cannot fail" shape as everywhere else in this repo's history, and
the only reason it was caught is that collection was counted rather than
assumed.

What is being controlled: `monkeypatch.setenv("PATH", <empty dir>)` is widely
used in this suite to mean "a machine without that tool". It is honest for a
`/usr/bin` tool and **wrong for an sbin-only one**, because `have_tool()` falls
back to `/usr/sbin` and `/usr/local/sbin` absolutely — the same trap `AGENTS.md`
records for `smartctl` and `aa-status`. The silence is the problem: the fixture
reads as "this machine has neither tool", the branch is not taken, and nothing
says why.
"""

from __future__ import annotations

import pytest

from shani_cassini import system_status as ss


class TestTheFixturesAreReal:
    def test_the_measurement_this_file_rests_on(self, monkeypatch, tmp_path):
        """The table in `tests/conftest.py`, as an assertion.

        Emptying PATH hides a `/usr/bin` tool and does NOT hide an sbin-only one,
        because `_tool_path()` falls back to `SBIN_DIRS` absolutely. Both halves
        are checked: the first so the guidance is not over-stated, the second so
        it is not under-stated. A test that only checked the first would let
        someone read "PATH-emptying is fine" and go on to lie about `smartctl`.
        """
        from shani_cassini import system_status as ss
        assert ss.SBIN_DIRS, "SBIN_DIRS is empty; the sbin fallback is gone"
        monkeypatch.setenv("PATH", str(tmp_path))
        # /usr/bin only -> PATH is the only thing that can find it
        assert ss.have_tool("ls") is False, (
            "have_tool now searches /usr/bin absolutely, so emptying PATH is no "
            "longer sufficient for any tool and the fixtures' premise changed")
        # and the sbin half: point SBIN_DIRS at a real dir holding a fake tool
        fake = tmp_path / "sbin"
        fake.mkdir()
        (fake / "faketool").write_text("#!/bin/sh\n")
        (fake / "faketool").chmod(0o755)
        monkeypatch.setattr(ss, "SBIN_DIRS", (str(fake),))
        assert ss.have_tool("faketool") is True, (
            "have_tool no longer searches SBIN_DIRS, so an emptied PATH now "
            "hides everything and the fixtures are stronger than documented")

    def test_absent_tools_makes_every_tool_absent(self, absent_tools):
        assert ss.have_tool("podman") is False
        assert ss.have_tool("smartctl") is False
        assert ss.have_tool("aa-status") is False
        assert ss.tool_path_or_self("podman") == "podman"

    def test_absent_tools_also_hides_an_sbin_tool(self, absent_tools,
                                                  monkeypatch, tmp_path):
        """The half that PATH-emptying gets wrong, checked directly."""
        fake = tmp_path / "sbin"
        fake.mkdir()
        (fake / "faketool").write_text("#!/bin/sh\n")
        (fake / "faketool").chmod(0o755)
        monkeypatch.setattr(ss, "SBIN_DIRS", (str(fake),))
        assert ss.have_tool("faketool") is False, (
            "the fixture patched have_tool but a caller holding its own "
            "reference, or using _tool_path directly, would still find it")

    def test_one_tool_absent_leaves_the_others_findable(self, one_tool_absent):
        one_tool_absent("distrobox")
        assert ss.have_tool("distrobox") is False
        assert ss.have_tool("podman") is True
        one_tool_absent()
        assert ss.have_tool("distrobox") is True

    def test_the_fixture_records_what_the_page_asked_about(self, absent_tools):
        """How a test tells "the page took the absent branch" apart from "the
        page never looked"."""
        assert ss.have_tool("podman") is False
        assert "podman" in absent_tools, (
            "have_tool was patched, so the page's own call has to be recorded")


class TestAPageActuallyTakesTheBranch:
    """And the fixtures are not merely self-consistent — they move a real page
    onto the branch under test. Without this, the two tests above would pass even
    if the pages ignored `have_tool` entirely."""

    def test_a_page_reports_the_tool_missing_when_the_fixture_says_so(
            self, absent_tools) -> None:
        gi = pytest.importorskip("gi")
        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw
        Adw.init()
        from shani_cassini.tabs.containers import ContainersTab
        tab = ContainersTab()
        from tests.test_containers_page import settled
        assert settled(tab)
        assert "podman" in absent_tools, \
            "the page did not consult have_tool at all"
        text = " ".join(
            r.get_subtitle() or "" for r in _rows(tab))
        assert "podman is not installed" in text, text

    def test_and_reports_it_present_when_the_fixture_does_not(
            self, monkeypatch) -> None:
        """The other direction, so the fixture cannot pass by making everything
        look absent to every page at once."""
        gi = pytest.importorskip("gi")
        gi.require_version("Gtk", "4.0")
        gi.require_version("Adw", "1")
        from gi.repository import Adw
        Adw.init()
        monkeypatch.setattr(ss, "have_tool", lambda cmd: True)
        from shani_cassini.tabs.containers import ContainersTab
        tab = ContainersTab()
        from tests.test_containers_page import settled
        assert settled(tab)
        text = " ".join(r.get_subtitle() or "" for r in _rows(tab))
        assert "podman is not installed" not in text, text


def _rows(tab):
    from gi.repository import Adw
    out, stack = [], [tab]
    while stack:
        w = stack.pop()
        if isinstance(w, Adw.ActionRow):
            out.append(w)
        child = w.get_first_child()
        while child is not None:
            stack.append(child)
            child = child.get_next_sibling()
    return out
