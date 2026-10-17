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
this", it is "a list mixes rows that reserve a column with rows that do not", and
that can happen on any page. A gate naming one page would pass the next page
that does the same thing — and the tell is always the same, an **absence** (the
missing prefix), which is the shape this repository keeps finding.

**What this can and cannot see, stated rather than implied.** It reads the
*built widget tree*, so it covers rows a page builds at construction. A row whose
icon arrives from an async read afterwards is judged before it is judged wrong.
That is the real limit, and it is why the Firmware row of the same family is
driven explicitly elsewhere.
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


def _rows_of(group):
    return [n for n in _walk(group, []) if isinstance(n, Adw.ActionRow)]


#: How many `GtkImage`s each row type carries **before any page touches it**.
#: Measured by constructing one of each: `ActionRow` 1 (libadwaita's expand
#: arrow), `ComboRow` 4, `EntryRow` 3, `SwitchRow` 3, `ExpanderRow` 4,
#: `PasswordEntryRow` 4, `SpinRow` 3.
#:
#: **This table is why the first version of this gate was worthless.** Counting
#: images and comparing *between rows* reported **12 pages** as ragged — because
#: an Updates group holds a `ComboRow` (4 images) beside `ActionRow`s (1), and
#: that is libadwaita's internals, not a page's prefix. Every one of those 12 was
#: a false positive, and the tell was that the number was implausibly high for a
#: defect this specific. Calibrating each row against *its own type's* baseline
#: is what turns "more images than usual" into "this page added a prefix here".
_BASELINE: dict[str, int] = {}

#: Widgets that **embed their own images** as part of being themselves. A row's
#: suffix is not part of the leading column, so an icon inside one of these is
#: not evidence of a prefix.
#:
#: This exclusion is not theoretical. The Remote Access page's directive rows
#: measured **3** page-added prefixes against **1** for the rows beside them,
#: and the measurement was wrong: three of those four images are inside the
#: suffix `Gtk.DropDown` (its own arrow, a search glyph and a clear glyph). The
#: row with the *fewer* images was the one that had a real prefix, so a gate
#: built on the uncorrected count would have "fixed" the correct row and left
#: the ragged pair alone.
_EMBEDS_IMAGES = ("DropDown", "ComboRow", "EntryRow", "PasswordEntryRow",
                  "SearchEntry", "Entry")


def _baseline_for(row) -> int:
    """Images this row type carries before the page adds anything."""
    name = type(row).__name__
    if name not in _BASELINE:
        try:
            _BASELINE[name] = _leading_images(type(row)(title="probe"))
        except Exception:                       # a row type that needs more args
            _BASELINE[name] = 0
    return _BASELINE[name]


def _added_prefixes(row) -> int:
    """How many prefix widgets the **page** put on this row."""
    return _leading_images(row) - _baseline_for(row)


#: Widgets that **embed their own images** as part of being themselves. A row's
#: suffix is not part of the leading column, so an icon inside one of these is
#: not evidence of a prefix.
#:
#: This exclusion is not theoretical. The Remote Access page's directive rows
#: measured **3** page-added prefixes against **1** for the rows beside them,
#: and the measurement was wrong: three of those four images are inside the
#: suffix `Gtk.DropDown` (its own arrow, a search glyph and a clear glyph). The
#: row with the *fewer* images was the one that had a real prefix, so a gate
#: built on the uncorrected count would have "fixed" the correct row and left
#: the ragged pair alone.
_IMBEDS_IMAGES = ("DropDown", "ComboRow", "EntryRow", "PasswordEntryRow",
                  "SearchEntry", "Entry")


def _leading_images(row) -> int:
    """How many images this row carries on its leading side, ignoring any that
    belong to a suffix widget's own internals.

    **Counting, not asking "is there one"** — and that correction came from
    running the control. A plain `AdwActionRow` **already contains one
    `GtkImage`**: libadwaita's own expand/arrow image. So
    `any(isinstance(n, Gtk.Image) ...)` is true for every row in the app, the
    gate reported every list as uniform, and its control failed.

    The count is what is invariant and it does not need to tell the internal
    image from one a page added:

    | row | images |
    |---|---|
    | no prefix | 1 (libadwaita's own) |
    | one prefix icon | 2 |
    | one **empty** placeholder | 2 |

    which is exactly why the Firmware fix uses an empty image of the same pixel
    size — it reserves the column without needing a verdict to draw, and it is
    indistinguishable from a real prefix by design.
    """
    total = 0
    stack = [row]
    while stack:
        node = stack.pop()
        if type(node).__name__ in _EMBEDS_IMAGES and node is not row:
            continue
        if isinstance(node, Gtk.Image):
            total += 1
        child = node.get_first_child()
        while child is not None:
            stack.append(child)
            child = child.get_next_sibling()
    return total


class TestNoListMixesIndentedAndFlushRows:
    def _check(self, pid, page) -> list[str]:
        offenders = []
        for group in (n for n in _walk(page, []) if isinstance(n, Adw.PreferencesGroup)):
            rows = _rows_of(group)
            if len(rows) < 2:
                continue
            # **Compared within a row type.** An `ActionRow`, a `SwitchRow` and
            # a `ComboRow` in one group are three different widgets, each with
            # its own internal chrome, and "one left edge" is a statement about
            # rows of the same kind lining up. Comparing across them flagged the
            # Security Keys page on rows that were already uniform within their
            # own kind — the kind of plausible-looking noise that teaches
            # everyone to ignore a gate.
            counts = {}
            for row in rows:
                counts.setdefault((type(row).__name__, _added_prefixes(row)),
                                  []).append(row)
            if len(counts) < 2:
                continue
            if len({k[0] for k in counts}) < 2:
                # One row type in this group: every count difference is real.
                pass
            else:
                # Several row types: only judge each type against itself.
                by_type = {}
                for (rtype, n), group_rows in counts.items():
                    by_type.setdefault(rtype, {}).setdefault(n, group_rows)
                offenders_local = []
                for rtype, per_count in by_type.items():
                    if len(per_count) < 2:
                        continue
                    smallest = min(len(v) for v in per_count.values())
                    for n, group_rows in per_count.items():
                        if len(group_rows) == smallest and len(per_count) > 1:
                            offenders_local.append(
                                f"{rtype} rows carry {sorted(per_count)} "
                                f"prefixes; under-reserved: "
                                + ", ".join(repr(r.get_title())[:24]
                                            for r in group_rows[:3]))
                if offenders_local:
                    offenders.extend(
                        f"{group.get_title() or '(untitled group)'}: {o}"
                        for o in offenders_local)
                continue
            # **Name both sides on a tie.** The first version took
            # `min(counts, key=len)`, which on a two-and-two split returns the
            # first key rather than the smaller side - so on the Encryption page
            # it reported "Not encrypted" when the row without the column was
            # the TPM row above it. The *verdict* was right and the *instruction*
            # was wrong, which is worse than useless: it would have sent someone
            # to edit the row that was already correct.
            smallest = min(len(v) for v in counts.values())
            minority = sorted(k for k, v in counts.items() if len(v) == smallest)
            offenders.append(
                f"{group.get_title() or '(untitled group)'}: rows carry "
                f"{sorted(n for _t, n in counts)} page-added prefixes between "
                f"them, so the list has {len(counts)} left edges — the "
                f"under-reserved rows are "
                + "; ".join(
                    ", ".join(repr(r.get_title())[:24] for r in counts[k][:3])
                    for k in minority))
        return offenders

    @pytest.mark.parametrize(
        "cls,pid",
        [(p[0], p[1]) for _g, subs in __import__(
            "shani_cassini.notebook", fromlist=["SECTIONS"]).SECTIONS
         for _s, pages in subs for p in pages],
        ids=[p[1] for _g, subs in __import__(
            "shani_cassini.notebook", fromlist=["SECTIONS"]).SECTIONS
             for _s, pages in subs for p in pages],
    )
    def test_no_group_mixes_prefixed_and_unprefixed_rows(self, cls, pid) -> None:
        offenders = self._check(pid, cls())
        assert not offenders, (
            f"{pid}: " + "; ".join(offenders[:3]) +
            ". Give every row in the list the same leading column - an empty "
            "image of the same pixel size is how a row reserves the space "
            "without a verdict to draw.")

    def test_the_check_can_see_a_mixed_list(self):
        """The control: the exact shape Firmware had."""
        group = Adw.PreferencesGroup(title="Devices")
        plain = Adw.ActionRow(title="carried", subtitle="x")
        marked = Adw.ActionRow(title="updatable", subtitle="y")
        marked.add_prefix(Gtk.Image.new_from_icon_name(
            "emblem-system-synchronizing-symbolic"))
        group.add(plain)
        group.add(marked)

        offenders = self._check("control", Adw.PreferencesGroup())
        offenders = self._check("control", _Wrapper(group))
        assert offenders, (
            "a group with one prefixed row and one unprefixed row was measured "
            "as consistent, so this gate cannot see the defect it was written "
            "for")

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
        without a verdict to draw. If this stopped counting, the Firmware fix
        would read as a defect to its own gate.
        """
        row = Adw.ActionRow(title="carried")
        assert _added_prefixes(row) == 0, (
            "a row with nothing added does not measure zero page-added "
            "prefixes")

        row.add_prefix(Gtk.Image.new_from_icon_name(""))
        assert _added_prefixes(row) == 1, (
            "an empty placeholder stopped counting as a reserved column, so "
            "the Firmware fix and this gate now disagree about the same row")

    def test_a_suffix_dropdown_is_not_counted_as_a_prefix(self):
        """The Remote Access false positive, named so it cannot come back.

        A row with a real prefix **and** a suffix `Gtk.DropDown` measures **2**:
        libadwaita's own expand image plus the page's prefix. Without the
        exclusion it measured **4**, because the dropdown contributes three icons
        of its own (its arrow, a search glyph and a clear glyph) — and then it
        looked *more* decorated than a row that had no prefix at all, which is
        backwards. The gate would have reported the prefixed row as the odd one
        out and had someone edit the correct row.

        So the assertion is that the dropdown contributes **nothing**: a prefixed
        row with a dropdown measures exactly one more than a bare row. It is not
        that the two are equal — they are not, and they should not be; this one
        really does have a prefix.
        """
        prefixed = Adw.ActionRow(title="prefixed")
        prefixed.add_prefix(Gtk.Image.new_from_icon_name("dialog-information-symbolic"))
        prefixed.add_suffix(Gtk.DropDown.new_from_strings(["a", "b"]))

        bare = Adw.ActionRow(title="bare")
        assert _leading_images(prefixed) - _leading_images(bare) == 1, (
            f"prefixed={_leading_images(prefixed)} bare={_leading_images(bare)}: "
            f"the difference is not the one prefix, so the dropdown's own icons "
            f"are still being counted as the row's leading column")

    def test_a_dropdown_only_difference_is_not_an_offender(self):
        """Two rows that differ *only* by a suffix dropdown are not ragged.

        Same column, same prefix, different suffix — the leading text lines up,
        which is the whole point. This is the Remote Access pair as it actually
        is, and the version of this test that asserted the two rows were
        identical was itself wrong.
        """
        group = Adw.PreferencesGroup(title="Settings")
        first = Adw.ActionRow(title="a")
        first.add_prefix(Gtk.Image.new_from_icon_name("dialog-information-symbolic"))
        first.add_suffix(Gtk.DropDown.new_from_strings(["a", "b"]))
        second = Adw.ActionRow(title="b")
        second.add_prefix(Gtk.Image.new_from_icon_name("object-select-symbolic"))
        second.add_suffix(Gtk.DropDown.new_from_strings(["a", "b"]))
        group.add(first)
        group.add(second)
        assert not self._check("control", _Wrapper(group))

    def test_a_combo_row_beside_an_action_row_is_not_an_offender(self):
        """The 12 false positives, named so they cannot come back.

        A `ComboRow` carries 4 internal images and an `ActionRow` carries 1.
        Mixing them in one group is ordinary libadwaita, not a ragged edge —
        this is what the first version of this gate called a defect on twelve
        pages.
        """
        group = Adw.PreferencesGroup(title="Updates")
        group.add(Adw.ActionRow(title="Version"))
        group.add(Adw.ComboRow(title="Update channel", model=Gtk.StringList()))
        assert not self._check("control", _Wrapper(group))


class _Wrapper(Adw.Bin):
    """Just a parent, so the control can hand a group to the checker."""

    def __init__(self, child):
        super().__init__(child=child)