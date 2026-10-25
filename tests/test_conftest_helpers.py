"""The controls for `assert_subtitle_shown_as_text` and `subtitle_getter_decodes`.

These live in a collected module rather than at the bottom of
`tests/conftest.py` — where pytest collects nothing — so they always run, the
same reason `test_absent_tool_fixtures.py` exists for its helper.

What is being controlled: the subtitle getter is stack-dependent (1.5.0
decodes, 1.9.4/1.9.1 returns as set) while the escaping property pages owe the
user is not. The helper measures the stack rather than assuming a version, so
its controls must keep the measurement honest on three fronts:

1. the probe's verdict must agree with what a real row on this build actually
   hands back for the page-shaped input (an escaped hostile string);
2. forced onto either convention, the helper must still **fail** for the two
   real defects it exists to catch — markup that was acted on, and a page that
   escaped twice — rather than quietly accepting both forms;
3. the helper passes for the correct page output on each convention.

Without 2, the per-convention branches could diverge silently: the as-set
branch could be tightened while the decoding branch accepts anything, or the
reverse, and no test on either stack would notice.
"""

from __future__ import annotations

import pytest
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GLib  # noqa: E402

import conftest as cf  # noqa: E402


@pytest.fixture()
def force_decoding(monkeypatch):
    """Pin the cached probe to the 1.5.0 answer for the duration of a test."""
    monkeypatch.setattr(cf, "_SUBTITLE_GETTER_DECODES", True)


@pytest.fixture()
def force_as_set(monkeypatch):
    """Pin the cached probe to the 1.9.4 answer for the duration of a test."""
    monkeypatch.setattr(cf, "_SUBTITLE_GETTER_DECODES", False)


def test_the_probe_answers_and_agrees_with_a_real_row() -> None:
    """The cached verdict is not a guess: a real row carrying the same shape
    the pages hand a subtitle (escaped hostile text) must hand back a String
    that agrees with what the probe concluded about this build."""
    assert isinstance(cf.subtitle_getter_decodes(), bool)
    row = Adw.ActionRow()
    row.set_subtitle(GLib.markup_escape_text("c < d", -1))
    sub = row.get_subtitle()
    if cf.subtitle_getter_decodes():
        assert "&lt;" not in sub and "<" in sub, (
            f"the probe said this build decodes, but a real row handed back "
            f"{sub!r} - it did not")
    else:
        assert "&lt;" in sub, (
            f"the probe said this build returns as set, but a real row handed "
            f"back {sub!r} - it escaped or decoded")
    del row


def test_half_a_convention_catches_tags_that_were_actually_consumed(
        force_decoding):
    """The only visible difference between a page that escaped and one that
    set the raw string on a decoding getter is CONSUMED characters. Measured
    on 1.5.0: set_subtitle("<b>evil</b> yes") - a page that forgot to escape -
    hands back `evil yes`, the tags eaten. On 1.9.4 the same raw set is kept
    as-is, so no real widget on that stack can model a consumed form; this
    control drives the helper with exactly the string the markup-acting
    builds produce, which is the form the decoded branch must catch."""
    with pytest.raises(AssertionError):
        cf.assert_subtitle_shown_as_text("evil yes", "<b>evil</b>",
                                         what="the consumed control")


def test_half_a_convention_catches_a_double_escape(force_decoding):
    """Two escaping layers survive a decoded getter as visible entity residue:
    `a &amp;amp; b` set returns `a &amp; b`, which the user reads as punctuation.
    The probe propagates the residue only if the helper asserts on it, because
    the `says` check reads the residue back as a bare ampersand and passes."""
    with pytest.raises(AssertionError):
        cf.assert_subtitle_shown_as_text(
            "a &amp; b",  # what set("a &amp;amp; b") hands back on 1.5.0
            "a & b", what="the double-escape control")


def test_the_decoding_convention_accepts_the_correct_output(force_decoding):
    """Correct output - one escaping layer - passes on a decoding getter,
    which hands the decoded presentation text back: measured on 1.5.0,
    set(GLib.markup_escape_text("c < d")) returns `c < d`."""
    cf.assert_subtitle_shown_as_text("c < d", "c < d", what="the decoded stack")


def test_the_as_set_convention_accepts_the_correct_output(force_as_set):
    """The same correct output passes on an as-set getter, which hands the
    escaped string back verbatim - measured on 1.9.4."""
    escaped = GLib.markup_escape_text("c < d", -1)
    cf.assert_subtitle_shown_as_text(escaped, "c < d",
                                     what="the as-set stack")


def test_as_set_catches_the_classic_raw_store(force_as_set):
    """On an as-set getter the *stored* form is directly checkable, so the raw
    set of a previous era's bug - the string stored unescaped, no tags
    stripped - is caught by `assert_escaped_not_markup` inside the helper."""
    with pytest.raises(AssertionError):
        cf.assert_subtitle_shown_as_text("<b>evil</b> yes", "<b>evil</b>",
                                         what="the unescaped stored control")


def test_no_widget_is_constructed_at_module_scope() -> None:
    """A module-level `Adw.ActionRow` probe segfaulted collection on Arch once
    (see `test_irqbalance_page.py`'s history). This is an AST gate over
    conftest.py, not a text grep - a grep would hit this file's own prose
    about the segfault, the same "a text gate cannot tell prose from
    behaviour" trap the repo has recorded twice - and it reads module scope
    only, so the probe inside the cached function is untouched."""
    import ast
    from pathlib import Path

    tree = ast.parse(Path(cf.__file__).read_text())
    offenders = []
    for node in tree.body:  # module scope only, not function bodies
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef
                      | ast.ClassDef | ast.ImportFrom):
            continue
        for sub in ast.walk(node):
            if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute):
                root = sub.func.value
                while isinstance(root, ast.Attribute):
                    root = root.value
                if isinstance(root, ast.Name) and root.id == "Adw":
                    offenders.append(ast.unparse(sub))
    assert not offenders, (
        f"conftest.py constructs widgets at module scope, which is the "
        f"segfault-on-collection class: {offenders}")
