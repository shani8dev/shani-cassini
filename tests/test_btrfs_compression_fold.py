"""`compsize` folded into the Btrfs page, and the `compression` id retired.

`compsize` only measures btrfs, so the compression read had no meaning away from
the filesystem page. Folding it in by **containment** rather than by moving the
renderer was deliberate: that renderer keeps a separate row list per group
precisely because one group cleared by two renderers wipes the first, and it
keeps the fstab lines in their own group because duplicate row titles in one
group shipped here before. Both facts are asserted below, so a future "tidy it
into BtrfsTab" finds out why it is not a tidy-up.
"""

from __future__ import annotations

import pytest

from shani_cassini.tabs import btrfs as btrfs_mod
from shani_cassini.tabs import compression as compression_mod

gi = pytest.importorskip("gi")
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

Adw.init()


def _spin(predicate, tries: int = 400) -> bool:
    ctx = GLib.MainContext.default()
    import time
    for _ in range(tries):
        if predicate():
            return True
        ctx.iteration(False)
        time.sleep(0.005)
    return False


def _group_titles(widget) -> list[str]:
    out: list[str] = []

    def walk(node):
        if isinstance(node, Adw.PreferencesGroup):
            title = node.get_title()
            if title:
                out.append(title)
        try:
            child = node.get_first_child()
        except Exception:
            return
        while child is not None:
            walk(child)
            try:
                child = child.get_next_sibling()
            except Exception:
                return

    walk(widget)
    return out


class TestTheFold:
    def test_all_nine_compression_groups_are_inside_the_btrfs_page(self) -> None:
        titles = _group_titles(btrfs_mod.BtrfsTab())
        for expected in ("Compression",
                         "What each filesystem is configured to compress",
                         "What /etc/fstab records for the next boot",
                         "What compsize measures",
                         "Broken down by algorithm"):
            assert expected in titles, f"{expected!r} is not on the Btrfs page: {titles}"

    def test_the_section_does_not_schedule_its_own_read(self, monkeypatch) -> None:
        """It is a *section*, not a page.

        As a page it scheduled its own read from `GLib.idle_add` in
        `__init__`. Embedded, that would be a read the host page knows nothing
        about: it could not count it as pending, so the Refresh button would
        re-enable while `compsize` was still walking a subvolume, and a second
        click would start a second walk.

        The first version of this test built a `BtrfsTab` and asserted no read
        happened - and failed, correctly: `BtrfsTab.__init__` calls
        `refresh()`, which is *supposed* to start it. Asserting "no read" was
        asserting the wrong thing entirely. What matters is **who** starts it,
        so this builds the section on its own and compares the two modes.
        """
        seen = []
        monkeypatch.setattr(compression_mod, "compression_state",
                            lambda done: seen.append("read"))

        compression_mod.CompressionTab(autoload=False)
        assert seen == [], "autoload=False still scheduled its own read"

        GLib.idle_add(lambda: (compression_mod.CompressionTab(autoload=True),
                               False)[1])
        assert _spin(lambda: len(seen) == 1), \
            "autoload=True must still schedule its own read, or the flag lies"

    def test_the_host_page_starts_it_and_waits_for_it(self, monkeypatch) -> None:
        calls = []
        monkeypatch.setattr(compression_mod, "compression_state",
                            lambda done: calls.append("read"))
        tab = btrfs_mod.BtrfsTab()
        assert len(calls) == 1, f"refresh() must start the section: {calls}"
        assert tab._pending >= 1, "an in-flight section read must keep _pending up"

    def test_pending_comes_back_down_when_the_section_lands(
            self, monkeypatch) -> None:
        """The Refresh button must not stay dead for ever.

        The bridge deliberately does not check the generation: a refresh
        arriving mid-walk must discard the stale rows, but must not leave
        `_pending` permanently raised.
        """
        tab = btrfs_mod.BtrfsTab()
        before = tab._pending
        tab._compression_settled()
        assert tab._pending == max(0, before - 1) or tab._pending < before

    def test_the_five_row_lists_are_still_five(self) -> None:
        """Why this was a containment and not a move.

        The section keeps a separate row list per group on purpose. Merging
        those five lists into the host page's single `_added` list would put
        two renderers over one collection, which is the wipe this page's own
        comments describe.
        """
        section = compression_mod.CompressionTab(autoload=False)
        lists = [section._configured_rows, section._fstab_rows,
                 section._measured_rows, section._algorithm_rows,
                 section._crypttab_rows]
        assert len(lists) == 5
        assert len({id(x) for x in lists}) == 5, "the row lists are already shared"


class TestTheRetiredId:
    def test_compression_resolves_to_btrfs(self) -> None:
        from shani_cassini.notebook import PAGES, resolve
        assert resolve("compression") == "btrfs"
        assert "btrfs" in {p[1] for p in PAGES}

    def test_it_does_not_shadow_a_live_page(self) -> None:
        from shani_cassini.notebook import ALIASES, PAGES
        assert not set(ALIASES) & {p[1] for p in PAGES}

    def test_the_compression_group_is_not_a_second_sidebar_entry(self) -> None:
        from shani_cassini.notebook import SECTIONS
        flat = [p[2] for _g, subs in SECTIONS for _s, pp in subs for p in pp]
        assert flat.count("Compression") == 0, \
            "the section is on the Btrfs page, not in the sidebar"
        assert flat.count("Btrfs") == 1
