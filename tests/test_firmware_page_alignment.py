"""Every device row on the Firmware page starts at the same x.

**Found by rendering the page (2026-10-17).** `add_prefix` was called only for a
device fwupd can write to. On a machine with exactly one such device — which is
the normal shape, and here it was an integrated camera — the list had a **ragged
left edge**: that one name sat ~30px right of every other name, its wrapped
second line (`serial 0001`) hung at a third indent again, and the single row a
user could act on was the one that looked different from all the others.

This is not a preference about whether the icon should be there. The icon is
right, and the verdict is already spelled out in the subtitle as `Updatable` /
`Carried, not updatable`. What is wrong is that **only some rows reserve the
space**, so the column exists for one row and not the rest — and an
inconsistently-indented list is read as "these are a different kind of thing",
which on this page means "actionable", which is not what the other rows are.

The gate therefore asserts the **count and the alignment**, because either half
alone would pass while the list still looked wrong:

* every row carries exactly one prefix image, updatable or not;
* every one of those images is the same size — an unaligned column is the
  defect, so an empty icon and a 16px one are not equivalent.
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


def _prefixes(row):
    """The images on a row's leading side, in order.

    `get_visible()` is the discriminator rather than position: the icons live
    behind internal wrappers, and the row's own prefix is the one this page
    adds, which is the only one carrying a pixel size here.
    """
    return [n for n in _walk(row, [])
            if isinstance(n, Gtk.Image) and n.get_visible()]


def _column(row):
    """The width of a row's leading column.

    **`get_pixel_size()`, not `get_width()`.** A widget that has never been
    mapped reports `get_width() == 0` for everything, so a width comparison on
    it passes for any two rows whatever their real columns are — including a row
    with no column at all. The first version of this gate did that and failed
    with every row measuring zero. The pixel size is what the page *asks* for,
    it is set at construction, and it is what the alignment actually consists of.
    """
    icons = _prefixes(row)
    if not icons:
        return 0
    sizes = [i.get_pixel_size() for i in icons]
    assert len(set(sizes)) == 1, (
        f"{row.get_title()!r} has leading images of {sizes}px; one column is "
        f"one size")
    return sizes[0]


def _render_devices(devices):
    """Build the page and feed it a device list, then hand back its rows."""
    from shani_cassini.auth import AuthManager
    from shani_cassini.state import AppState
    from shani_cassini.tabs.firmware import FirmwareTab

    tab = FirmwareTab(state=AppState(), auth_manager=AuthManager())
    renderer = tab._render_devices
    renderer({"ok": True, "devices": devices})
    # The page has rows of its own ("Devices", "Updates", "Revision",
    # "Installing firmware"), so the device rows are picked out by name rather
    # than by "every ActionRow" — counting the page's own rows would make the
    # column assertion true for the wrong reason.
    wanted = {(d["name"] or "(unnamed device)") for d in devices}
    return [n for n in _walk(tab, [])
            if isinstance(n, Adw.ActionRow) and n.get_title() in wanted]


def _device(name, updatable, serial=None):
    return {"name": name, "version": "1.0", "version_format": "text",
            "updatable": updatable, "vendor": "", "serial": serial,
            "update_state": ""}


class TestTheDeviceListHasOneLeftEdge:
    def test_every_row_reserves_the_same_leading_column(self):
        rows = _render_devices([
            _device("carried-one", False),
            _device("updatable-one", True, serial="0001"),
            _device("carried-two", False),
            _device("updatable-two", True),
        ])
        assert len(rows) >= 4, f"only {len(rows)} device rows were built"

        widths = []
        for row in rows:
            icons = _prefixes(row)
            assert len(icons) == 1, (
                f"{row.get_title()!r} carries {len(icons)} leading icons; a "
                f"column that exists for some rows and not others is the ragged "
                f"edge this gate is about")
            widths.append(_column(row))

        assert len(set(widths)) == 1, (
            f"the leading column is {sorted(set(widths))}px wide depending on "
            f"the row, so the device names do not line up")
        assert widths[0] > 0, (
            "every device row measures a zero-width column, so nothing is "
            "aligned - the names are only flush by accident")

    def test_an_updatable_device_still_says_so(self):
        """Aligning the column must not cost the row its icon."""
        rows = _render_devices([_device("cam", True, serial="0001")])
        icons = _prefixes(rows[0])
        assert icons[0].get_icon_name(), (
            "the updatable device lost its icon when the column was aligned; the "
            "alignment fix must not delete the signal")
        assert "Updatable" in (rows[0].get_subtitle() or "")

    def test_a_carried_device_has_no_icon_but_the_same_column(self):
        rows = _render_devices([_device("spi", False)])
        icons = _prefixes(rows[0])
        assert not icons[0].get_icon_name(), (
            "a device fwupd cannot write to is given an icon it does not have a "
            "verdict for")
        assert "Carried, not updatable" in (rows[0].get_subtitle() or "")

    def test_the_control_can_see_a_missing_column(self):
        """A check that cannot see the defect is not a check."""
        # The unfixed shape: prefix only when updatable, and at the default
        # size. Both rows then report zero leading icons and different widths,
        # which is what the real defect looked like.
        plain = Adw.ActionRow(title="a", subtitle="x")
        assert len(_prefixes(plain)) == 0

        icon = Gtk.Image.new_from_icon_name(
            "emblem-system-synchronizing-symbolic")
        icon.set_pixel_size(16)
        marked = Adw.ActionRow(title="b", subtitle="y")
        marked.add_prefix(icon)
        assert len(_prefixes(marked)) == 1
        assert _prefixes(marked)[0].get_pixel_size() > 0, (
            "an aligned column still has to have a width")