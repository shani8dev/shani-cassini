"""A row that was given text must not end up showing none - on EITHER stack.

**Why this exists, and why it is two checks and not one.** An `Adw.ActionRow`
title and subtitle are Pango markup, so a raw `&`, `<` or `>` breaks the row.
*Where the breakage shows depends on the libadwaita version*, which is the whole
reason this repo's escaping tests pass on CI and fail on the distribution the app
actually ships on. Measured, same three inputs, two stacks:

    set "a & b"      libadwaita 1.5.0  -> get_subtitle() == ''   label blank
                     libadwaita 1.9.4  -> get_subtitle() == 'a & b'  label BLANK
    set "x < y"      libadwaita 1.5.0  -> get_subtitle() == ''   label blank
    set "a &amp; b"  both             -> fine

So on 1.5 the getter empties, and on 1.9.4 the getter is untouched and the
**label** is what goes blank. A test that detects this through `get_subtitle()`
works on one stack and cannot work on the other - and the failure mode it causes
is a confident green on CI about a page that is blank for the user on Arch.

Two checks, because only one of them is portable:

  * `LBLANK` - the label is empty while the getter has text. This is the 1.9.4
    symptom and it is the one that matters for the shipped distribution. It is
    silent on 1.5, where the getter is empty too and there is nothing left to
    compare against.
  * `NOTITLE` - a row with no title at all. A title is mandatory, so this is
    always wrong, on every version.

**What this gate cannot do, stated rather than implied.** On libadwaita 1.5 a
subtitle destroyed by markup is indistinguishable from a subtitle that was never
set: both come back as `''`. Nothing observable from the widget tells them
apart. So the 1.5 half of this class is not detectable here, and a green run of
this test on CI is not evidence that no page has the bug - only that no page has
the version of it that leaves a trace. The per-page escaping tests remain the
coverage for that, and they need to assert on the *rendered label*, not the
getter, before they mean anything on both.

The control at the bottom is what keeps the `LBLANK` check from being a
tautology: it has to actually fire on the stack that has the symptom, and says
so when the stack does not.
"""

from __future__ import annotations

import re
import sys

import pytest

gi = pytest.importorskip("gi")
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: E402

Adw.init()

from shani_cassini.notebook import SECTIONS  # noqa: E402

# 1.9.4 returns what it was given; 1.5 normalises markup back to plain text.
GETTERS_STORE_VERBATIM = bool(
    Adw.ActionRow(title="t", subtitle="a &amp; b").get_subtitle() == "a &amp; b"
)


def _walk(widget, out: list) -> list:
    out.append(widget)
    child = widget.get_first_child() if isinstance(widget, Gtk.Widget) else None
    while child is not None:
        _walk(child, out)
        child = child.get_next_sibling()
    return out


def _rendered_text(row) -> str:
    """Every word the row actually put on screen, title and subtitle together.

    Deliberately not "the subtitle's label". libadwaita builds a row out of
    several labels and there is no supported way to ask which one holds the
    subtitle, so the first version of this helper returned the TITLE's label -
    which is never empty, which made the check unable to fail. Joining all of
    them sidesteps the question, and the caller compares words rather than
    strings so an entity difference between getter and label cannot matter.
    """
    words = []
    for node in _walk(row, []):
        if isinstance(node, Gtk.Label) and node.get_text():
            words.extend(node.get_text().split())
    return " ".join(words)


def _squash(text: str) -> str:
    """The text with entities decoded and all whitespace removed.

    Two reasons. Entities, because one stack's getter hands back `&amp;` where
    the other's hands back `&` and this must not care which. Whitespace,
    because the comparison is a substring test over `Gtk.Label.get_text()`,
    which re-wraps freely - and because the first version of this helper
    compared *words* filtered to length >= 3, so the control string "a & b" had
    no qualifying word at all, `_words` returned the empty set, and the check
    could never pass. A substring test has no such hole: empty in, empty out,
    and the caller skips empty subtitles anyway.
    """
    plain = (text.replace("&amp;", "&").replace("&lt;", "<")
                 .replace("&gt;", ">").replace("&quot;", '"')
                 .replace("&apos;", "'"))
    return "".join(plain.split())


class TestTheGateCanSee:
    def test_the_control_reports_the_symptom_this_stack_has(self):
        """Negative control, version-aware.

        On 1.9.4 a raw ampersand must blank the label while the getter keeps the
        text - that is `LBLANK`. On 1.5 the getter empties instead, so there is
        nothing to compare and the gate is honestly blind; this says so out loud
        rather than passing as if it had checked something.
        """
        row = Adw.ActionRow(title="Value", subtitle="a & b")
        getter = row.get_subtitle() or ""
        rendered = _rendered_text(row)
        # The shape the page sweep looks for, computed the same way.
        flagged = bool(_squash(getter)) and _squash(getter) not in _squash(rendered)
        if _squash(getter) and _squash(getter) not in _squash(rendered):
            assert GETTERS_STORE_VERBATIM, (
                "the label blanked while the getter had text, but this stack "
                "normalises markup - so the version probe above is wrong and "
                "the gate is looking for the wrong shape")
            assert flagged, (
                "the symptom is present but the sweep's own expression did not "
                "reproduce it, so the gate cannot detect this case")
            return
        assert not getter, (
            f"expected this stack to empty the getter for a raw ampersand, got "
            f"{getter!r}; if the behaviour moved again, update GETTERS_STORE_"
            f"VERBATIM and this control together")
        assert not flagged, (
            "on a stack that empties the getter the sweep has nothing to "
            "compare, so this gate is BLIND here - which is true and is why "
            "the per-page escaping tests still have to assert on the rendered "
            "label rather than the getter")

    def test_an_escaped_ampersand_renders_and_is_not_flagged(self):
        row = Adw.ActionRow(title="Value", subtitle="a &amp; b")
        getter = row.get_subtitle() or ""
        assert getter.strip(), "the control row is empty"
        assert _squash(getter) and _squash(getter) in _squash(_rendered_text(row)), (
            f"an escaped ampersand must render as text on every stack; the row "
            f"show {_rendered_text(row)!r} for a subtitle of {getter!r}")


class TestEveryPage:
    @pytest.mark.parametrize(
        "cls,pid",
        [(p[0], p[1]) for _g, subs in SECTIONS for _s, pages in subs
         for p in pages],
        ids=[p[1] for _g, subs in SECTIONS for _s, pages in subs for p in pages],
    )
    def test_no_row_shows_nothing_while_its_getter_has_text(
            self, cls, pid) -> None:
        tab = cls()
        blanked, untitled = [], []
        for node in _walk(tab, []):
            if not isinstance(node, Adw.ActionRow):
                continue
            if not (node.get_title() or "").strip():
                untitled.append("row built with no title at all")
                continue
            subtitle = node.get_subtitle() or ""
            wanted = _squash(subtitle)
            if wanted and wanted not in _squash(_rendered_text(node)):
                blanked.append(
                    f"subtitle {subtitle!r} is in the row but none of its words "
                    f"reached the screen")
        assert not blanked, f"{pid}: " + "; ".join(blanked[:4])
        assert not untitled, f"{pid}: " + "; ".join(untitled[:4])

#: Paired single-asterisk italics only — `*word*`, never a lone `*`. A page's
#: prose is free to use a bare asterisk (glob patterns, arithmetic), so a naive
#: search for `*` would be a gate that always fires and therefore always gets
#: ignored. This is the same expression `tests/test_setup_page.py` uses.
_PAIRED_ITALIC = re.compile(r"(?<!\*)\*(?!\s)(?:[^\*\n]{1,40})\*(?!\*)")

#: Emphasis markers, in the two forms a Markdown-shaped habit produces. `_` is
#: not checked on its own: it is a legitimate character in file paths, option
#: names and shell fragments, several of which appear in these pages' prose.
_EMPHASIS = ("**", "__")


def _module_notes(tab_cls) -> list[str]:
    """Every module-level string constant on a page, i.e. its note prose.

    Read off the module rather than the widget tree so a page whose rows only
    appear after an async read is still covered.

    **Dunders are excluded, and the first version did not.** `getmembers`
    returns `__doc__`, `__file__` and `__name__` alongside the module's own
    constants, and every page's `__doc__` is a long Markdown document - so
    `len(value) > 40` alone matched the documentation of the very thing the gate
    forbids, and **59 of 59 pages failed on their own prose**. That is this
    file's documented "a text gate cannot tell prose from behaviour" trap, hit by
    the gate written to avoid it.

    Still not perfect, and the residual is stated rather than hidden: a note
    built by concatenating or `.format()` is invisible here. The widget-tree walk
    is what covers those, and it is why both halves run.
    """
    import inspect
    out = []
    for name, value in inspect.getmembers(sys.modules[tab_cls.__module__]):
        if name.startswith("__"):
            continue
        if isinstance(value, str) and len(value) > 40:
            out.append(value)
    return out


class TestNoPageShowsMarkdownToALabel:
    """Every page, not just the one that was caught.

    **`AdwActionRow`'s title/subtitle/description and `AdwPreferencesGroup`'s
    description are plain labels — Cassini does not parse markdown.** So a note
    written with `**emphasis**` is shown with the asterisks on screen, exactly
    as typed.

    `tests/test_setup_page.py` already holds this gate for the Setup page, after
    a render found its five notes shipping punctuation instead of emphasis. That
    fix was local, and **the same habit was still live on another page the week
    the sweep was run**: App Versions put `**version**` and `**channel**` into a
    Snap group's description and the render showed both pairs of asterisks. A
    gate on one page is a gate on one page, so this one walks **every** page
    registered in `SECTIONS`.

    Read off the **built widget tree**, not the source. A grep for `**` over a
    module fires on its own docstring — every page in this repo documents itself
    in Markdown — which is the "a text gate cannot tell prose from behaviour"
    trap documented twice above, and it would pass while the screen still showed
    asterisks.
    """

    @staticmethod
    def _walk(widget, out: list, depth: int = 0) -> list:
        assert depth < 40, "widget tree deeper than 40 - a cycle, not a page"
        out.append(widget)
        child = widget.get_first_child()
        while child is not None:
            TestNoPageShowsMarkdownToALabel._walk(child, out, depth + 1)
            child = child.get_next_sibling()
        return out

    def _visible_text(self, page) -> list[str]:
        found = []
        for widget in self._walk(page, []):
            for getter in ("get_title", "get_subtitle", "get_description"):
                if hasattr(widget, getter):
                    value = getattr(widget, getter)()
                    if value:
                        found.append(value)
        return found

    @pytest.mark.parametrize(
        "cls,pid",
        [(p[0], p[1]) for _g, subs in SECTIONS for _s, pages in subs
         for p in pages],
        ids=[p[1] for _g, subs in SECTIONS for _s, pages in subs for p in pages],
    )
    def test_no_visible_string_carries_markdown_markers(self, cls, pid) -> None:
        seen = self._visible_text(cls())

        # **The note constants are checked on every page, including ones whose
        # rows only arrive from an async read.** `drivers` and `secureboot` build
        # no rows in `__init__`, so a walk of the constructed page finds no text
        # at all — and the first version of this gate asserted that it had, which
        # failed those two for the right-looking wrong reason. A gate that can
        # only see what happens to be built by the time it runs is a gate that
        # skips pages silently, which is the absence-shaped failure this file
        # documents. So the module's `*_NOTE` constants are read directly: they
        # are what the render showed, they exist on every page that has notes,
        # and reading them needs no widget tree.
        notes = _module_notes(cls)
        if not seen and not notes:
            # **Named, not skipped silently.** `drivers` and `secureboot` build
            # every row from an async read, so a constructed page has no text and
            # the modules declare no note constants: there is genuinely nothing
            # for this gate to look at. Asserting they had text would be
            # asserting something untrue; skipping them quietly would be the
            # absence-shaped failure this file documents twice. So the fact is
            # stated, and if either page ever gains a build-time string the gate
            # starts covering it with no edit here.
            pytest.skip(
                f"{pid}: builds every row from an async read and declares no "
                f"note constant, so this gate has nothing to inspect")

        for t in notes:
            if any(m in t for m in _EMPHASIS) or _PAIRED_ITALIC.search(t):
                seen.append(f"[{pid} module note] {t}")

        bold = [t for t in seen if any(m in t for m in _EMPHASIS)]
        assert not bold, (
            f"{pid}: shown literally, markers and all: "
            + "; ".join(repr(t[:80]) for t in bold[:4]))

        italics = [t for t in seen if _PAIRED_ITALIC.search(t)]
        assert not italics, (
            f"{pid}: italic markers shown literally: "
            + "; ".join(repr(t[:80]) for t in italics[:4]))

    def test_the_check_can_see_a_marker(self) -> None:
        """The control: a check that cannot fail is not a check."""
        assert _PAIRED_ITALIC.search("a *bold* claim")
        assert not _PAIRED_ITALIC.search("a * lone asterisk")
        assert "**" in "a **bold** claim"
