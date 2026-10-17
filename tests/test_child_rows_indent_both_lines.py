"""A row's indent must move its title **and** its subtitle, or it is not an indent.

**Found by rendering the whole Modules page rather than the window, 2026-10-17.**
The page indents a module's parameter rows beneath the module, and it did it with
four literal spaces inside the parameter's **title string**:

    child = _row(f"    {_esc(param['name'])}", _esc(param["value"]))

So only the title moved. Measured off the whole-page render:

    y=362..375  left_ink=28   `fork_from_owner_default`
    y=384..393  left_ink=14   `Y`

Each parameter's value sat flush with the module names instead of under its own
name, so a one-letter value read as a property of the module above it. Nothing
above the fold had ever shown this page's parameters — they start at y=340 of a
3000px page — so the sweep could not have found it either way.

**This had a test, and the test asserted the defect.** `test_filtering_the_
module_list_folds_a_module_with_its_own_parameters` found the parameter rows with
`get_title().startswith("    ")`. That was not an arbitrary choice: the spaces
*were* the indent, so the test was keyed on the very artefact of the bug and
could only ever agree with it. Four spaces in a title also survive into
`get_title()`, which is why every other assertion about these rows passed while
the screen was wrong.

The generalisable rule, and the reason this file exists rather than a line in
`test_new_gap_pages.py`: **an indent expressed in the text of a string moves one
line, and a test that recognises the row by that text is pinned to the bug.**
Both halves are now asserted — the row is found by its margin, and its title is
required to carry no leading whitespace.
"""

from __future__ import annotations

import pytest

gi = pytest.importorskip("gi")
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

Adw.init()


def _walk(widget, out=None, depth=0):
    assert depth < 40, "widget tree deeper than 40 - a cycle, not a page"
    out = [] if out is None else out
    out.append(widget)
    child = widget.get_first_child()
    while child is not None:
        _walk(child, out, depth + 1)
        child = child.get_next_sibling()
    return out


@pytest.fixture
def modules_tab(tmp_path, monkeypatch):
    """A Modules page with one module carrying three parameters.

    The fixture tree is written by hand rather than reusing another file's: this
    test needs to *find* the parameter rows, and sharing a fixture with a test
    that finds them a different way is how the two drift apart silently.
    """
    import shani_cassini.system_status as ss
    from shani_cassini.tabs import modules as modules_mod

    proc = tmp_path / "modules"
    proc.write_text("iwlwifi 253440 0 - Live 0x0000000000000000\n")
    monkeypatch.setattr(ss, "PROC_MODULES", str(proc))
    root = tmp_path / "module"
    for key, value in (("power_save", "Y"), ("11n_disable", "0"),
                       ("bt_coex_active", "Y")):
        d = root / "iwlwifi" / "parameters"
        d.mkdir(parents=True, exist_ok=True)
        (d / key).write_text(value + "\n")
    monkeypatch.setattr(ss, "SYS_MODULE_ROOT", str(root))
    return modules_mod, modules_mod.ModulesTab()


def _param_rows(tab, modules_mod):
    # `isinstance` because `_walk` includes the page root itself, and the page
    # is a `Gtk.Box`: asking it for `get_margin_start` is fine, but the moment
    # one of these helpers reads `get_title()` the walk has to be narrowed -
    # found by running the control, not by reading it.
    return [r for r in _walk(tab)
            if isinstance(r, Adw.ActionRow)
            and r.get_margin_start() == modules_mod.CHILD_INDENT_PX]


class TestAChildRowIndentsBothLines:
    def test_the_indent_is_a_margin_not_whitespace_in_the_title(self, modules_tab):
        mod, tab = modules_tab
        rows = _param_rows(tab, mod)
        if not rows:
            # **Say what is there instead, rather than only that nothing is.**
            # "no row carries the child indent" reads like a fixture that did
            # not build, and the run would stop there having said nothing about
            # the defect. Naming the whitespace rows turns the same failure into
            # the diagnosis it is.
            spaced = [r for r in _walk(tab)
                      if isinstance(r, Adw.ActionRow)
                      and r.get_title()[:1].isspace()]
            assert not spaced, (
                f"{len(spaced)} parameter row(s) indent themselves with "
                f"whitespace in the title - e.g. {spaced[0].get_title()!r}. "
                f"Their values do not move with the names. Use "
                f"`set_margin_start(CHILD_INDENT_PX)`.")
            raise AssertionError(
                "no row carries the child indent and none is whitespace-indented "
                "either, so the fixture built no parameter rows at all")
        for row in rows:
            assert not row.get_title()[:1].isspace(), (
                f"{row.get_title()!r} indents itself with whitespace in the "
                f"title. That moves the title only: the value underneath stays "
                f"flush with the module names and reads as a property of the "
                f"module above. Use `set_margin_start`.")

    def test_a_parameter_row_has_both_a_name_and_a_value(self, modules_tab):
        """The thing the indent was for: a name over the value it belongs to."""
        mod, tab = modules_tab
        rows = _param_rows(tab, mod)
        assert rows, "no parameter rows were built"
        for row in rows:
            assert row.get_title().strip(), "a parameter row has no name"
            assert row.get_subtitle().strip(), (
                f"{row.get_title()!r} has no value; the row would then be a name "
                f"with nothing under it, which is what the indent was for")

    def test_the_control_a_title_indented_with_spaces_fails(self):
        """The control: the exact shape the page had.

        Built by hand, because the point is that the *checker* can see the old
        form. If this row passed, the gate above would be asserting nothing for
        the defect it was written for.
        """
        mod = pytest.importorskip("shani_cassini.tabs.modules")
        bad = Adw.ActionRow(title="    power_save", subtitle="Y")
        good = Adw.ActionRow(title="power_save", subtitle="Y")
        good.set_margin_start(mod.CHILD_INDENT_PX)

        assert bad.get_title()[:1].isspace(), \
            "a title with four leading spaces stopped reporting as such"
        assert good.get_title()[:1].isspace() is False, \
            "the control's un-indented row came back with whitespace in it"
        assert bad.get_margin_start() != good.get_margin_start(), (
            "the two rows now indent identically, so the margin cannot be what "
            "distinguishes them")

    def test_margins_do_not_move_the_title_string(self, modules_tab):
        """What a margin buys over spaces: the text itself is clean.

        Four leading spaces are copied when a user selects the row's text and
        they survive into `get_title()`, so every assertion about these rows
        agreed with each other while the screen was wrong.
        """
        mod, tab = modules_tab
        for row in _param_rows(tab, mod):
            assert row.get_title() == row.get_title().strip()
            assert not row.get_title().startswith((" ", "\t", "\n"))
