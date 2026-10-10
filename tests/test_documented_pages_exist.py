"""AGENTS.md's gap table cites page ids, and the code is what proves them.

**This file exists because of a correction made 2026-10-10**, recorded in the
Known-issues entry of the same name. The gap table said `| Software RAID |
`mdadm` | none |` while `SECTIONS` had registered a `raid` page for a week — it
was written once in `a44a642` and never re-checked as the pages landed. Ten rows
claimed `none`, and a eleventh said "fwupd only" while `firmware.py` read the
thing itself.

The rows were corrected from each page's own `notebook.py` registration string.
**A prose correction is not a verified correction**, and this repo's whole
discipline is that a change nobody can re-check has not landed — so the claims
the corrected rows make are now checkable here on every run.

**What is checked, and what is not — read this before trusting the green:**

* Every `` `page-id` `` the table cites in its Cassini column must be registered
  in `SECTIONS`. A row that names a page which was renamed, removed or never
  existed is a doc asserting something false about the app, and this fails.
* The "N registered pages" count the correction note carries must equal the
  number actually in `SECTIONS`. Adding a page and not updating the count fires
  it, which is the smallest signal that the table needs a second look.

**What is deliberately NOT checked, because it cannot be.** The original defect
was a row claiming `none` for a subsystem that *had* a page — an **absence**. No
regex finds a citation that was never written, and any attempt to map subsystem
names to page ids mechanically would be a hand-kept list in the test, which is
the same rot wearing a different hat. So this gate proves the doc's positive
claims are true and cannot prove the doc is complete. The count check is the
partial substitute: it is the one thing that moves when pages land.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "src" / "shani_cassini" / "notebook.py"
AGENTS = Path(__file__).resolve().parent.parent / "AGENTS.md"

#: The table under the "Shipped-but-unrepresented" measurement. Bounded at both
#: ends so a stray backtick elsewhere in the file cannot be read as a citation.
_TABLE_START = "Shipped-but-unrepresented, checked against both sets"
_TABLE_END = "**Not gaps, despite looking like them:**"

#: A page id cited as `` (`raid`) `` or `` (`avahi`, "Service Discovery") `` — the
#: convention the 2026-10-10 correction adopted. Package names (`mdadm`,
#: `oath-toolkit`) are backticked too but never sit alone inside the Cassini
#: column's own parentheses, which is what separates a citation from a name.
_CITATION = re.compile(r"\(`(?P<page>[a-z0-9-]+)`")

#: "**58 pages are registered today**", the phrasing the correction note uses.
#: Deliberately specific: a bare `\*\*(\d+) pages\*\*` would also match
#: "**36 new tests**" the moment someone writes one, and a gate that fires on an
#: unrelated number is a gate everybody learns to ignore. The trailing words are
#: not pinned, so the sentence may be reworded without breaking the check — but
#: the digits must stay inside one bold run on one line.
_COUNT_CLAIM = re.compile(r"\*\*(\d+) pages are registered")


def _registered_pages() -> dict[str, str]:
    """{page id: title} from `SECTIONS`, read from the module rather than imported.

    Imported, `SECTIONS` needs every tab module to load, which needs GTK — and
    this gate is about the *registry*, not about the widgets. Parsing the AST
    keeps it runnable anywhere, and it reads the same source the app does.
    """
    tree = ast.parse(SRC.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not any(getattr(t, "id", None) == "SECTIONS" for t in node.targets):
            continue
        out: dict[str, str] = {}
        for section in node.value.elts:                  # (title, [subsections])
            for group in section.elts[1].elts:           # (title, [pages])
                for page in group.elts[1].elts:          # (Tab, id, title, icon, desc)
                    out[page.elts[1].value] = page.elts[2].value
        assert out, "no pages parsed - the shape of SECTIONS changed"
        return out
    raise AssertionError("SECTIONS not found in notebook.py")


def _table() -> str:
    text = AGENTS.read_text(encoding="utf-8")
    start = text.index(_TABLE_START)
    end = text.index(_TABLE_END, start)
    return text[start:end]


# --- the citations --------------------------------------------------------


def test_every_page_the_table_cites_is_registered():
    """A row naming a page the app does not have is a false claim about it.

    This is the check that catches the *next* variant of the original rot: a
    page renamed, removed or re-slugged, with the table still pointing at the
    old id and still reading as authoritative.
    """
    pages = _registered_pages()
    cited = {m.group("page") for m in _CITATION.finditer(_table())}
    assert cited, "no page ids parsed - the citation convention changed"
    missing = sorted(p for p in cited if p not in pages)
    assert not missing, (
        f"AGENTS.md's gap table cites pages that are not registered: "
        f"{missing}. Registered ids include: {sorted(pages)}")


def test_the_table_actually_cites_something():
    """The gate's own control, and the reason it is here rather than in the
    loop above.

    Without this, a regex that matched nothing would make the previous test
    pass by inspecting an empty set — the exact "an absence" this repo keeps
    finding, here aimed at the doc rather than the page.
    """
    assert len(_CITATION.findall(_table())) >= 9, (
        "the gap table no longer cites the page ids it was corrected to cite")


# --- the count ------------------------------------------------------------


def test_the_registered_page_count_matches_the_claim():
    """The claim CI can actually re-check when a page lands.

    Not a completeness check (see the module docstring), but it is the one
    number that moves on every registration, so the doc cannot silently drift
    a second time without a red line.
    """
    claims = _COUNT_CLAIM.findall(AGENTS.read_text(encoding="utf-8"))
    assert claims, "no page-count claim found - the correction note was edited"
    pages = _registered_pages()
    for claim in claims:
        assert int(claim) == len(pages), (
            f"AGENTS.md claims {claim} registered pages; notebook.py has "
            f"{len(pages)}. Update the claim, and re-read the gap table while "
            f"you are there.")


# --- what the gate cannot do, stated so nobody reads it as coverage -------


def test_the_gate_cannot_detect_a_row_that_claims_none():
    """Deliberately asserts the blind spot, so it is documented rather than
    assumed.

    The original defect was `| Software RAID | mdadm | none |` — a row with no
    citation at all, so the citation gate has nothing to bite on. This test
    feeds that exact row through the parser and proves it survives, which is
    the honest statement: **a row claiming `none` is invisible here.**
    """
    row = "| Software RAID | `mdadm` | none |"
    assert not _CITATION.search(row), (
        "the citation regex now matches a bare `none` row, which means it has "
        "broadened past page ids - check which package names it is now eating")
