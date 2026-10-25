"""Shared test fixtures for shani-cassini test suite."""

import html
import sys
import os
import re
import threading
from unittest.mock import MagicMock

import pytest
import gi

gi.require_version("Gtk", "4.0")

# Ensure src/ is on the path when running from repo root
repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
src_path = os.path.join(repo_root, "src")
if src_path not in sys.path:
    sys.path.insert(0, src_path)

# Establish the httpx2-backed `httpx` alias before any test module does
# `import httpx` — see shani_cassini/_httpx_compat.py.
import shani_cassini._httpx_compat  # noqa: E402,F401

# Mock external modules BEFORE test modules import them.
# shani_chronoa and shani_backup are not installed in this environment.
_mock_modules = {
    "shani_chronoa": MagicMock(),
    "shani_chronoa.config": MagicMock(),
    "shani_chronoa.config.ChronoaConfig": MagicMock(),
    "shani_chronoa.config.HardwareProfile": MagicMock(),
    "shani_backup": MagicMock(),
    "shani_backup.config": MagicMock(),
    "shani_backup.config.BackupConfig": MagicMock(),
}
for _name, _mock in _mock_modules.items():
    if _name not in sys.modules:
        sys.modules[_name] = _mock


@pytest.fixture(autouse=True)
def clear_keyring_entries():
    """Clear shani-cassini keyring entries before and after each test.

    Ensures tests don't leak credentials into the real keyring or
    interfere with each other via leftover keyring state.
    """
    _clear_shani_keyring()
    yield
    _clear_shani_keyring()


# A one-shot latch, not a status flag: without it the deadline in
# _delete_password_bounded is paid before every test instead of once.
_KEYRING_UNREACHABLE = False


def _delete_password_bounded(keyring, service, account, timeout=2.0):
    """Run one `delete_password` with a hard deadline; True if it returned.

    A thread is required rather than a `try/except`: keyring's SecretService
    backend asks the session keyring to unlock, then blocks in a D-Bus read
    waiting for a prompt nobody answers. Nothing is ever raised, so the handler
    that used to wrap this call could not catch it, and an autouse fixture that
    hangs blocks the whole suite at its first test.
    """

    def _run():
        try:
            keyring.delete_password(service, account)
        except Exception:
            pass

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    thread.join(timeout)
    return not thread.is_alive()


def _clear_shani_keyring():
    """Delete all shani-cassini entries from the real keyring if available."""
    global _KEYRING_UNREACHABLE
    if _KEYRING_UNREACHABLE:
        return
    try:
        import keyring
    except ImportError:
        return
    for account in ("credentials", "__keyring_probe__"):
        if not _delete_password_bounded(keyring, "shani-cassini", account):
            _KEYRING_UNREACHABLE = True
            return


@pytest.fixture
def app_state():
    """Provide a fresh AppState instance."""
    from shani_cassini.state import AppState

    return AppState()


@pytest.fixture
def auth_manager():
    """Provide a fresh AuthManager instance."""
    from shani_cassini.auth import AuthManager

    return AuthManager()


@pytest.fixture
def api_client(auth_manager):
    """Provide an APIClient with a test base URL."""
    from shani_cassini.api_client import APIClient

    client = APIClient(auth_manager, base_url="http://localhost:9999")
    return client


# --- simulating a machine a tool is not installed on ------------------------
#
# **`monkeypatch.setenv("PATH", <empty dir>)` works for a `/usr/bin` tool and
# silently fails for an sbin-only one.** Both halves matter, and the first version
# of this note got the second wrong by claiming it never works.
#
# `system_status._tool_path()` searches `shutil.which()` first and then
# `SBIN_DIRS` = (`/usr/sbin`, `/usr/local/sbin`) **absolutely**. Measured:
#
#   tool        in /usr/bin   in /usr/sbin   have_tool() with an empty PATH
#   podman      yes            no             False   <- hidden, as intended
#   ls          yes            no             False   <- hidden
#   smartctl    no             yes            **True**    <- still found
#   aa-status   no             yes            **True**    <- still found
#
# So a test that empties PATH is honest about `podman` and lies about
# `smartctl`, which is the same `/usr/sbin` trap `AGENTS.md` records for
# `smartctl` and `aa-status`. That silence is the problem: the fixture reads as
# "this machine has neither tool", the branch is not taken, and nothing says why.
#
# The fixtures below patch `have_tool`/`have`/`tool_path_or_self` **and** point
# `SBIN_DIRS` at an empty directory, so "absent" means absent on every path the
# resolver can take. `SBIN_DIRS` is a module constant precisely so a test can do
# this - `_tool_path`'s own docstring says so.
#
# `tests/test_absent_tool_fixtures.py` holds the controls, including the
# measurement table above, so neither half of this note can rot unnoticed. (They
# live in a collected test module rather than here because pytest does not
# collect tests from `conftest.py`.)

@pytest.fixture
def absent_tools(monkeypatch, tmp_path):
    """Every tool is absent, on every path the resolver searches.

    Returns the list of tool names asked about, so a test can assert the page
    asked for the one it cares about - which is how you tell "took the absent
    branch" apart from "never looked", the absence this repo keeps being bitten
    by.
    """
    from shani_cassini import system_status as ss
    asked: list[str] = []

    def no_tool(cmd: str) -> bool:
        asked.append(cmd)
        return False

    monkeypatch.setattr(ss, "have_tool", no_tool)
    monkeypatch.setattr(ss, "have", no_tool)
    # An absent tool is still executed, per tool_path_or_self's own contract, so
    # a page's argv carries the bare name and the tool's error is what reports.
    monkeypatch.setattr(ss, "tool_path_or_self", lambda cmd: cmd)
    monkeypatch.setattr(ss, "_tool_path", lambda cmd: None)
    # and the sbin fallback, which is an absolute search PATH cannot influence
    monkeypatch.setattr(ss, "SBIN_DIRS", (str(tmp_path / "empty-sbin"),))
    return asked


@pytest.fixture
def one_tool_absent(monkeypatch, tmp_path):
    """Factory: mark specific tools absent, leave every other one findable.

    The common case is "podman is here, distrobox is not" - a machine with one of
    two tools - which neither an emptied PATH nor `absent_tools` can express.
    Call with no names to restore the machine.
    """
    from shani_cassini import system_status as ss
    real = ss._tool_path
    absent: set[str] = set()

    def make(*names: str):
        absent.clear()
        absent.update(names)
        return absent

    def have_tool(cmd: str) -> bool:
        return cmd not in absent

    monkeypatch.setattr(ss, "have_tool", have_tool)
    monkeypatch.setattr(ss, "have", have_tool)
    monkeypatch.setattr(ss, "_tool_path",
                        lambda cmd: None if cmd in absent else real(cmd))
    monkeypatch.setattr(ss, "SBIN_DIRS", (str(tmp_path / "empty-sbin"),))
    return make


@pytest.fixture
def empty_sbin(monkeypatch, tmp_path):
    """`have_tool()` finds nothing in the sbin fallback directories.

    Use this **alongside** `monkeypatch.setenv("PATH", <empty dir>)` when the
    tool being faked away is an sbin-only one - `smartctl`, `aa-status`,
    `fprintd`. Emptying PATH alone does not hide those: `_tool_path()` falls back
    to `SBIN_DIRS` absolutely, so the tool stays findable and the test's premise
    is false while reading true.

    Prefer `absent_tools`/`one_tool_absent` for new tests; this exists for the
    ones that already empty PATH and only need the second half of the fix.
    `tests/test_absent_tool_fixtures.py` holds the measurement.
    """
    from shani_cassini import system_status as ss
    empty = tmp_path / "no-sbin"
    empty.mkdir(exist_ok=True)
    monkeypatch.setattr(ss, "SBIN_DIRS", (str(empty),))
    return empty


# ============================================================================
# What "escaped, not markup" means on this libadwaita
# ============================================================================
#
# **Eleven tests were asserting the wrong thing**, and the fix is not to stop
# escaping. Measured on libadwaita 1.9.1:
#
#   * `Adw.ActionRow` has a `use-markup` property and **it defaults to True**,
#     so a title IS Pango markup and a title containing `<b>` renders bold.
#   * `get_title()` returns the string exactly as it was set - it does not
#     unescape anything.
#
# So the old assertion, `assert "<b>evil</b>" in row.get_title()`, was asserting
# that a hostile filename survives into the title **unescaped** - which is the
# bug, not the goal. It passed on an older libadwaita where an unescaped `&`
# blanked the whole row, so a blank row and a hostile row were told apart by
# their damage. On 1.9 that distinction is gone and the assertion only proves
# the escaping was removed.
#
# The property that actually matters is "Pango finds no tag in this string", and
# it is version-independent: strip the escape sequences, then assert no `<` or
# `&` is left. `renders_literally` below is that check, and
# `assert_escaped_not_markup` is what the tests should call.
#
# What this does NOT weaken: a hostile string still reaches the screen as
# readable text with no tag interpreted. That is the user-visible guarantee, and
# it is now asserted directly instead of inferred from a blank row.

_ENTITY_RE = re.compile(r"&(?:lt|gt|amp|quot|apos|#\d+|#x[0-9A-Fa-f]+);")


def pango_finds_a_tag(text: str) -> bool:
    """Would Pango find a markup tag in `text`? The security-relevant question.

    Escape sequences are removed first, because they are the *only* legitimate
    way for a `<` to appear in a title: `&lt;` is a literal `<`, not a tag
    opener. Anything left over is markup Pango would act on.
    """
    stripped = _ENTITY_RE.sub("", text or "")
    return "<" in stripped or "&" in stripped


def renders_literally(text: str) -> bool:
    """True when Pango will show `text` exactly as written, with no tag acted on."""
    return not pango_finds_a_tag(text)


def assert_escaped_not_markup(value: str, *, what: str = "the string") -> None:
    """The assertion the eleven tests should have been making all along."""
    assert renders_literally(value), (
        f"{what} would be interpreted as markup rather than shown literally: "
        f"{value!r}")


def literal_text(value: str) -> str:
    """`value` with Pango escape sequences turned back into their characters.

    For assertions about what a user READS. `get_title()` returns the string as
    it was set, and the pages set the ESCAPED form, so a test that searches for
    the raw filename finds nothing and concludes the escaping was removed - when
    in fact the escaping is what makes the filename visible as text at all.

    This is a test-reading helper, not something the app should use: unescaping
    before handing a string back to Pango would be the very bug these tests
    exist to catch. Python's `html.unescape` does the same job as Pango's
    entities (`&lt; &gt; &amp; &quot; &apos;` and numeric forms) and is not
    reimplemented here.
    """
    return html.unescape(value or "")


def says(haystack: str, needle: str) -> bool:
    """Does `haystack`, as a reader sees it, contain `needle`?

    The replacement for `assert needle in row.get_title()`, which broke when the
    pages began escaping properly. Every one of those assertions was asking
    "can the user still read this?" and comparing against the wrong form of the
    string to ask it.
    """
    return needle in literal_text(haystack)


# ============================================================================
# get_subtitle() is stack-dependent; the escaping property is not
# ============================================================================
#
# `renders_literally` / `assert_escaped_not_markup` above inspect the string
# they are handed, and the *subtitle* getter hands different strings on
# different libadwaita builds. Measured same input, both stacks:
#
# | what was set (the pages always escape) | get_subtitle() on 1.5.0 | on 1.9.4 |
# |---|---|---|
# | `"c &lt; d"` | `'c < d'` — the **decoded** presentation text | `'c &lt; d'` — **as set** |
#
# (1.5.0 probed 2026-10-25 on the CI stack — libadwaita 1.5.0 / GTK 4.14.5,
# `get_title()` returns the string as set on both stacks, it is only the
# subtitle getter that differs. On an escaped subtitle with a hostile
# `<b>…</b>` in it, 1.5.0's decoded return keeps the tag characters as
# literal text, which is exactly the guarantee escaping buys: a tag that had
# been *acted on* would have consumed its characters.)
#
# So `assert_escaped_not_markup(row.get_subtitle())` asserts on the plain form
# a 1.5.0 getter hands back and fails there while passing on Shanios - the
# twelve CI failures of 2026-10-13..25. `assert_subtitle_shown_as_text` below
# asks, with its own probe, which convention this build uses, and then asserts
# the property that build can testify to. It is deliberately a **cached
# function**, not a module-level widget: a module-level probe segfaulted the
# suite during collection on Arch (see `test_irqbalance_page.py`'s history).


_SUBTITLE_GETTER_DECODES: bool | None = None


def subtitle_getter_decodes() -> bool:
    """Does THIS libadwaita's subtitle getter decode markup before handing it back?

    Measured with a probe row on first call, cached thereafter - never a
    module-level widget, for the segfault reason above. The probe row carries a
    marker only pages would escape deliberately, so the two conventions cannot
    answer alike: an as-set getter hands back `&lt;`, a decoding one hands back
    `<`.
    """
    global _SUBTITLE_GETTER_DECODES
    if _SUBTITLE_GETTER_DECODES is None:
        gi.require_version("Adw", "1")
        from gi.repository import Adw  # noqa: PLC0415 - display-bound import

        row = Adw.ActionRow(title="t &lt;b&gt; &amp; t",
                            subtitle="s &lt;b&gt; &amp; s")
        _SUBTITLE_GETTER_DECODES = "&lt;" not in (row.get_subtitle() or "")
    return _SUBTITLE_GETTER_DECODES


def assert_subtitle_shown_as_text(subtitle: str, hostile: str, *,
                                  what: str = "the string") -> None:
    """The escaped subtitle's user-visible guarantee, on either getter convention.

    The property the pages owe the user is one: a hostile string reaches the
    screen as text, its tag characters intact, no tag acted on. The two getter
    conventions just testify to it differently:

    - **as-set getter** (1.9.4, Shanios): the escaped form is what came back,
      so `assert_escaped_not_markup` is directly checkable - and `says` then
      re-decodes it to prove the hostile characters were escaped, not dropped
      (a double-escape would survive the first check and fail the second).
    - **decoding getter** (1.5.0, CI): the getter returns the text it would
      *show*. A tag acted on would have consumed its characters, so the
      hostile text surviving verbatim in the plain form is the one proof a
      plain-form getter can still give - and it is the user-visible guarantee
      itself, not a weaker stand-in. This branch also asserts **no entity
      survives**: a getter that decodes eats exactly one escaping layer, so a
      page that escaped twice would leave `&amp;` visible on screen as
      punctuation - and `says` alone would read that residue back as a bare
      `&` and pass it.

    `mock-as-set` / `mock-decoded` controls for this helper live in
    `tests/test_conftest_helpers.py`, which drives it both ways.
    """
    if not subtitle_getter_decodes():
        assert_escaped_not_markup(subtitle, what=what)
    if not says(subtitle, hostile):
        raise AssertionError(
            f"{what}: the hostile text did not survive to the screen. "
            f"{hostile!r} does not read back from a subtitle getter returning "
            f"{subtitle!r} - markup was acted on (or escaped twice), not shown")
    if subtitle_getter_decodes() and _ENTITY_RE.search(subtitle):
        raise AssertionError(
            f"{what}: this getter decodes, so no entity should be left in "
            f"{subtitle!r} - one decode layer already happened, and a "
            f"remaining entity means the page escaped twice (or the page "
            f"wrote an entity of its own, which a use-markup row renders as "
            f"the entity's characters, not as text)")
