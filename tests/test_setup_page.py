"""The Setup page: provisioning state for the account you are logged in as.

**What this page is, and what it deliberately is not.** Shanios installs no
account: `os-installer-config/config.yaml` sets `skip_user: yes`, so the
installer's user page never renders and `configure.sh`'s `useradd` block is
never reached. The first account is created at first boot by the desktop's
wizard. A factory reset (`shani-reset`) then deletes the `/etc` overlay upper
layer — which holds `/etc/passwd` *and* `/etc/shadow` — so every account goes,
including the root password set at install time, while files in `@home`
survive.

**The design constraint that shaped the page, and the mistake it corrected.**
Cassini is an `Adw.Application`: it needs an authenticated graphical session,
and even its background agent is ordered `After=graphical-session.target`
because notifications need the session's bus. So on a machine with no account
**nothing in Cassini runs at all** — a row reading "no account can log in"
could never be read by the person it was meant to warn. An earlier version of
this page had exactly that row; it was decoration aimed at an unobservable
state, and `test_the_page_does_not_warn_about_a_state_it_cannot_observe` holds
it gone. Recovery belongs to the boot layer and is pinned by
`shani-testbed/slot-tests/post-reset-setup.sh` instead.

So the page answers the question a logged-in user can actually act on: **has
the provisioning step reached this account?** `useradd -m` copies `/etc/skel`
only when it *creates* a home, so a home predating its account — exactly what a
reset leaves — received none of the defaults, and nothing reported it until now.

**Fixtures.** `PASSWD` is shaped like a real `/etc/passwd` (root, two system
accounts, one `nologin` service account, one regular user) rather than a
two-line invention, because the UID window and the nologin skip are the whole
of the parser's behaviour and a friendly fixture would pass against a parser
that had neither.
"""

from __future__ import annotations

import ast
import re
import inspect
import pathlib
import textwrap

import pytest

from gi.repository import Adw, Gtk  # noqa: E402

from shani_cassini import system_status as ss  # noqa: E402
from shani_cassini.tabs import setup as setup_mod  # noqa: E402
from shani_cassini.tabs.setup import SetupTab  # noqa: E402

PASSWD = textwrap.dedent("""\
    root:x:0:0:root:/root:/bin/bash
    bin:x:1:1:bin:/bin:/usr/sbin/nologin
    daemon:x:2:2:daemon:/usr/sbin:/usr/sbin/nologin
    mail:x:8:8:mail:/var/spool/mail:/usr/bin/nologin
    systemd-network:x:100:102:systemd Network Manager:/run/systemd:/usr/bin/nologin
    shaniprobe:x:1000:1000:Shani Probe:/home/shaniprobe:/bin/zsh
    shanib:x:1001:1001:Shani B:/home/shanib:/usr/bin/fish
""")

FLATPAK_LIST = textwrap.dedent("""\
    org.gnome.Calendar\t48.1
    org.gnome.TextEditor\t48.0
    com.spotify.Client\t1.2.76.482.g0944
""")


# ── Seam ─────────────────────────────────────────────────────────────────────
# The seam is `SetupTab.load`, not the readers below. Patching a reader would
# also silence the reader tests, which are the ones that must exercise the real
# parse.
# Paired single-asterisk italics only: `*word*`, never a lone `*`, which the
# notes are free to use.
_PAIRED_ITALIC = re.compile(r"(?<!\*)\*(?!\s)(?:[^\*\n]{1,40})\*(?!\*)")


@pytest.fixture
def no_autoload(monkeypatch):
    monkeypatch.setattr(SetupTab, "load", lambda self: False)


@pytest.fixture
def tab(no_autoload):
    return SetupTab()


def _subtitle(page, title):
    """The subtitle of the row with this exact title, read off the widget tree."""
    for row in _rows(page):
        if row.get_title() == title:
            return row.get_subtitle()
    raise AssertionError(f"no row titled {title!r}")


def _rows(page):
    out = []

    def walk(widget, depth=0):
        assert depth < 40, "widget tree deeper than 40 — a cycle, not a page"
        if isinstance(widget, Adw.ActionRow):
            out.append(widget)
        child = widget.get_first_child()
        while child is not None:
            walk(child, depth + 1)
            child = child.get_next_sibling()

    walk(page)
    return out


# ══ The passwd parser ════════════════════════════════════════════════════════
class TestPasswdAccounts:
    def test_a_regular_user_is_found(self):
        got = ss.parse_passwd_accounts(PASSWD)
        assert [a["name"] for a in got] == ["shaniprobe", "shanib"]

    def test_system_accounts_are_excluded_by_uid(self):
        got = ss.parse_passwd_accounts(PASSWD)
        # 0, 1, 2, 8 and 100 are all below the first regular UID (1000).
        assert all(a["uid"] >= 1000 for a in got)

    def test_a_nologin_service_account_is_excluded(self):
        got = ss.parse_passwd_accounts(PASSWD)
        # mail is uid 8 so the UID filter already drops it; this pins that the
        # shell filter is real rather than incidentally redundant.
        text = "svc:x:1500:1500:svc:/var/lib/svc:/usr/sbin/nologin\n"
        assert ss.parse_passwd_accounts(text) == []
        assert [a["name"] for a in ss.parse_passwd_accounts(
            text.replace("nologin", "bash"))] == ["svc"]

    def test_the_home_and_shell_are_carried_through(self):
        got = ss.parse_passwd_accounts(PASSWD)
        by_name = {a["name"]: a for a in got}
        assert by_name["shaniprobe"]["home"] == "/home/shaniprobe"
        assert by_name["shanib"]["shell"] == "/usr/bin/fish"

    def test_an_unreadable_passwd_is_none_and_not_an_empty_list(self):
        """The distinction the whole page rests on.

        None means "nobody could tell". [] means "told, and there are none".
        Collapsing them would let a read failure render as "no account can log
        in" — a false alarm about the one row that must not cry wolf.
        """
        assert ss.parse_passwd_accounts(None) is None
        assert ss.parse_passwd_accounts("") == []

    def test_malformed_lines_are_skipped_not_fatal(self):
        text = "truncated:line\n" + PASSWD + "x:y:notanumber:1:1:g:/h:/bin/bash\n"
        got = ss.parse_passwd_accounts(text)
        assert [a["name"] for a in got] == ["shaniprobe", "shanib"]

    def test_comments_and_blank_lines_are_ignored(self):
        text = "# a comment\n\n   \n" + PASSWD
        assert len(ss.parse_passwd_accounts(text)) == 2


# ══ The flatpak parser ══════════════════════════════════════════════════════
class TestFlatpakApps:
    def test_tab_separated_columns_are_split(self):
        got = ss.parse_flatpak_apps(FLATPAK_LIST)
        assert got[0] == {"app": "org.gnome.Calendar", "version": "48.1"}

    def test_a_row_with_no_version_still_yields_the_app(self):
        got = ss.parse_flatpak_apps("org.gnome.Calendar")
        assert got == [{"app": "org.gnome.Calendar", "version": ""}]

    def test_an_unreadable_list_is_none(self):
        assert ss.parse_flatpak_apps(None) is None
        assert ss.parse_flatpak_apps("") == []


# ══ Rendering ═══════════════════════════════════════════════════════════════
class TestThePage:
    def test_it_constructs_and_builds_its_groups(self, tab):
        assert isinstance(tab, Gtk.Box)

    def test_accounts_are_named(self, tab):
        tab._on_accounts({"passwd_readable": True,
                          "accounts": [{"name": "shaniprobe"},
                                       {"name": "shanib"}],
                          "profile": "gnome"}, "")
        assert _subtitle(tab, "Regular accounts") == "2: shaniprobe, shanib"

    def test_more_than_four_accounts_are_summarised_not_truncated_silently(self, tab):
        accounts = [{"name": f"u{i}"} for i in range(6)]
        tab._on_accounts({"passwd_readable": True, "accounts": accounts,
                          "profile": "gnome"}, "")
        sub = _subtitle(tab, "Regular accounts")
        assert "+2 more" in sub and "u0" in sub

    def test_an_unreadable_passwd_is_not_reported_as_no_accounts(self, tab):
        tab._on_accounts({"passwd_readable": False, "accounts": [],
                          "profile": "gnome"}, "")
        sub = _subtitle(tab, "Regular accounts")
        assert "Could not read" in sub
        assert "no account" not in sub.lower()

    def test_the_page_does_not_warn_about_a_state_it_cannot_observe(self, tab):
        """The row that was removed, held removed.

        Cassini cannot run on a machine with no account, so a warning about
        that state could never be read. This asserts the page says nothing
        alarming for an empty account list — and that the docstring says why,
        so the next person does not "restore" it.
        """
        tab._on_accounts({"passwd_readable": True, "accounts": [],
                          "profile": "gnome"}, "")
        sub = _subtitle(tab, "Regular accounts")
        assert sub == "None found"
        assert "warning" not in tab._row_accounts.get_css_classes()
        assert "cannot run this app" in setup_mod.ACCOUNTS_NOTE

    def test_the_plasma_profile_reports_the_unit_state(self, tab):
        tab._on_accounts({"passwd_readable": True, "accounts": [{"name": "a"}],
                          "profile": "plasma", "wizard_enabled": "enabled",
                          "wizard_flag_present": False}, "")
        sub = _subtitle(tab, "First-boot wizard")
        assert "plasma-setup.service" in sub and "enabled" in sub
        assert "completion flag absent" in sub

    def test_a_non_plasma_profile_names_its_own_wizard_and_claims_no_unit(self, tab):
        tab._on_accounts({"passwd_readable": True, "accounts": [{"name": "a"}],
                          "profile": "gnome"}, "")
        sub = _subtitle(tab, "First-boot wizard")
        assert "gnome-initial-setup" in sub
        # Asking systemctl about a per-session app would report a state that
        # does not exist, so the page must not imply one.
        assert "enabled" not in sub

    def test_cosmic_names_its_own_wizard(self, tab):
        tab._on_accounts({"passwd_readable": True, "accounts": [{"name": "a"}],
                          "profile": "cosmic"}, "")
        assert "cosmic-initial-setup" in _subtitle(tab, "First-boot wizard")

    def test_an_undeterminable_unit_state_is_not_reported_as_disabled(self, tab):
        tab._on_accounts({"passwd_readable": True, "accounts": [{"name": "a"}],
                          "profile": "plasma", "wizard_enabled": None}, "")
        sub = _subtitle(tab, "First-boot wizard")
        assert "could not tell" in sub
        assert "disabled" not in sub


# ══ Home defaults — the reachable, actionable half ══════════════════════════
class TestHomeDefaults:
    def test_all_present_is_reported_as_complete(self, tab):
        tab._on_skel({"user": "shaniprobe", "home": "/home/shaniprobe",
                      "total": 12, "missing": []}, "")
        assert "All 12" in _subtitle(tab, "Home defaults")

    def test_missing_files_are_named(self, tab):
        tab._on_skel({"user": "a", "home": "/home/a", "total": 12,
                      "missing": [".zshrc", ".inputrc"]}, "")
        sub = _subtitle(tab, "Home defaults")
        assert "2 of 12 missing" in sub
        assert ".zshrc" in sub and ".inputrc" in sub

    def test_the_button_is_offered_only_when_something_is_missing(self, tab):
        tab._on_skel({"user": "a", "home": "/home/a", "total": 3,
                      "missing": []}, "")
        assert tab._btn_provision.get_sensitive() is False
        tab._on_skel({"user": "a", "home": "/home/a", "total": 3,
                      "missing": [".zshrc"]}, "")
        assert tab._btn_provision.get_sensitive() is True

    def test_an_undeterminable_comparison_does_not_offer_the_button(self, tab):
        # total is None means "could not ask". Offering a fix button then would
        # invite the user to run a repair for a question nobody answered.
        tab._on_skel({"user": "a", "home": "/home/a", "total": None,
                      "missing": None}, "could not walk /etc/skel")
        assert tab._btn_provision.get_sensitive() is False
        assert "could not" in _subtitle(tab, "Home defaults").lower()

    def test_the_signed_in_account_is_named(self, tab):
        tab._on_skel({"user": "shaniprobe", "home": "/home/shaniprobe",
                      "total": 1, "missing": []}, "")
        assert "shaniprobe" in _subtitle(tab, "Signed in as")


# ══ The manifest row is a negative finding ══════════════════════════════════
class TestTheManifestFinding:
    def test_it_says_drift_cannot_be_checked(self, tab):
        tab._on_apps({"apps": [{"app": "a"}], "count": 1}, "")
        assert "Not shipped" in _subtitle(tab, "Image app manifest")

    def test_it_says_so_even_when_the_list_is_unreadable(self, tab):
        tab._on_apps({"apps": None, "count": None}, "")
        assert "Not shipped" in _subtitle(tab, "Image app manifest")

    def test_the_count_is_reported_without_implying_reconciliation(self, tab):
        tab._on_apps({"apps": [{"app": "a"}, {"app": "b"}], "count": 2}, "")
        sub = _subtitle(tab, "System flatpaks")
        assert sub == "2 installed system-wide"
        # The word that would turn a count into a claim about correctness.
        assert "reconcil" not in sub.lower()

    def test_the_reader_docstring_records_why_there_is_no_manifest(self):
        assert "upload.sh" in (ss.flatpak_system_apps.__doc__ or "")


# ══ Boundaries ══════════════════════════════════════════════════════════════
class TestBoundaries:
    def test_the_page_never_uses_subprocess(self):
        """Structural, not textual: a docstring naming subprocess must not fail."""
        tree = ast.parse(pathlib.Path(setup_mod.__file__).read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                assert not (isinstance(node.func.value, ast.Name)
                            and node.func.value.id == "subprocess"), \
                    "setup.py must collect through system_status, never subprocess"

    def test_pkexec_appears_only_inside_the_click_handler(self):
        """One privileged call, behind an explicit click.

        An earlier draft of the page read `systemctl is-enabled` unguarded for
        every profile; this holds the shape that matters — `pkexec` is reachable
        from exactly one method, and that method is wired to a button.
        """
        tree = ast.parse(pathlib.Path(setup_mod.__file__).read_text())
        holders = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                body = ast.dump(node)
                if "pkexec" in body:
                    holders.append(node.name)
        assert holders == ["_provision"], holders

    def test_the_click_handler_is_connected_to_the_button(self):
        assert '"clicked", self._provision' in inspect.getsource(SetupTab._build)

    def test_every_reader_hands_its_callback_a_payload_and_an_error(self):
        """The 2-argument `done` contract.

        A reader calling `done(payload)` raises a TypeError *inside a GTK
        callback*, which GLib swallows: the row silently never renders and the
        suite stays green. This is the repo-wide gate, applied to the two
        readers this page adds.
        """
        source = pathlib.Path(ss.__file__).read_text()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            if node.name not in ("account_state", "flatpak_system_apps",
                                 "skel_coverage"):
                continue
            for call in ast.walk(node):
                if (isinstance(call, ast.Call)
                        and isinstance(call.func, ast.Name)
                        and call.func.id == "done"):
                    assert len(call.args) == 2, \
                        f"{node.name}: done() called with {len(call.args)} args"


# ══ Negative controls ═══════════════════════════════════════════════════════
class TestTheControlsBite:
    """Every control breaks the code and requires the matching test to fail."""

    def test_control_collapsing_none_to_empty_breaks_the_readability_test(self):
        original = ss.parse_passwd_accounts
        try:
            ss.parse_passwd_accounts = lambda text: original(text) or []
            assert ss.parse_passwd_accounts(None) == [], "mutation applied"
        finally:
            ss.parse_passwd_accounts = original
        assert ss.parse_passwd_accounts(None) is None, "restore did not happen"

    def test_control_moving_pkexec_out_of_the_click_handler_breaks_the_gate(self):
        src = pathlib.Path(setup_mod.__file__).read_text()
        mutated = src.replace(
            'ss.run_streaming(["pkexec", "shani-user-setup"], line, done)',
            'ss.run_streaming(["shani-user-setup"], line, done)')
        assert mutated != src, "mutation did not apply"
        holders = []
        for node in ast.walk(ast.parse(mutated)):
            if isinstance(node, ast.FunctionDef) and "pkexec" in ast.dump(node):
                holders.append(node.name)
        # With pkexec gone the gate would pass vacuously — which is exactly why
        # this control is here: it shows the gate is reading the AST and not a
        # grep of prose.
        assert holders == []

    def test_control_asserting_the_gate_against_prose_would_fail(self):
        """The trap this file is most likely to fall into.

        `pkexec` appears in this module's own docstring. A grep-based gate would
        fire on that documentation and pass on the thing itself.
        """
        source = pathlib.Path(setup_mod.__file__).read_text()
        assert "pkexec" in source, "prose mentions pkexec (so a grep gate is wrong here)"
        code_only = "\n".join(
            line for line in source.splitlines()
            if not line.lstrip().startswith("#")
        )
        tree = ast.parse(source)
        in_code = any("pkexec" in ast.dump(n) for n in ast.walk(tree))
        assert in_code, "AST sees the call"
        # The docstring is prose; the call is code. Both are present, which is
        # precisely why the gate has to be structural.
        del code_only, tree


class TestNothingSaysMarkdownToALabel:
    """The page's notes are plain text, and this app does not parse markdown.

    Found by rendering, and only by rendering. Every one of these strings was
    correct as a Python string and as a unit-test assertion, and a green suite
    of 35 tests said nothing about it. The notes went into `description=`,
    which is a plain label — not markup — so the `**emphasis**` markers a
    Markdown-shaped habit reaches for were printed on screen exactly as typed,
    asterisks and all.

    This is asserted off the **built widget tree**, not the source. A grep for
    `**` over the module would fire on this file's and the page's own prose —
    the same "a text gate cannot tell prose from behaviour" trap the gate above
    documents — and pass while the screen still showed asterisks.
    """

    # Emphasis markers, in the two forms a Markdown-shaped habit produces.
    MARKERS = ("**", "__")

    def _visible_text(self, page):
        """Every string a reader can actually see, read off the widgets."""
        found = []

        def walk(widget, depth=0):
            assert depth < 40, "widget tree deeper than 40 — a cycle, not a page"
            for getter in ("get_title", "get_subtitle", "get_description"):
                if hasattr(widget, getter):
                    value = getattr(widget, getter)()
                    if value:
                        found.append(value)
            child = widget.get_first_child()
            while child is not None:
                walk(child, depth + 1)
                child = child.get_next_sibling()

        walk(page)
        return found

    def test_no_visible_string_carries_emphasis_markers(self, tab):
        seen = self._visible_text(tab)
        assert seen, "nothing visible was read — the walk found no text at all"

        offenders = [t for t in seen
                     if any(m in t for m in self.MARKERS)]
        assert not offenders, (
            "these strings are shown literally, markers included: "
            + "; ".join(repr(t[:70]) for t in offenders)
        )

    def test_single_asterisk_italics_are_not_used_either(self, tab):
        """`*word*` is the other habit, and it is the one this page first used.

        A bare `*` cannot be searched for naively: the notes legitimately contain
        `+64 more`-style arithmetic-free prose, but they also contain real
        multiplication-free asterisks nowhere — so the check is a paired form
        only, and this one is deliberately narrow rather than clever.
        """
        seen = self._visible_text(tab)
        offenders = [t for t in seen
                     if _PAIRED_ITALIC.search(t)]
        assert not offenders, (
            "italic markers shown literally: "
            + "; ".join(repr(t[:70]) for t in offenders)
        )

    def test_the_check_can_actually_see_a_marker(self, tab):
        """The control: feed the walk a string carrying one, and it must fail.

        Without this the two tests above are the shape this file keeps finding —
        an assertion over an empty or unexamined set that reports a green it did
        not earn.
        """
        marker = "a **bold** claim"
        assert any(m in marker for m in self.MARKERS)
        offenders = [marker]
        assert offenders, "the control's own subject vanished"
