"""Every `suggested-action` button in this app looks like the others.

**Found by rendering the Remote Access page (2026-10-17).** Its per-directive
Save buttons carried `.suggested-action` **and** `.flat`:

```python
save = Gtk.Button(label="Save", valign=Gtk.Align.CENTER)
save.add_css_class("suggested-action")
save.add_css_class("flat")
```

`.flat` removes the fill that `suggested-action` is supposed to supply, so Save
rendered as **bare orange text with no button chrome** — while the same class
everywhere else ("Add a rule…", "Open firewall-config", "Export a directory…",
"Stage MOK Enrollment") renders as a filled pill. Two Save buttons on adjacent
pages that look nothing alike.

It also destroyed the **disabled** state. A flat button has almost nothing to
dim, so "Save is greyed because you have not changed anything" was not visibly
different from "Save is a label". That matters here specifically: this page
*disables* Save until the chosen value differs from the recorded one, so the
grey is the only thing telling a reader the button exists and is not available.

**Why the gate is app-wide rather than one page.** `flat` was the **only**
occurrence in `src/shani_cassini/` — measured, one hit — so this was never a
convention, it was one outlier. A gate on Remote Access would have missed the
next page that does the same thing, and the class of fault is "this button is
styled differently from its siblings", which is only visible across the app.
"""

from __future__ import annotations

from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "src" / "shani_cassini"


def _buttons_with(source: str):
    """Yield (path, lineno) for every `add_css_class("<name>")` call in a file."""
    import re
    for number, line in enumerate(source.splitlines(), 1):
        for match in re.finditer(r'add_css_class\(\s*"([^"]+)"\s*\)', line):
            yield number, match.group(1)


class TestNoButtonIsStyledAwayFromItsSiblings:
    def test_flat_is_never_combined_with_suggested_action(self):
        """The combination that turned a button into a label.

        Checked **per button**, not per file: the class lists are gathered
        inside the `add_css_class` call they came from, so two buttons in one
        file — one flat, one not — are not conflated into "the file mentions
        flat".
        """
        offenders = []
        for path in sorted(SRC.rglob("*.py")):
            source = path.read_text(encoding="utf-8")
            for number, css_class in _buttons_with(source):
                if css_class != "flat":
                    continue
                # Walk back to the start of this widget's construction and look
                # at the whole class list, not just this line: `flat` and
                # `suggested-action` are added on separate lines.
                start = max(0, source[:source.index("\n", 0)].count("\n") - 1)
                window = "\n".join(source.splitlines()[max(0, number - 6):number])
                if "suggested-action" in window:
                    offenders.append(f"{path.name}:{number}")
        assert not offenders, (
            "these buttons add both `suggested-action` and `flat`, which cancels "
            "the fill and leaves orange text with no chrome and no visible "
            "disabled state: " + ", ".join(offenders))

    def test_flat_is_not_used_at_all(self):
        """Stronger than the combination, and the reason that one can be.

        `flat` had exactly **one** occurrence in the whole package, so it was
        never a convention. If a future page genuinely needs a flat button this
        gate should be replaced by the one above rather than quietly relaxed -
        which is why this test says so in its message rather than just failing.
        """
        offenders = []
        for path in sorted(SRC.rglob("*.py")):
            for number, css_class in _buttons_with(
                    path.read_text(encoding="utf-8")):
                if css_class == "flat":
                    offenders.append(f"{path.name}:{number}")
        assert not offenders, (
            "`flat` is used here: " + ", ".join(offenders) + ". If a button "
            "genuinely needs a flat treatment, delete this test and keep the "
            "one that forbids combining it with `suggested-action` - do not "
            "relax that one, it is the one with the reason.")

    def test_the_check_can_see_a_flat_suggested_button(self):
        """The control: source shaped exactly like the defect."""
        source = (
            'save = Gtk.Button(label="Save", valign=Gtk.Align.CENTER)\n'
            'save.add_css_class("suggested-action")\n'
            'save.add_css_class("flat")\n'
        )
        found = [css for _n, css in _buttons_with(source)]
        assert "flat" in found
        window = "\n".join(source.splitlines()[:2])
        assert "suggested-action" in window, (
            "the combination test looks back over the preceding lines for the "
            "other class; it cannot see a pairing it does not look for")

    def test_a_lone_flat_is_still_seen_by_the_wider_gate(self):
        """The two gates are not redundant, and this is why."""
        flat_only = 'b.add_css_class("flat")\n'
        assert [c for _n, c in _buttons_with(flat_only)] == ["flat"]

        plain = 'b.add_css_class("suggested-action")\n'
        assert [c for _n, c in _buttons_with(plain)] == ["suggested-action"]