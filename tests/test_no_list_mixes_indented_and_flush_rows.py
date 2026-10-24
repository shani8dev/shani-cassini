"""Within one group, either every row reserves a leading column or none does.

**Found by rendering the Firmware page (2026-10-17), and it is a class.**
`add_prefix` was called only for a device fwupd can write to, so on a machine
with one such device the list had a **ragged left edge**: that name sat ~30px
right of every other, and its wrapped second line hung at a third indent again.

The idea behind it — "only the rows that deserve a glyph get one" — is
sensible. The defect is mechanical: `add_prefix` on **some** rows of a list
reserves horizontal space for **all** of them, so "only some rows have an icon"
renders as "all rows are indented, and a few of them more than the others". The
reader sees a grouping the page never declared, and on Firmware the row left
alone was the one a user can act on.

**Why this is app-wide and not a Firmware test.** The fault is not "Firmware does
this", it is "a list mixes rows that reserve a column with rows that do not",
and that can happen on any page. A gate naming one page would pass the next page
that does the same thing — and the tell is always the same, an **absence** (the
missing prefix), which is the shape this repository keeps finding.

---

## Counting prefixes took four attempts, and each earlier one was wrong

This is the part worth keeping. Every version below passed a suite while
measuring the wrong thing, and three of the four were found by running the
control rather than by reading the assertion.

**1. "Does this row contain a `GtkImage`?" — always true.** A plain
`AdwActionRow` already contains one: libadwaita's own expand arrow. So every row
in the app looked like it had a prefix, every list came back uniform, and the
control failed.

**2. "How many images does the row contain, compared between rows?" — 12 false
positives.** `ComboRow` carries 4 internal images and `ActionRow` carries 1, so
a group holding both reported a difference that was libadwaita's internals, not
a page's prefix. Calibrating each row against *its own type's* baseline fixed
those 12 — and was still wrong.

**3. "Count every image, minus a per-type baseline, and exclude images inside a
widget that embeds its own."** This worked until it met **Security Keys**, where
`EntryRow`/`SwitchRow`/`ComboRow` rows sat flush at x=14 beside `ActionRow`s at
x=42. That is a real ragged edge, measured off a whole-page render:

    Mode                            left=14
    Key file (authfile)             left=14
    Key id (id)             [warn]  left=42   (title)
    Challenge-response secret file  left=14
    Accept any key (alwaysok)       left=14

The escape from it — "compare only rows of the same type, because an
`ActionRow`, a `SwitchRow` and a `ComboRow` are three different widgets" —
**hid the very defect it was added to survive.** Removing it makes 39 pages fail,
so it cannot simply be dropped either.

**4. Count images in the row's *prefix box*, which is positional.** The row's
first child is a `Box` whose first child is the prefix area, and its contents are
exactly what `add_prefix` put there. Measured across every row type:

    | row                                   | prefix box |
    |---------------------------------------|------------|
    | `ActionRow`, nothing added            | 0          |
    | `ActionRow`, one icon                 | 1          |
    | `ActionRow`, one **empty placeholder**| 1          |
    | `EntryRow`, nothing added             | 0          |
    | `EntryRow`, one icon                  | 1          |
    | `ComboRow` with a model, nothing added| **0**      |
    | `SwitchRow`, nothing added            | 0          |

That last-but-one row is the one that mattered: a `ComboRow`'s arrow, search and
clear glyphs live in its **suffix**, so a count that walked the whole row called
Remote Access's prefixed rows *more* decorated than the unprefixed ones — and the
row with fewer images was the correct one. A positional count cannot get that
backwards, needs no baseline table, and compares across row types correctly, so
it catches Security Keys without excluding it.

An **empty image of the same pixel size** is deliberately indistinguishable from a
real prefix here, because that is exactly how `widgets.reserve_leading_column`
reserves a column without inventing a verdict to draw.
"""

from __future__ import annotations

import pytest

gi = pytest.importorskip("gi")
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

Adw.init()


def _walk(widget, out, depth=0):
    assert depth < 40, "widget tree deeper than 40 - a cycle, not a page"
    out.append(widget)
    child = widget.get_first_child()
    while child is not None:
        _walk(child, out, depth + 1)
        child = child.get_next_sibling()
    return out


def _prefix_count(row) -> int:
    """How many widgets the **page** put in this row's leading column.

    Positional, and that is the whole trick: the row's first child is a `Box`
    whose first child is the prefix area, so this reads what `add_prefix` put
    there and nothing else. It needs no per-type baseline (a configured
    `ComboRow` or `EntryRow` does not carry the same internals as a freshly
    constructed one, which is what made baselines unreliable), and it excludes a
    suffix widget's own glyphs for free.
    """
    box = row.get_first_child()
    if box is None:
        return 0
    prefix = box.get_first_child()
    if prefix is None:
        return 0
    return sum(1 for n in _walk(prefix, []) if isinstance(n, Gtk.Image))


def _rows_of(group):
    return [n for n in _walk(group, []) if isinstance(n, Adw.ActionRow)]


def _all_pages():
    from shani_cassini.notebook import SECTIONS
    for _group, subsections in SECTIONS:
        for _name, pages in subsections:
            for entry in pages:
                yield entry[1], entry[0]


class TestNoListMixesIndentedAndFlushRows:
    def _check(self, pid, page) -> list[str]:
        offenders = []
        for group in (n for n in _walk(page, []) if isinstance(n, Adw.PreferencesGroup)):
            rows = _rows_of(group)
            if len(rows) < 2:
                continue
            counts: dict[int, list] = {}
            for row in rows:
                counts.setdefault(_prefix_count(row), []).append(row)
            if len(counts) < 2:
                continue
            # **Name every side on a tie.** `min(counts, key=len)` returns the
            # first key on a two-and-two split, not the smaller side — which on
            # the Encryption page named `Not encrypted` when the row without the
            # column was the TPM row above it. The verdict right and the
            # instruction wrong is worse than no message.
            smallest = min(len(v) for v in counts.values())
            minority = sorted(k for k, v in counts.items() if len(v) == smallest)
            offenders.append(
                f"{group.get_title() or '(untitled group)'}: rows reserve "
                f"{sorted(counts)} leading columns between them, so the list has "
                f"{len(counts)} left edges — the under-reserved rows are "
                + "; ".join(
                    ", ".join(repr(r.get_title())[:24] for r in counts[k][:3])
                    for k in minority))
        return offenders

    @pytest.mark.parametrize("pid,cls", list(_all_pages()),
                             ids=[pid for pid, _c in _all_pages()])
    def test_no_group_mixes_reserved_and_flush_rows(self, pid, cls) -> None:
        try:
            page = cls()
        except Exception:
            pytest.skip(f"{pid} could not be constructed here")
        offenders = self._check(pid, page)
        assert not offenders, (
            f"{pid}: " + "; ".join(offenders[:3]) +
            ". Give every row in the list the same leading column - "
            "`widgets.reserve_leading_column` adds an empty image of the same "
            "pixel size, which reserves the space without a verdict to draw.")

    def test_the_check_can_see_a_mixed_list(self):
        """The control: the exact shape Firmware had."""
        group = Adw.PreferencesGroup(title="Devices")
        plain = Adw.ActionRow(title="carried", subtitle="x")
        marked = Adw.ActionRow(title="updatable", subtitle="y")
        marked.add_prefix(Gtk.Image.new_from_icon_name(
            "emblem-system-synchronizing-symbolic"))
        group.add(plain)
        group.add(marked)

        offenders = self._check("control", _Wrapper(group))
        assert offenders, (
            "a group with one reserved row and one flush row was measured as "
            "consistent, so this gate cannot see the defect it was written for")

    def test_a_mixed_list_is_caught_across_row_types(self):
        """The control for the hole that was papered over rather than fixed.

        Security Keys put an `EntryRow` beside `ActionRow`s in one card, and the
        first version of this gate **passed it**, because it compared only rows
        of the same type. This is the shape that hid for a whole session.
        """
        group = Adw.PreferencesGroup(title="Settings")
        flush_entry = Adw.EntryRow(title="Key file (authfile)",
                                   show_apply_button=True)
        icon_row = Adw.ActionRow(title="Site (origin)")
        icon_row.add_prefix(Gtk.Image.new_from_icon_name("dialog-warning-symbolic"))
        flush_switch = Adw.SwitchRow(title="Accept any key (alwaysok)")
        group.add(flush_entry)
        group.add(icon_row)
        group.add(flush_switch)

        offenders = self._check("control", _Wrapper(group))
        assert offenders, (
            "an EntryRow and a SwitchRow sitting flush beside an ActionRow with "
            "a prefix was measured as consistent - this is the Security Keys "
            "defect, and the per-type comparison used to pass it")

    def test_a_uniform_list_is_not_an_offender(self):
        group = Adw.PreferencesGroup(title="Devices")
        for name in ("a", "b", "c"):
            row = Adw.ActionRow(title=name)
            row.add_prefix(Gtk.Image.new_from_icon_name(""))
            group.add(row)
        assert not self._check("control", _Wrapper(group))

        plain = Adw.PreferencesGroup(title="Devices")
        for name in ("a", "b", "c"):
            plain.add(Adw.ActionRow(title=name))
        assert not self._check("control", _Wrapper(plain))

    def test_an_empty_placeholder_counts_as_reserving_the_column(self):
        """The fix's own mechanism, asserted directly.

        An empty image of the same pixel size is what lets a row keep the column
        without a verdict to draw. If this stopped counting, the fix and this
        gate would disagree about the same row.
        """
        row = Adw.ActionRow(title="carried")
        assert _prefix_count(row) == 0, (
            "a row with nothing added does not measure zero reserved prefixes")
        row.add_prefix(Gtk.Image.new_from_icon_name(""))
        assert _prefix_count(row) == 1, (
            "an empty placeholder stopped counting as a reserved column, so "
            "the fix and this gate now disagree about the same row")

    def test_a_suffix_widgets_own_icons_are_not_counted(self):
        """The Remote Access inversion: the row with fewer images was correct.

        A `ComboRow` with a model carries three glyphs of its own. Counting the
        whole row called the *prefixed* rows the more decorated ones.
        """
        bare = Adw.ActionRow(title="bare")
        bare.add_suffix(Gtk.DropDown.new_from_strings(["a", "b"]))
        prefixed = Adw.ActionRow(title="prefixed")
        prefixed.add_prefix(Gtk.Image.new_from_icon_name("dialog-information-symbolic"))
        prefixed.add_suffix(Gtk.DropDown.new_from_strings(["a", "b"]))

        assert _prefix_count(prefixed) - _prefix_count(bare) == 1, (
            f"prefixed={_prefix_count(prefixed)} bare={_prefix_count(bare)}: the "
            f"difference is not the one prefix, so a suffix widget's icons are "
            f"still being counted as the row's leading column")

    def test_a_combo_row_with_no_prefix_reserves_nothing(self):
        """The 12 false positives, named so they cannot come back."""
        group = Adw.PreferencesGroup(title="Updates")
        group.add(Adw.ActionRow(title="Version"))
        group.add(Adw.ComboRow(title="Update channel",
                               model=Gtk.StringList.new(["a", "b"])))
        assert not self._check("control", _Wrapper(group))


class _Wrapper(Adw.Bin):
    """Just a parent, so the control can hand a group to the checker."""

    def __init__(self, child):
        super().__init__(child=child)
